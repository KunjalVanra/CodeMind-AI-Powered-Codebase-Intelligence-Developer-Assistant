from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import repositories
from app.api.deps import get_db
from app.core.config import settings
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import User
from app.services import repository_cloning


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


@pytest.fixture(autouse=True)
def mock_github_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repositories,
        "fetch_github_repository",
        lambda owner, name: {
            "name": name,
            "owner": {"login": owner},
            "default_branch": "main",
            "private": False,
        },
    )


def create_repository(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/v1/repositories",
        json={"github_url": "https://github.com/octocat/hello-world"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_clone_updates_status_and_uses_safe_storage(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_id = create_repository(client, auth_headers)
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    destination = tmp_path / "1" / str(repository_id)

    def fake_clone(url: str, branch: str, user_id: int, repo_id: int) -> Path:
        assert url == "https://github.com/octocat/hello-world"
        assert branch == "main"
        assert user_id == 1
        assert repo_id == repository_id
        destination.mkdir(parents=True)
        (destination / ".git").mkdir()
        return destination

    monkeypatch.setattr(repositories, "clone_repository", fake_clone)
    response = client.post(
        f"/api/v1/repositories/{repository_id}/clone",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cloned"
    assert "storage" not in response.text
    assert str(tmp_path) not in response.text


def test_clone_failure_sets_failed_status(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_id = create_repository(client, auth_headers)
    monkeypatch.setattr(
        repositories,
        "clone_repository",
        lambda *args: (_ for _ in ()).throw(
            repositories.RepositoryCloneError("Git is unavailable")
        ),
    )

    response = client.post(
        f"/api/v1/repositories/{repository_id}/clone",
        headers=auth_headers,
    )
    repository = client.get(
        f"/api/v1/repositories/{repository_id}",
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Git is unavailable"
    assert repository.json()["status"] == "clone_failed"


def test_clone_route_enforces_repository_ownership(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    repository_id = create_repository(client, auth_headers)
    with Session(test_engine) as db:
        other_user = User(
            full_name="Grace Hopper",
            email="grace@example.com",
            hashed_password="unused",
        )
        db.add(other_user)
        db.commit()
        db.refresh(other_user)
        other_headers = {
            "Authorization": f"Bearer {create_access_token(other_user.id)}"
        }

    response = client.post(
        f"/api/v1/repositories/{repository_id}/clone",
        headers=other_headers,
    )

    assert response.status_code == 404


def test_clone_service_uses_safe_path_and_skips_existing_clone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    clone_calls: list[tuple[str, Path]] = []

    def fake_clone(url: str, destination: Path, **options: object) -> None:
        clone_calls.append((url, destination))
        destination.mkdir(parents=True)
        (destination / ".git").mkdir()

    monkeypatch.setattr(repository_cloning.Repo, "clone_from", fake_clone)

    first_path = repository_cloning.clone_repository(
        "https://github.com/octocat/hello-world",
        "main",
        7,
        11,
    )
    second_path = repository_cloning.clone_repository(
        "https://github.com/octocat/hello-world",
        "main",
        7,
        11,
    )

    assert first_path == tmp_path / "7" / "11"
    assert second_path == first_path
    assert len(clone_calls) == 1
