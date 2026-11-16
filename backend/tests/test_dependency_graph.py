from collections.abc import Generator
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Analysis, Repository, User
from app.services.dependency_graph import build_dependency_graph


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def _parse_summary() -> dict:
    return {
        "total_python_files": 3,
        "languages": {
            "Python": {
                "files": [
                    {
                        "path": "pkg/main.py",
                        "status": "parsed",
                        "imports": [
                            {
                                "module": ".utils",
                                "relative": True,
                                "level": 1,
                                "names": ["helper"],
                                "start_line": 1,
                            },
                            {"module": "os", "start_line": 2},
                            {"module": "os", "start_line": 3},
                            {
                                "module": ".missing",
                                "relative": True,
                                "level": 1,
                                "start_line": 4,
                            },
                        ],
                    },
                    {
                        "path": "pkg/utils.py",
                        "status": "parsed",
                        "imports": [],
                    },
                ],
            },
            "TypeScript": {
                "files": [
                    {
                        "path": "src/a.ts",
                        "status": "parsed",
                        "imports": [{"module": "./b", "start_line": 1}],
                    },
                    {
                        "path": "src/b.ts",
                        "status": "parsed",
                        "imports": [{"module": "./a", "start_line": 1}],
                    },
                ],
            },
        },
    }


def test_dependency_graph_resolves_imports_deduplicates_and_keeps_cycles() -> None:
    graph = build_dependency_graph(_parse_summary())

    assert graph["summary"] == {
        "total_files": 4,
        "nodes": 4,
        "edges": 5,
        "internal_dependencies": 3,
        "external_dependencies": 1,
        "unresolved_imports": 1,
    }
    assert {
        (edge["source"], edge["target"], edge["dependency_type"])
        for edge in graph["edges"]
        if edge["dependency_type"] == "internal"
    } == {
        ("pkg/main.py", "pkg/utils.py", "internal"),
        ("src/a.ts", "src/b.ts", "internal"),
        ("src/b.ts", "src/a.ts", "internal"),
    }
    assert sum(
        edge["dependency"] == "os" for edge in graph["edges"]
    ) == 1
    assert any(
        edge["dependency"] == ".missing"
        and edge["dependency_type"] == "unresolved"
        for edge in graph["edges"]
    )


def test_dependency_graph_resolves_rust_crate_modules() -> None:
    graph = build_dependency_graph(
        {
            "languages": {
                "Rust": {
                    "files": [
                        {
                            "path": "src/lib.rs",
                            "status": "parsed",
                            "imports": [{"module": "crate::util", "start_line": 1}],
                        },
                        {
                            "path": "src/util/mod.rs",
                            "status": "parsed",
                            "imports": [],
                        },
                    ],
                },
            },
        }
    )

    assert graph["edges"][0]["target"] == "src/util/mod.rs"
    assert graph["edges"][0]["dependency_type"] == "internal"


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


def _add_user_and_token(user_id: int = 1) -> dict[str, str]:
    with Session(test_engine) as db:
        user = User(
            id=user_id,
            full_name="Ada Lovelace",
            email=f"ada{user_id}@example.com",
            hashed_password="unused",
        )
        db.add(user)
        db.commit()
        token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _add_repository(user_id: int = 1) -> Repository:
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


def _add_analysis(repository: Repository, summary: dict) -> int:
    with Session(test_engine) as db:
        analysis = Analysis(
            user_id=repository.user_id,
            repository_id=repository.id,
            status="completed",
            summary=json.dumps(summary),
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        return analysis.id


def test_dependency_endpoint_requires_auth_owner_and_parse_data(
    client: TestClient,
) -> None:
    assert client.get("/api/v1/repositories/1/dependencies").status_code == 401
    headers = _add_user_and_token()
    assert client.get(
        "/api/v1/repositories/999/dependencies",
        headers=headers,
    ).status_code == 404

    repository = _add_repository()
    assert client.get(
        f"/api/v1/repositories/{repository.id}/dependencies",
        headers=headers,
    ).status_code == 409

    _add_user_and_token(user_id=2)
    other_repository = _add_repository(user_id=2)
    _add_analysis(other_repository, _parse_summary())
    assert client.get(
        f"/api/v1/repositories/{other_repository.id}/dependencies",
        headers=headers,
    ).status_code == 404


def test_dependency_endpoint_returns_graph_and_unsupported_languages(
    client: TestClient,
) -> None:
    headers = _add_user_and_token()
    repository = _add_repository()
    scan_summary = {
        "total_source_files": 4,
        "languages": {
            "Python": {"files": 2, "lines": 10},
            "TypeScript": {"files": 2, "lines": 20},
            "HTML": {"files": 1, "lines": 5},
        },
    }
    scan_id = _add_analysis(repository, scan_summary)
    parse_id = _add_analysis(repository, _parse_summary())

    response = client.get(
        f"/api/v1/repositories/{repository.id}/dependencies",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_id"] == parse_id
    assert body["repository_id"] == repository.id
    assert body["status"] == "completed"
    assert body["summary"]["nodes"] == 4
    assert body["summary"]["edges"] == 5
    assert body["unsupported_languages"] == ["HTML"]
    assert scan_id < parse_id
    assert "source_content" not in response.text
