import math

from app.services.embedding_service import EmbeddingError, generate_embeddings
from app.services.vector_store import VectorStoreError, get_collection


class SemanticRetrievalError(Exception):
    """Raised when semantic code retrieval cannot be completed."""


def _scope_filter(user_id: int, repository_id: int) -> dict:
    return {
        "$and": [
            {"user_id": {"$eq": int(user_id)}},
            {"repository_id": {"$eq": int(repository_id)}},
        ]
    }


def _validate_scope(user_id: int, repository_id: int) -> None:
    if user_id <= 0 or repository_id <= 0:
        raise ValueError("Valid user and repository IDs are required")


def has_indexed_chunks(user_id: int, repository_id: int) -> bool:
    _validate_scope(user_id, repository_id)
    try:
        collection = get_collection()
        stored = collection.get(
            where=_scope_filter(user_id, repository_id),
            limit=1,
            include=["metadatas"],
        )
        return bool(stored.get("ids"))
    except (EmbeddingError, VectorStoreError) as exc:
        raise SemanticRetrievalError("Semantic retrieval is unavailable") from exc
    except Exception as exc:
        raise SemanticRetrievalError("Semantic retrieval failed") from exc


def retrieve_code(
    query: str,
    user_id: int,
    repository_id: int,
    limit: int = 5,
) -> list[dict]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query must not be empty")
    _validate_scope(user_id, repository_id)
    limit = max(1, min(int(limit), 50))

    try:
        collection = get_collection()
        if collection.count() == 0:
            return []
        query_embedding = generate_embeddings([query.strip()])[0]
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            where=_scope_filter(user_id, repository_id),
            include=["documents", "metadatas", "distances"],
        )
    except (EmbeddingError, VectorStoreError) as exc:
        raise SemanticRetrievalError("Semantic retrieval is unavailable") from exc
    except Exception as exc:
        raise SemanticRetrievalError("Semantic retrieval failed") from exc

    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    distances = result.get("distances") or [[]]
    identifiers = result.get("ids") or [[]]
    matches = []
    for identifier, document, metadata, distance in zip(
        identifiers[0], documents[0], metadatas[0], distances[0]
    ):
        if not isinstance(document, str) or not isinstance(metadata, dict):
            continue
        try:
            numeric_distance = float(distance)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(numeric_distance):
            continue
        matches.append(
            {
                "id": identifier,
                "source_content": document,
                "metadata": metadata,
                "distance": numeric_distance,
            }
        )
    matches.sort(key=lambda match: match["distance"])

    unique_matches = []
    seen_chunks = set()
    for match in matches:
        chunk_id = match["metadata"].get("chunk_id")
        dedupe_key = (
            ("chunk", chunk_id)
            if isinstance(chunk_id, str) and chunk_id
            else ("record", match["id"])
        )
        if dedupe_key in seen_chunks:
            continue
        seen_chunks.add(dedupe_key)
        unique_matches.append(match)
    return unique_matches[:limit]
