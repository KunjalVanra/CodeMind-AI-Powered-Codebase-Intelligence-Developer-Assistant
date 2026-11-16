import hashlib
import math
from collections.abc import Sequence

from app.core.config import settings
from app.services.embedding_service import EmbeddingError, generate_embeddings
from app.services.vector_store import VectorStoreError, get_collection


class VectorIndexingError(Exception):
    """Raised when vector indexing cannot access its storage or model."""


def _record_id(user_id: int, repository_id: int, chunk_id: str) -> str:
    return hashlib.sha256(
        f"{user_id}:{repository_id}:{chunk_id}".encode("utf-8")
    ).hexdigest()


def _valid_chunk(chunk: object) -> bool:
    if not isinstance(chunk, dict):
        return False
    text = chunk.get("source_content")
    return (
        isinstance(chunk.get("chunk_id"), str)
        and bool(chunk["chunk_id"])
        and isinstance(text, str)
        and bool(text.strip())
        and isinstance(chunk.get("file_path"), str)
        and isinstance(chunk.get("language"), str)
        and isinstance(chunk.get("chunk_type"), str)
        and isinstance(chunk.get("start_line"), int)
        and isinstance(chunk.get("end_line"), int)
    )


def _metadata(
    chunk: dict,
    user_id: int,
    repository_id: int,
    analysis_id: int,
) -> dict:
    metadata = {
        "user_id": int(user_id),
        "repository_id": int(repository_id),
        "analysis_id": int(analysis_id),
        "chunk_id": chunk["chunk_id"],
        "file_path": chunk["file_path"],
        "language": chunk["language"],
        "chunk_type": chunk["chunk_type"],
        "symbol": chunk.get("name") or "",
        "parent_type": chunk.get("parent_type") or "",
        "start_line": int(chunk["start_line"]),
        "end_line": int(chunk["end_line"]),
    }
    return metadata


def index_chunks(
    chunks: Sequence[object],
    user_id: int,
    repository_id: int,
    analysis_id: int,
) -> dict:
    total_chunks = len(chunks)
    valid_chunks = [chunk for chunk in chunks if _valid_chunk(chunk)]
    failed_chunks = total_chunks - len(valid_chunks)
    indexed_chunks = 0

    try:
        collection = get_collection()
    except VectorStoreError as exc:
        raise VectorIndexingError("Vector storage is unavailable") from exc

    batch_size = max(1, settings.VECTOR_INDEX_BATCH_SIZE)
    for offset in range(0, len(valid_chunks), batch_size):
        batch = valid_chunks[offset:offset + batch_size]
        documents = [chunk["source_content"] for chunk in batch]
        try:
            embeddings = generate_embeddings(documents)
            if len(embeddings) != len(batch):
                raise EmbeddingError("Embedding count did not match chunk count")
            for embedding in embeddings:
                if not embedding or not all(
                    math.isfinite(value) for value in embedding
                ):
                    raise EmbeddingError("Embedding output is invalid")
            collection.upsert(
                ids=[
                    _record_id(user_id, repository_id, chunk["chunk_id"])
                    for chunk in batch
                ],
                embeddings=embeddings,
                documents=documents,
                metadatas=[
                    _metadata(chunk, user_id, repository_id, analysis_id)
                    for chunk in batch
                ],
            )
            indexed_chunks += len(batch)
        except Exception:
            failed_chunks += len(batch)

    return {
        "total_chunks": total_chunks,
        "indexed_chunks": indexed_chunks,
        "failed_chunks": failed_chunks,
        "collection_name": collection.name,
    }
