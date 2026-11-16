from collections.abc import Generator
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.config import settings
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Analysis, Repository, User
from app.services import documentation as documentation_service
from app.services.llm_service import LLMConfigurationError


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


def _create_repository(user_id: int = 1) -> Repository:
    with Session(test_engine) as db:
        repository = Repository(
            user_id=user_id,
            github_url=f"https://github.com/user/repo-{user_id}",
            name=f"repo-{user_id}",
            owner_name="user",
            default_branch="main",
            status="cloned",
        )
        db.add(repository)
        db.commit()
        db.refresh(repository)
        db.expunge(repository)
        return repository


def _parse_summary() -> dict:
    return {
        "total_python_files": 1,
        "languages": {
            "Python": {
                "total_files": 1,
                "files": [
                    {
                        "path": "app.py",
                        "status": "parsed",
                        "classes": [],
                        "interfaces": [],
                        "functions": [
                            {
                                "name": "health",
                                "parent_class": None,
                                "start_line": 5,
                                "end_line": 7,
                                "docstring": None,
                            }
                        ],
                        "imports": [],
                    }
                ],
            }
        },
        "files": [],
    }


def _save_parse_analysis(repository_id: int, summary: dict | None = None) -> None:
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


def _create_cloned_file(tmp_path: Path, repository_id: int) -> Path:
    root = tmp_path / "1" / str(repository_id)
    (root / ".git").mkdir(parents=True)
    (root / "app.py").write_text(
        'from fastapi import APIRouter\n'
        'router = APIRouter()\n'
        '@router.get("/health")\n'
        'def health():\n'
        '    """Report service health."""\n'
        '    return {"status": "healthy"}\n',
        encoding="utf-8",
    )
    return root


def test_documentation_endpoint_generates_and_persists_module_docs(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _save_parse_analysis(repository.id)
    _create_cloned_file(tmp_path, repository.id)
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    observed = {}

    def fake_generate(documentation_type: str, context: str) -> dict:
        observed.update(documentation_type=documentation_type, context=context)
        return {
            "documentation": "# Health module\nDefines the health route.",
            "sufficient_information": True,
            "limitations": [],
        }

    monkeypatch.setattr(
        documentation_service,
        "generate_documentation_response",
        fake_generate,
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/documentation",
        headers=auth_headers,
        json={"documentation_type": "module", "file_path": "app.py"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["documentation_type"] == "module"
    assert body["file_path"] == "app.py"
    assert body["sufficient_information"] is True
    assert body["documentation"].startswith("# Health module")
    assert observed["documentation_type"] == "module"
    assert "healthy" in observed["context"]
    with Session(test_engine) as db:
        generated = (
            db.query(Analysis)
            .filter(Analysis.id == body["analysis_id"])
            .one()
        )
        stored = json.loads(generated.summary)
        assert stored["analysis_type"] == "documentation"
        assert stored["documentation"] == body["documentation"]


def test_api_documentation_uses_only_literal_parsed_routes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_id = 7
    root = tmp_path / "1" / str(repository_id)
    (root / ".git").mkdir(parents=True)
    (root / "routes.py").write_text(
        '@router.get("/health")\n'
        'def health():\n'
        '    return {"status": "ok"}\n'
        '@router.get(DYNAMIC_PATH)\n'
        'def dynamic():\n'
        '    return {}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    captured = {}
    summary = {
        "languages": {
            "Python": {
                "files": [
                    {
                        "path": "routes.py",
                        "status": "parsed",
                        "functions": [
                            {"name": "health", "start_line": 2, "end_line": 3},
                            {"name": "dynamic", "start_line": 5, "end_line": 6},
                        ],
                    }
                ]
            }
        }
    }

    def fake_generate(documentation_type: str, context: str) -> dict:
        captured.update(documentation_type=documentation_type, context=context)
        return {
            "documentation": "GET /health",
            "sufficient_information": True,
            "limitations": [],
        }

    monkeypatch.setattr(
        documentation_service,
        "generate_documentation_response",
        fake_generate,
    )
    result = documentation_service.generate_repository_documentation(
        user_id=1,
        repository_id=repository_id,
        repository_name="repo",
        default_branch="main",
        parse_summary=summary,
        documentation_type="api",
    )

    assert result.sufficient_information is True
    assert '"path_as_declared":"/health"' in captured["context"]
    assert '"method":["GET"]' in captured["context"]
    assert "DYNAMIC_PATH" not in captured["context"]


def test_documentation_endpoint_rejects_traversal_and_invalid_requests(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _save_parse_analysis(repository.id)
    _create_cloned_file(tmp_path, repository.id)
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        documentation_service,
        "generate_documentation_response",
        lambda **kwargs: pytest.fail("Unsafe or invalid requests must not reach Groq"),
    )

    traversal = client.post(
        f"/api/v1/repositories/{repository.id}/documentation",
        headers=auth_headers,
        json={"documentation_type": "module", "file_path": "../app.py"},
    )
    missing_module_path = client.post(
        f"/api/v1/repositories/{repository.id}/documentation",
        headers=auth_headers,
        json={"documentation_type": "module"},
    )
    unsupported_type = client.post(
        f"/api/v1/repositories/{repository.id}/documentation",
        headers=auth_headers,
        json={"documentation_type": "package"},
    )

    assert traversal.status_code == 422
    assert missing_module_path.status_code == 422
    assert unsupported_type.status_code == 422


def test_insufficient_parsed_data_is_reported_without_calling_groq(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_id = 8
    root = tmp_path / "1" / str(repository_id)
    (root / ".git").mkdir(parents=True)
    (root / "empty.py").write_text("value = 1\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        documentation_service,
        "generate_documentation_response",
        lambda **kwargs: pytest.fail("No source symbols should not invoke Groq"),
    )

    result = documentation_service.generate_repository_documentation(
        user_id=1,
        repository_id=repository_id,
        repository_name="repo",
        default_branch="main",
        parse_summary={
            "languages": {
                "Python": {
                    "files": [
                        {
                            "path": "empty.py",
                            "status": "parsed",
                            "functions": [],
                            "classes": [],
                        }
                    ]
                }
            }
        },
        documentation_type="function",
    )

    assert result.sufficient_information is False
    assert "no parsed function definitions" in (result.notice or "")
    assert result.model is None


def test_documentation_endpoint_enforces_auth_owner_parse_and_provider_state(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unauthenticated = client.post(
        "/api/v1/repositories/1/documentation",
        json={"documentation_type": "readme"},
    )
    foreign = _create_repository(user_id=2)
    foreign_response = client.post(
        f"/api/v1/repositories/{foreign.id}/documentation",
        headers=auth_headers,
        json={"documentation_type": "readme"},
    )
    repository = _create_repository()
    missing_parse = client.post(
        f"/api/v1/repositories/{repository.id}/documentation",
        headers=auth_headers,
        json={"documentation_type": "readme"},
    )

    assert unauthenticated.status_code == 401
    assert foreign_response.status_code == 404
    assert missing_parse.status_code == 409


def test_missing_groq_configuration_returns_service_unavailable(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = _create_repository()
    _save_parse_analysis(repository.id)
    _create_cloned_file(tmp_path, repository.id)
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(
        documentation_service,
        "generate_documentation_response",
        lambda **kwargs: (_ for _ in ()).throw(
            LLMConfigurationError("private configuration details")
        ),
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/documentation",
        headers=auth_headers,
        json={"documentation_type": "module", "file_path": "app.py"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "AI documentation generation is not configured"
    assert "private configuration details" not in response.text
