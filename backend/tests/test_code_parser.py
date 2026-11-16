from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import mysql
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.config import settings
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Analysis
from app.services.code_parser import parse_repository


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
    from app.models import User

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


def create_clone(root: Path) -> Path:
    (root / ".git").mkdir(parents=True)
    return root


def test_parser_extracts_functions_classes_imports_and_docstrings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = create_clone(tmp_path / "1" / "2")
    (root / "main.py").write_text(
        '"""Module docs."""\n'
        "from .utils import helper\n"
        "import os\n\n"
        "def outer():\n"
        '    """Outer docs."""\n'
        "    def inner():\n"
        "        return 1\n"
        "    return inner()\n\n"
        "class Service:\n"
        '    """Service docs."""\n'
        "    def run(self):\n"
        "        return True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    result = parse_repository(1, 2)

    parsed = result.files[0]
    assert result.successfully_parsed_files == 1
    assert result.total_classes == 1
    assert result.total_functions == 3
    assert result.total_imports == 2
    assert parsed["classes"][0]["methods"][0]["parent_class"] == "Service"
    assert parsed["classes"][0]["docstring"] == "Service docs."
    assert parsed["functions"][0]["docstring"] == "Outer docs."
    assert parsed["functions"][0]["cyclomatic_complexity"] == 1
    assert parsed["classes"][0]["methods"][0]["cyclomatic_complexity"] == 1
    assert parsed["imports"][0]["relative"] is True
    assert parsed["imports"][0]["module"] == ".utils"


def test_python_parser_records_cyclomatic_complexity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = create_clone(tmp_path / "1" / "2")
    (root / "branches.py").write_text(
        "def choose(items, enabled):\n"
        "    if enabled and items:\n"
        "        for item in items:\n"
        "            if item:\n"
        "                return item\n"
        "    return None\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    result = parse_repository(1, 2)

    assert result.as_dict()["complexity_metric"] == "cyclomatic_complexity_v1"
    assert result.files[0]["functions"][0]["cyclomatic_complexity"] == 5


def test_parser_reports_syntax_errors_empty_and_multiple_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = create_clone(tmp_path / "1" / "2")
    (root / "valid.py").write_text("value = 1\n", encoding="utf-8")
    (root / "empty.py").write_text("", encoding="utf-8")
    (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    result = parse_repository(1, 2)

    assert result.total_python_files == 3
    assert result.successfully_parsed_files == 2
    assert result.syntax_error_files == 1
    assert all("source" not in file_info for file_info in result.files)


def test_parse_endpoint_requires_cloned_owned_repository(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post("/api/v1/repositories/999/parse", headers=auth_headers)
    assert response.status_code == 404


def test_parse_endpoint_persists_and_returns_structure(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.models import Repository

    with Session(test_engine) as db:
        repository = Repository(
            user_id=1,
            github_url="https://github.com/octocat/hello-world",
            name="hello-world",
            owner_name="octocat",
            default_branch="main",
            status="cloned",
        )
        db.add(repository)
        db.commit()
        db.refresh(repository)

    root = create_clone(tmp_path / "1" / str(repository.id))
    (root / "main.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    (root / "app.js").write_text("function start() {}\n", encoding="utf-8")
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    response = client.post(
        f"/api/v1/repositories/{repository.id}/parse",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["total_python_files"] == 1
    assert body["total_functions"] == 1
    assert body["files"][0]["path"] == "main.py"
    assert body["languages"]["JavaScript"]["total_functions"] == 1
    assert body["chunk_count"] > 0
    assert "source_content" not in response.text


def test_analysis_summary_supports_large_mysql_parse_results() -> None:
    summary_type = Analysis.__table__.c.summary.type

    assert isinstance(summary_type.dialect_impl(mysql.dialect()), mysql.LONGTEXT)
