import json
from collections.abc import Generator
from pathlib import Path

import chromadb
import pytest
from chromadb.config import Settings as ChromaSettings
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import repositories as repository_api
from app.api.deps import get_db
from app.core.config import settings
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Analysis, Repository, User
from app.services import embedding_service, vector_indexing
from app.services import vector_store
from app.services.semantic_retrieval import retrieve_code
from app.services.vector_indexing import index_chunks
from app.services.vector_store import get_collection


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
def vector_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vector_path = tmp_path / "vectors"
    monkeypatch.setattr(settings, "VECTOR_DB_DIR", vector_path)
    monkeypatch.setattr(
        settings,
        "VECTOR_COLLECTION_NAME",
        f"test_{vector_path.name}_{id(vector_path)}",
    )
    monkeypatch.setattr(
        "app.services.vector_store._client",
        chromadb.PersistentClient(
            path=str(vector_path),
            settings=ChromaSettings(anonymized_telemetry=False),
        ),
    )
    return vector_path


@pytest.fixture()
def fake_embedding_model(monkeypatch: pytest.MonkeyPatch):
    class FakeArray:
        def __init__(self, value):
            self.value = value

        def tolist(self):
            return self.value

    class FakeModel:
        def __init__(self):
            self.calls = []

        def encode(self, texts, **kwargs):
            self.calls.append((list(texts), kwargs))
            return FakeArray([[float(len(text)), 1.0, 0.5] for text in texts])

    model = FakeModel()
    monkeypatch.setattr(embedding_service, "_model", model)
    return model


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


def sample_chunk(chunk_id: str = "chunk-1", content: str = "def answer(): pass") -> dict:
    return {
        "chunk_id": chunk_id,
        "file_path": "src/example.py",
        "language": "Python",
        "chunk_type": "function",
        "name": "answer",
        "parent_type": "Example",
        "start_line": 4,
        "end_line": 8,
        "source_content": content,
    }


def test_embedding_generation_is_batched_and_reuses_model(
    fake_embedding_model,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "EMBEDDING_BATCH_SIZE", 2)

    embeddings = embedding_service.generate_embeddings(["first", "second"])

    assert len(embeddings) == 2
    assert embeddings[0] == [5.0, 1.0, 0.5]
    assert fake_embedding_model.calls[0][1]["batch_size"] == 2
    assert embedding_service.get_embedding_model() is fake_embedding_model


def test_indexing_persists_metadata_and_repeated_upsert(
    vector_db: Path,
    fake_embedding_model,
) -> None:
    chunks = [sample_chunk()]

    first = index_chunks(chunks, user_id=4, repository_id=9, analysis_id=2)
    second = index_chunks(chunks, user_id=4, repository_id=9, analysis_id=2)
    stored = get_collection().get(include=["documents", "metadatas"])

    assert first["indexed_chunks"] == 1
    assert second["indexed_chunks"] == 1
    assert get_collection().count() == 1
    assert stored["documents"] == ["def answer(): pass"]
    metadata = stored["metadatas"][0]
    assert metadata["user_id"] == 4
    assert metadata["repository_id"] == 9
    assert metadata["analysis_id"] == 2
    assert metadata["chunk_id"] == "chunk-1"
    assert metadata["file_path"] == "src/example.py"
    assert metadata["symbol"] == "answer"
    assert metadata["parent_type"] == "Example"
    assert metadata["start_line"] == 4
    assert metadata["end_line"] == 8
    assert vector_db.exists()

    vector_store._client = None
    reopened_collection = get_collection()
    assert reopened_collection.count() == 1


def test_empty_and_invalid_chunks_are_counted_as_failed(
    vector_db: Path,
    fake_embedding_model,
) -> None:
    result = index_chunks(
        [sample_chunk(), sample_chunk("empty", "  "), None],
        user_id=1,
        repository_id=2,
        analysis_id=3,
    )

    assert result["total_chunks"] == 3
    assert result["indexed_chunks"] == 1
    assert result["failed_chunks"] == 2


def test_indexing_batches_and_embedding_failures_are_reported(
    vector_db: Path,
    fake_embedding_model,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "VECTOR_INDEX_BATCH_SIZE", 2)
    result = index_chunks(
        [sample_chunk(f"chunk-{index}") for index in range(5)],
        user_id=1,
        repository_id=2,
        analysis_id=3,
    )
    assert len(fake_embedding_model.calls) == 3
    assert result["indexed_chunks"] == 5

    monkeypatch.setattr(
        vector_indexing,
        "generate_embeddings",
        lambda texts: (_ for _ in ()).throw(RuntimeError("model failure")),
    )
    failed = index_chunks(
        [sample_chunk("bad-1"), sample_chunk("bad-2")],
        user_id=1,
        repository_id=2,
        analysis_id=3,
    )
    assert failed["failed_chunks"] == 2


def test_vector_storage_failure_is_reported_as_failed_batch(
    vector_db: Path,
    fake_embedding_model,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenCollection:
        name = "broken"

        def upsert(self, **kwargs):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(
        vector_indexing,
        "get_collection",
        lambda: BrokenCollection(),
    )

    result = index_chunks([sample_chunk()], 1, 2, 3)

    assert result["indexed_chunks"] == 0
    assert result["failed_chunks"] == 1


def test_retrieval_filters_by_user_and_repository(
    vector_db: Path,
    fake_embedding_model,
) -> None:
    index_chunks([sample_chunk()], user_id=1, repository_id=10, analysis_id=1)
    index_chunks([sample_chunk("other", "private user code")], 2, 10, 2)
    index_chunks([sample_chunk("another-repo", "different repository")], 1, 11, 3)

    owned_results = retrieve_code("find answer function", user_id=1, repository_id=10)
    other_user_results = retrieve_code("find answer", user_id=3, repository_id=10)

    assert len(owned_results) == 1
    assert owned_results[0]["metadata"]["user_id"] == 1
    assert owned_results[0]["metadata"]["repository_id"] == 10
    assert other_user_results == []


def test_retrieval_handles_missing_collection_indexes_gracefully(
    vector_db: Path,
    fake_embedding_model,
) -> None:
    assert retrieve_code("find a function", user_id=1, repository_id=1) == []


def _create_owned_cloned_repository(user_id: int = 1) -> Repository:
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


def _add_completed_analysis(repository: Repository, chunks: list[dict] | None) -> int:
    summary = {"chunking": {"chunks": chunks}} if chunks is not None else {}
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


def test_index_endpoint_response_excludes_sources_and_vectors(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _create_owned_cloned_repository()
    analysis_id = _add_completed_analysis(repository, [sample_chunk()])
    monkeypatch.setattr(
        repository_api,
        "index_chunks",
        lambda chunks, user_id, repository_id, analysis_id: {
            "total_chunks": len(chunks),
            "indexed_chunks": len(chunks),
            "failed_chunks": 0,
            "collection_name": "codemind_code_chunks",
        },
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/index",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "indexed"
    assert body["analysis_id"] == analysis_id
    assert body["indexed_chunks"] == 1
    assert "source_content" not in response.text
    assert "embedding" not in response.text
    assert "C:\\" not in response.text


def test_index_endpoint_requires_auth_clone_and_completed_chunks(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    unauthorized = client.post("/api/v1/repositories/1/index")
    assert unauthorized.status_code == 401

    repository = _create_owned_cloned_repository()
    with Session(test_engine) as db:
        stored = db.get(Repository, repository.id)
        stored.status = "connected"
        db.commit()
    not_cloned = client.post(
        f"/api/v1/repositories/{repository.id}/index",
        headers=auth_headers,
    )
    assert not_cloned.status_code == 409

    with Session(test_engine) as db:
        stored = db.get(Repository, repository.id)
        stored.status = "cloned"
        db.commit()
    no_analysis = client.post(
        f"/api/v1/repositories/{repository.id}/index",
        headers=auth_headers,
    )
    assert no_analysis.status_code == 409

    _add_completed_analysis(repository, [])
    no_chunks = client.post(
        f"/api/v1/repositories/{repository.id}/index",
        headers=auth_headers,
    )
    assert no_chunks.status_code == 409


def test_index_endpoint_denies_another_users_repository(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    repository = _create_owned_cloned_repository(user_id=2)

    response = client.post(
        f"/api/v1/repositories/{repository.id}/index",
        headers=auth_headers,
    )

    assert response.status_code == 404


def test_index_endpoint_selects_latest_completed_analysis(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _create_owned_cloned_repository()
    _add_completed_analysis(repository, [sample_chunk("older")])
    latest_id = _add_completed_analysis(repository, [sample_chunk("latest")])
    selected = {}

    def fake_index(chunks, user_id, repository_id, analysis_id):
        selected["chunk"] = chunks[0]["chunk_id"]
        selected["analysis_id"] = analysis_id
        return {
            "total_chunks": 1,
            "indexed_chunks": 1,
            "failed_chunks": 0,
            "collection_name": "codemind_code_chunks",
        }

    monkeypatch.setattr(repository_api, "index_chunks", fake_index)
    response = client.post(
        f"/api/v1/repositories/{repository.id}/index",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert selected == {"chunk": "latest", "analysis_id": latest_id}
