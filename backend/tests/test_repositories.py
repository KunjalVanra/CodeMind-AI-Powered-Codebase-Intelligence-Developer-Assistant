from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import repositories
from app.api.deps import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Analysis, Repository, User


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


def github_metadata() -> dict:
    return {
        "name": "hello-world",
        "owner": {"login": "octocat"},
        "default_branch": "main",
        "private": False,
    }


def test_create_list_get_and_delete_repository(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        repositories,
        "fetch_github_repository",
        lambda owner, name: github_metadata(),
    )

    created = client.post(
        "/api/v1/repositories",
        json={"github_url": "https://github.com/octocat/hello-world"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    repository_id = created.json()["id"]

    listed = client.get("/api/v1/repositories", headers=auth_headers)
    fetched = client.get(
        f"/api/v1/repositories/{repository_id}",
        headers=auth_headers,
    )
    deleted = client.delete(
        f"/api/v1/repositories/{repository_id}",
        headers=auth_headers,
    )

    assert len(listed.json()) == 1
    assert fetched.status_code == 200
    assert fetched.json()["owner_name"] == "octocat"
    assert deleted.status_code == 204
    assert client.get(
        f"/api/v1/repositories/{repository_id}",
        headers=auth_headers,
    ).status_code == 404


def test_duplicate_repository_is_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        repositories,
        "fetch_github_repository",
        lambda owner, name: github_metadata(),
    )
    payload = {"github_url": "https://github.com/octocat/hello-world"}

    assert client.post(
        "/api/v1/repositories",
        json=payload,
        headers=auth_headers,
    ).status_code == 201
    duplicate = client.post(
        "/api/v1/repositories",
        json=payload,
        headers=auth_headers,
    )

    assert duplicate.status_code == 409


def test_invalid_url_and_private_repository_are_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = client.post(
        "/api/v1/repositories",
        json={"github_url": "https://gitlab.com/octocat/hello-world"},
        headers=auth_headers,
    )
    monkeypatch.setattr(
        repositories,
        "fetch_github_repository",
        lambda owner, name: {**github_metadata(), "private": True},
    )
    private = client.post(
        "/api/v1/repositories",
        json={"github_url": "https://github.com/octocat/private"},
        headers=auth_headers,
    )

    assert invalid.status_code == 422
    assert private.status_code == 404
