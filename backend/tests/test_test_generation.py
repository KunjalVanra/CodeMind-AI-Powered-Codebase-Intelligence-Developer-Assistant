from collections.abc import Generator
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.config import settings
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Analysis, Repository, User
from app.services import llm_service, test_generation as test_generation_service
from app.services.llm_service import LLMProviderError


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    Base.metadata.create_all(bind=test_engine)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    with Session(test_engine) as db:
        user = User(
            full_name="Ada Lovelace",
            email="ada@example.com",
            hashed_password="unused",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _create_repository(user_id: int = 1, status: str = "cloned") -> Repository:
    with Session(test_engine) as db:
        repository = Repository(
            user_id=user_id,
            github_url=f"https://github.com/user/repo-{user_id}-{status}",
            name=f"repo-{user_id}",
            owner_name="user",
            default_branch="main",
            status=status,
        )
        db.add(repository)
        db.commit()
        db.refresh(repository)
        db.expunge(repository)
        return repository


def _parse_summary(file_path: str = "app.py", language: str = "Python") -> dict:
    file_entry = {
        "path": file_path,
        "status": "parsed",
        "classes": [],
        "interfaces": [],
        "functions": [
            {
                "name": "add",
                "parent_class": None,
                "start_line": 1,
                "end_line": 2,
                "docstring": None,
            }
        ],
        "imports": [],
    }
    return {
        "total_python_files": 1 if language == "Python" else 0,
        "languages": {
            language: {
                "total_files": 1,
                "files": [file_entry],
            }
        },
        "files": [],
    }


def _save_parse_analysis(
    repository_id: int,
    summary: dict | None = None,
) -> None:
    with Session(test_engine) as db:
        db.add(
            Analysis(
                user_id=1,
                repository_id=repository_id,
                status="completed",
                total_files=1,
                summary=json.dumps(summary or _parse_summary()),
            )
        )
        db.commit()


def _create_clone(
    tmp_path: Path,
    repository_id: int,
    *,
    source: str | None = "def add(left, right):\n    return left + right\n",
    source_path: str = "app.py",
) -> Path:
    root = tmp_path / "1" / str(repository_id)
    (root / ".git").mkdir(parents=True)
    if source is not None:
        source_file = root / source_path
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_text(source, encoding="utf-8")
    return root


def _generated_response() -> dict:
    return {
        "generated_test_code": (
            "import pytest\n"
            "from app import add\n\n"
            "def test_adds_values():\n"
            "    assert add(2, 3) == 5\n"
        ),
        "explanation": "Covers the add function with integer inputs.",
        "sufficient_source_information": True,
        "limitations": [],
    }


def _prepare_request(
    repository: Repository,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    summary: dict | None = None,
    source: str | None = "def add(left, right):\n    return left + right\n",
    source_path: str = "app.py",
    language: str = "Python",
) -> None:
    _save_parse_analysis(
        repository.id,
        summary or _parse_summary(source_path, language),
    )
    _create_clone(
        tmp_path,
        repository.id,
        source=source,
        source_path=source_path,
    )
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)


def test_generate_tests_endpoint_returns_mocked_tests_and_persists_result(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _prepare_request(repository, tmp_path, monkeypatch)
    observed = {}

    def fake_generate(*, source_file_path: str, framework: str, context: str) -> dict:
        observed.update(
            source_file_path=source_file_path,
            framework=framework,
            context=context,
        )
        return _generated_response()

    monkeypatch.setattr(
        test_generation_service,
        "generate_unit_test_response",
        fake_generate,
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py", "framework": "pytest"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_file_path"] == "app.py"
    assert body["language"] == "Python"
    assert body["test_framework"] == "pytest"
    assert body["generated_test_code"] == _generated_response()["generated_test_code"]
    assert body["sufficient_source_information"] is True
    assert body["verified"] is False
    assert body["verification_status"] == "not_executed"
    assert any("not verified" in item for item in body["limitations"])
    assert observed["framework"] == "pytest"
    assert "def add(left, right)" in observed["context"]

    with Session(test_engine) as db:
        analysis = db.get(Analysis, body["analysis_id"])
        stored = json.loads(analysis.summary)
        assert stored["analysis_type"] == "test_generation"
        assert stored["generated_test_code"] == body["generated_test_code"]
        assert stored["verified"] is False
        assert analysis.total_files == 1


def test_generate_tests_authentication_ownership_and_clone_requirements(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    unauthenticated = client.post(
        "/api/v1/repositories/1/generate-tests",
        json={"file_path": "app.py"},
    )
    foreign = _create_repository(user_id=2)
    foreign_response = client.post(
        f"/api/v1/repositories/{foreign.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )
    connected = _create_repository(status="connected")
    connected_response = client.post(
        f"/api/v1/repositories/{connected.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )

    assert unauthenticated.status_code == 401
    assert foreign_response.status_code == 404
    assert connected_response.status_code == 409


def test_generate_tests_requires_completed_parse_analysis(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    repository = _create_repository()
    response = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )
    assert response.status_code == 409
    assert "parse the repository first" in response.json()["detail"]


@pytest.mark.parametrize(
    ("file_path", "expected_status"),
    [
        ("../outside.py", 422),
        ("C:\\private\\source.py", 422),
        ("missing.py", 404),
    ],
)
def test_generate_tests_rejects_unsafe_or_missing_paths(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    file_path: str,
    expected_status: int,
) -> None:
    repository = _create_repository()
    _prepare_request(repository, tmp_path, monkeypatch)

    response = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": file_path},
    )

    assert response.status_code == expected_status


def test_generate_tests_reports_missing_source_file(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _prepare_request(repository, tmp_path, monkeypatch, source=None)

    response = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )

    assert response.status_code == 404


def test_generate_tests_reports_empty_source_without_calling_ai(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _prepare_request(repository, tmp_path, monkeypatch, source="")
    monkeypatch.setattr(
        test_generation_service,
        "generate_unit_test_response",
        lambda **kwargs: pytest.fail("Empty source must not be sent to Groq"),
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )

    assert response.status_code == 200
    assert response.json()["sufficient_source_information"] is False
    assert response.json()["generated_test_code"] == ""


def test_generate_tests_rejects_unsupported_language_and_framework(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _prepare_request(
        repository,
        tmp_path,
        monkeypatch,
        summary=_parse_summary("app.js", "JavaScript"),
        source="export function add(left, right) { return left + right }\n",
        source_path="app.js",
        language="JavaScript",
    )

    unsupported_language = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.js"},
    )
    unsupported_framework = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py", "framework": "nose"},
    )

    assert unsupported_language.status_code == 422
    assert "Python source files only" in unsupported_language.json()["detail"]
    assert unsupported_framework.status_code == 422


def test_generate_tests_reports_insufficient_source_without_ai(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _prepare_request(repository, tmp_path, monkeypatch, source="VERSION = '1.0'\n")
    monkeypatch.setattr(
        test_generation_service,
        "generate_unit_test_response",
        lambda **kwargs: pytest.fail("No testable symbols must not reach Groq"),
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )

    assert response.status_code == 200
    assert response.json()["sufficient_source_information"] is False
    assert "No public functions or classes" in response.json()["explanation"]


def test_generate_tests_maps_ai_provider_and_malformed_output_errors(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _prepare_request(repository, tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "GROQ_API_KEY", SecretStr("test-key"))

    class ErrorGroq:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **params: (_ for _ in ()).throw(
                        TimeoutError("private provider details")
                    )
                )
            )

    monkeypatch.setattr(llm_service, "Groq", ErrorGroq)
    failed = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )
    assert failed.status_code == 503
    assert "private provider details" not in failed.text

    class MalformedGroq:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **params: SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(content="not JSON")
                            )
                        ]
                    )
                )
            )

    monkeypatch.setattr(llm_service, "Groq", MalformedGroq)
    malformed = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )
    assert malformed.status_code == 503
    assert malformed.json()["detail"] == (
        "AI test generation service is temporarily unavailable"
    )

    with pytest.raises(LLMProviderError):
        llm_service.generate_unit_test_response(
            source_file_path="app.py",
            framework="pytest",
            context="source context",
        )


def test_generate_tests_handles_missing_groq_configuration(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _prepare_request(repository, tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "GROQ_API_KEY", None)
    monkeypatch.setattr(
        llm_service,
        "Groq",
        lambda **kwargs: pytest.fail("Groq client must not be constructed"),
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "AI test generation is not configured"


def test_generate_tests_accepts_unittest_preference(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _prepare_request(repository, tmp_path, monkeypatch)
    monkeypatch.setattr(
        test_generation_service,
        "generate_unit_test_response",
        lambda **kwargs: {
            "generated_test_code": (
                "import unittest\n"
                "from app import add\n\n"
                "class AddTests(unittest.TestCase):\n"
                "    def test_adds_values(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n"
            ),
            "explanation": "Covers add with integer inputs.",
            "sufficient_source_information": True,
            "limitations": [],
        },
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/generate-tests",
        headers=auth_headers,
        json={"file_path": "app.py", "framework": "unittest"},
    )

    assert response.status_code == 200
    assert response.json()["test_framework"] == "unittest"


def test_generate_tests_requires_file_path_and_route_is_registered(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/repositories/1/generate-tests",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 422
    operation = app.openapi()["paths"][
        "/api/v1/repositories/{repository_id}/generate-tests"
    ]
    assert "post" in operation
