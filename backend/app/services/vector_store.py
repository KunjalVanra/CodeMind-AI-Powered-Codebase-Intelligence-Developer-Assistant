from pathlib import Path
from threading import Lock
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings


_client: Any | None = None
_client_lock = Lock()


class VectorStoreError(Exception):
    """Raised when persistent vector storage is unavailable."""


def get_client() -> chromadb.PersistentClient:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                try:
                    storage_path = Path(settings.VECTOR_DB_DIR).expanduser()
                    storage_path.mkdir(parents=True, exist_ok=True)
                    _client = chromadb.PersistentClient(
                        path=str(storage_path),
                        settings=ChromaSettings(anonymized_telemetry=False),
                    )
                except Exception as exc:
                    raise VectorStoreError(
                        "Unable to open persistent vector storage"
                    ) from exc
    return _client


def get_collection():
    try:
        return get_client().get_or_create_collection(
            name=settings.VECTOR_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    except VectorStoreError:
        raise
    except Exception as exc:
        raise VectorStoreError("Unable to access the vector collection") from exc
