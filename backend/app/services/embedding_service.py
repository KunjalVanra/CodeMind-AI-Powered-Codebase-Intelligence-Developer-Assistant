from threading import Lock

from app.core.config import settings


_model = None
_model_lock = Lock()


class EmbeddingError(Exception):
    """Raised when local embedding generation fails."""


def get_embedding_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                try:
                    from sentence_transformers import SentenceTransformer

                    _model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
                except Exception as exc:
                    raise EmbeddingError(
                        "Unable to load the configured local embedding model"
                    ) from exc
    return _model


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise EmbeddingError("Embedding input contains empty or invalid text")
    try:
        encoded = get_embedding_model().encode(
            texts,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        embeddings = encoded.tolist()
        if len(embeddings) != len(texts):
            raise ValueError("Embedding model returned an unexpected result count")
        return [[float(value) for value in embedding] for embedding in embeddings]
    except EmbeddingError:
        raise
    except Exception as exc:
        raise EmbeddingError("Unable to generate local embeddings") from exc
