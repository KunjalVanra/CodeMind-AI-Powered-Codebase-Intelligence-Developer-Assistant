import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.llm_service import (
    LLMConfigurationError,
    LLMProviderError,
    generate_rag_response,
)
from app.services.semantic_retrieval import (
    SemanticRetrievalError,
    retrieve_code,
)


class RAGRetrievalError(Exception):
    """Raised when repository context cannot be retrieved."""


@dataclass(frozen=True)
class RAGAnswer:
    answer: str
    citations: list[dict[str, Any]]
    model: str | None


_INSUFFICIENT_CONTEXT = (
    "I couldn't find enough relevant code in this repository to answer that question."
)
_CITATION_PATTERN = re.compile(r"\[(C\d+)\]")


def _relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        return None
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or ":" in parts[0] or any(part == ".." for part in parts):
        return None
    path = "/".join(part for part in parts if part not in {"", "."})
    return path or None


def _candidate_metadata(match: object) -> tuple[dict[str, Any], str] | None:
    if not isinstance(match, dict):
        return None
    metadata = match.get("metadata")
    source = match.get("source_content")
    if not isinstance(metadata, dict) or not isinstance(source, str) or not source.strip():
        return None

    file_path = _relative_path(metadata.get("file_path"))
    start_line = metadata.get("start_line")
    end_line = metadata.get("end_line")
    if (
        file_path is None
        or type(start_line) is not int
        or type(end_line) is not int
        or start_line < 1
        or end_line < start_line
    ):
        return None

    language = metadata.get("language")
    symbol = metadata.get("symbol")
    return (
        {
            "file_path": file_path,
            "language": language if isinstance(language, str) and language else "unknown",
            "symbol": symbol if isinstance(symbol, str) and symbol else None,
            "start_line": start_line,
            "end_line": end_line,
        },
        source,
    )


def _build_context(
    matches: list[dict],
    max_chars: int,
) -> tuple[str, dict[str, dict[str, Any]]]:
    if max_chars <= 0:
        return "", {}

    entries: list[dict[str, Any]] = []
    citations: dict[str, dict[str, Any]] = {}

    def serialize(candidate_entries: list[dict[str, Any]]) -> str:
        return json.dumps(
            {"chunks": candidate_entries},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    for match in matches:
        candidate = _candidate_metadata(match)
        if candidate is None:
            continue
        metadata, source = candidate
        reference_id = f"C{len(entries) + 1}"
        entry = {
            "reference_id": reference_id,
            **metadata,
            "source": source,
            "source_truncated": False,
        }
        proposed = entries + [entry]
        if len(serialize(proposed)) > max_chars:
            low, high = 0, len(source)
            best_entry = None
            while low <= high:
                middle = (low + high) // 2
                snippet = source[:middle]
                truncated_entry = {
                    "reference_id": reference_id,
                    **metadata,
                    "source": snippet,
                    "source_truncated": True,
                }
                if len(serialize(entries + [truncated_entry])) <= max_chars:
                    best_entry = truncated_entry
                    low = middle + 1
                else:
                    high = middle - 1
            if best_entry is None or not best_entry["source"].strip():
                continue
            entry = best_entry
            if entry["source_truncated"]:
                represented_lines = entry["source"].count("\n") + 1
                entry["end_line"] = min(
                    metadata["end_line"],
                    metadata["start_line"] + represented_lines - 1,
                )
        entries.append(entry)
        citations[reference_id] = {
            "reference_id": reference_id,
            "file_path": metadata["file_path"],
            "language": metadata["language"],
            "symbol": metadata["symbol"],
            "start_line": metadata["start_line"],
            "end_line": entry["end_line"],
        }

    return serialize(entries), citations


def answer_repository_question(
    question: str,
    user_id: int,
    repository_id: int,
    top_k: int = 5,
) -> RAGAnswer:
    if not isinstance(question, str) or not question.strip() or len(question.strip()) > 2000:
        raise ValueError("Question must contain 1 to 2000 characters")
    if user_id <= 0 or repository_id <= 0:
        raise ValueError("Valid user and repository IDs are required")
    if not 1 <= top_k <= 10:
        raise ValueError("top_k must be between 1 and 10")

    try:
        matches = retrieve_code(
            question.strip(),
            user_id=user_id,
            repository_id=repository_id,
            limit=top_k,
        )
    except SemanticRetrievalError as exc:
        raise RAGRetrievalError("Repository context is unavailable") from exc

    context, citation_metadata = _build_context(
        matches,
        max_chars=settings.MAX_RAG_CONTEXT_CHARS,
    )
    if not citation_metadata:
        return RAGAnswer(
            answer=_INSUFFICIENT_CONTEXT,
            citations=[],
            model=None,
        )

    try:
        generated = generate_rag_response(
            question=question.strip(),
            context=context,
            reference_ids=list(citation_metadata),
        )
    except (LLMConfigurationError, LLMProviderError):
        raise

    valid_ids = []
    seen_ids = set()
    for reference_id in generated["citation_ids"]:
        if reference_id in citation_metadata and reference_id not in seen_ids:
            valid_ids.append(reference_id)
            seen_ids.add(reference_id)

    if not valid_ids:
        return RAGAnswer(
            answer=_INSUFFICIENT_CONTEXT,
            citations=[],
            model=settings.GROQ_MODEL,
        )

    answer = generated["answer"]
    answer = _CITATION_PATTERN.sub(
        lambda match: match.group(0) if match.group(1) in seen_ids else "",
        answer,
    )
    return RAGAnswer(
        answer=answer.strip(),
        citations=[citation_metadata[item] for item in valid_ids],
        model=settings.GROQ_MODEL,
    )
