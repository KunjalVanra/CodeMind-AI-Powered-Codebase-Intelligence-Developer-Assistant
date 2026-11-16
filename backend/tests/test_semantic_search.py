from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import repositories as repository_api
from app.api.deps import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Repository, User
from app.services import embedding_service, semantic_retrieval
from app.services.semantic_retrieval import (
    SemanticRetrievalError,
    retrieve_code,
)


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
        return repository


def _match(
    *,
    file_path: str = "src/scoring.py",
    distance: float = 0.15,
    chunk_id: str = "chunk-1",
) -> dict:
    return {
        "source_content": "def calculate_score():\n    return 42",
        "metadata": {
            "chunk_id": chunk_id,
            "file_path": file_path,
            "language": "Python",
            "chunk_type": "function",
            "symbol": "calculate_score",
            "parent_type": "Scorer",
            "start_line": 3,
            "end_line": 4,
        },
        "distance": distance,
    }


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def encode(self, texts: list[str], **kwargs):
        self.calls.append((list(texts), kwargs))

        class FakeArray:
            def tolist(self) -> list[list[float]]:
                return [[0.1, 0.2, 0.3] for _ in texts]

        return FakeArray()


class FakeCollection:
    def __init__(self, *, stored_ids=None, result=None) -> None:
        self.stored_ids = stored_ids or []
        self.result = result or {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        self.get_calls: list[dict] = []
        self.query_calls: list[dict] = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return {"ids": self.stored_ids}

    def count(self) -> int:
        return 10

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return self.result


def test_retrieval_embeds_query_and_applies_top_k_and_scope_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = FakeEmbeddingModel()
    collection = FakeCollection(
        stored_ids=["indexed"],
        result={
            "ids": [["chunk-1", "chunk-2", "chunk-3"]],
            "documents": [["one", "two", "three"]],
            "metadatas": [
                [
                    {"chunk_id": "one"},
                    {"chunk_id": "two"},
                    {"chunk_id": "three"},
                ]
            ],
            "distances": [[0.3, 0.1, 0.2]],
        },
    )
    monkeypatch.setattr(embedding_service, "_model", model)
    monkeypatch.setattr(semantic_retrieval, "get_collection", lambda: collection)

    assert semantic_retrieval.has_indexed_chunks(user_id=4, repository_id=9)
    matches = retrieve_code(
        "  Where is score calculated?  ",
        user_id=4,
        repository_id=9,
        limit=2,
    )

    assert model.calls[0][0] == ["Where is score calculated?"]
    query = collection.query_calls[0]
    assert query["n_results"] == 2
    assert query["query_embeddings"] == [[0.1, 0.2, 0.3]]
    assert query["where"] == {
        "$and": [
            {"user_id": {"$eq": 4}},
            {"repository_id": {"$eq": 9}},
        ]
    }
    assert [match["source_content"] for match in matches] == ["two", "three"]
    assert collection.get_calls[0]["where"] == query["where"]


def test_retrieval_deduplicates_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = FakeCollection(
        result={
            "ids": [["duplicate-a", "duplicate-b"]],
            "documents": [["code A", "code B"]],
            "metadatas": [[{"chunk_id": "same"}, {"chunk_id": "same"}]],
            "distances": [[0.2, 0.1]],
        },
    )
    monkeypatch.setattr(semantic_retrieval, "get_collection", lambda: collection)
    monkeypatch.setattr(
        semantic_retrieval,
        "generate_embeddings",
        lambda texts: [[0.1, 0.2]],
    )

    matches = retrieve_code("query", user_id=1, repository_id=2)

    assert len(matches) == 1
    assert matches[0]["source_content"] == "code B"


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": " \t "},
        {"query": "x" * 2001},
        {"query": "valid", "top_k": 0},
        {"query": "valid", "top_k": 11},
    ],
)
def test_search_rejects_invalid_query_or_top_k(
    client: TestClient,
    auth_headers: dict[str, str],
    payload: dict,
) -> None:
    repository = _create_repository()
    response = client.post(
        f"/api/v1/repositories/{repository.id}/search",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422


def test_search_endpoint_returns_ranked_safe_results_and_uses_top_k(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _create_repository()
    calls = {}
    monkeypatch.setattr(repository_api, "has_indexed_chunks", lambda user_id, repo_id: True)

    def fake_retrieve(query, user_id, repository_id, limit):
        calls.update(
            query=query,
            user_id=user_id,
            repository_id=repository_id,
            limit=limit,
        )
        return [
            _match(distance=0.1),
            _match(distance=0.2, chunk_id="chunk-2"),
            _match(file_path="C:\\private\\secret.py", chunk_id="unsafe-path"),
        ]

    monkeypatch.setattr(repository_api, "retrieve_code", fake_retrieve)
    response = client.post(
        f"/api/v1/repositories/{repository.id}/search",
        headers=auth_headers,
        json={"query": "Where is project score calculated?", "top_k": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_id"] == repository.id
    assert body["query"] == "Where is project score calculated?"
    assert body["total_results"] == 2
    assert body["results"][0]["similarity"] == pytest.approx(0.9)
    assert body["results"][0]["file_path"] == "src/scoring.py"
    assert body["results"][0]["snippet"].startswith("def calculate_score")
    assert calls == {
        "query": "Where is project score calculated?",
        "user_id": 1,
        "repository_id": repository.id,
        "limit": 2,
    }
    assert "embedding" not in response.text.lower()
    assert "C:\\" not in response.text
    assert "source_content" not in body["results"][0]


def test_search_requires_auth_and_owned_repository(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unauthenticated = client.post(
        "/api/v1/repositories/1/search",
        json={"query": "score"},
    )
    assert unauthenticated.status_code == 401

    foreign_repository = _create_repository(user_id=2)
    monkeypatch.setattr(
        repository_api,
        "has_indexed_chunks",
        lambda *args: pytest.fail("ownership must be checked before vector access"),
    )
    response = client.post(
        f"/api/v1/repositories/{foreign_repository.id}/search",
        headers=auth_headers,
        json={"query": "score"},
    )
    assert response.status_code == 404


def test_search_handles_missing_and_unindexed_repositories(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = client.post(
        "/api/v1/repositories/999/search",
        headers=auth_headers,
        json={"query": "score"},
    )
    assert missing.status_code == 404

    repository = _create_repository()
    monkeypatch.setattr(repository_api, "has_indexed_chunks", lambda *args: False)
    unindexed = client.post(
        f"/api/v1/repositories/{repository.id}/search",
        headers=auth_headers,
        json={"query": "score"},
    )
    assert unindexed.status_code == 409


def test_search_returns_empty_results_and_maps_storage_errors(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _create_repository()
    monkeypatch.setattr(repository_api, "has_indexed_chunks", lambda *args: True)
    monkeypatch.setattr(repository_api, "retrieve_code", lambda *args, **kwargs: [])
    empty = client.post(
        f"/api/v1/repositories/{repository.id}/search",
        headers=auth_headers,
        json={"query": "nothing"},
    )
    assert empty.status_code == 200
    assert empty.json()["total_results"] == 0
    assert empty.json()["results"] == []

    monkeypatch.setattr(
        repository_api,
        "has_indexed_chunks",
        lambda *args: (_ for _ in ()).throw(
            SemanticRetrievalError("internal storage detail")
        ),
    )
    failed = client.post(
        f"/api/v1/repositories/{repository.id}/search",
        headers=auth_headers,
        json={"query": "nothing"},
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == "Semantic search is unavailable"
    assert "internal storage detail" not in failed.text


def test_embedding_and_vector_database_failures_are_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        semantic_retrieval,
        "get_collection",
        lambda: (_ for _ in ()).throw(RuntimeError("database secret")),
    )
    with pytest.raises(SemanticRetrievalError):
        semantic_retrieval.has_indexed_chunks(user_id=1, repository_id=2)

    monkeypatch.setattr(
        semantic_retrieval,
        "get_collection",
        lambda: FakeCollection(),
    )
    monkeypatch.setattr(
        semantic_retrieval,
        "generate_embeddings",
        lambda texts: (_ for _ in ()).throw(RuntimeError("model details")),
    )
    with pytest.raises(SemanticRetrievalError):
        retrieve_code("query", user_id=1, repository_id=2)


def test_search_route_is_registered_in_openapi() -> None:
    assert "post" in app.openapi()["paths"][
        "/api/v1/repositories/{repository_id}/search"
    ]
