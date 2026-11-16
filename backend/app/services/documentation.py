import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.core.config import settings
from app.services.llm_service import (
    LLMConfigurationError,
    LLMProviderError,
    generate_documentation_response,
)
from app.services.repository_cloning import (
    RepositoryCloneError,
    repository_storage_path,
)


DocumentationType = Literal["readme", "module", "function", "class", "api"]
MAX_DOCUMENTATION_CONTEXT_CHARS = 20_000
MAX_DOCUMENTATION_SYMBOLS = 100
API_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
API_DECORATORS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "delete": "DELETE",
    "options": "OPTIONS",
    "head": "HEAD",
    "api_route": None,
}


class DocumentationRepositoryError(Exception):
    """Raised when the cloned repository cannot be accessed safely."""


class DocumentationPathError(Exception):
    """Raised when a requested source path is unsafe or unavailable."""


class DocumentationSourceFileNotFound(DocumentationPathError):
    """Raised when a source path is not present in the parsed repository."""


class DocumentationSourceFileUnavailable(DocumentationPathError):
    """Raised when a parsed source file cannot be read safely."""


@dataclass(frozen=True)
class DocumentationResult:
    documentation_type: DocumentationType
    file_path: str | None
    documentation: str
    sufficient_information: bool
    notice: str | None
    limitations: list[str]
    source_file_count: int
    model: str | None


def _relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
        return None
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return None
    parts = normalized.split("/")
    if any(part == ".." for part in parts):
        return None
    safe_parts = [part for part in parts if part not in {"", "."}]
    return "/".join(safe_parts) or None


def _parsed_files(parse_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    languages = parse_summary.get("languages")
    if isinstance(languages, dict):
        for language, language_data in languages.items():
            if not isinstance(language, str) or not isinstance(language_data, dict):
                continue
            language_files = language_data.get("files")
            if not isinstance(language_files, list):
                continue
            for entry in language_files:
                if not isinstance(entry, dict):
                    continue
                relative_path = _relative_path(entry.get("path"))
                if relative_path is None or relative_path in files:
                    continue
                files[relative_path] = {
                    **entry,
                    "path": relative_path,
                    "language": language,
                }

    legacy_files = parse_summary.get("files")
    if isinstance(legacy_files, list):
        for entry in legacy_files:
            if not isinstance(entry, dict):
                continue
            relative_path = _relative_path(entry.get("path"))
            if relative_path is not None and relative_path not in files:
                files[relative_path] = {
                    **entry,
                    "path": relative_path,
                    "language": "Python",
                }
    return files


def _select_files(
    files: dict[str, dict[str, Any]],
    requested_path: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    if requested_path is None:
        return list(files.values()), None

    safe_path = _relative_path(requested_path)
    if safe_path is None:
        raise DocumentationPathError("file_path must be a safe repository-relative path")
    entry = files.get(safe_path)
    if entry is None:
        raise DocumentationSourceFileNotFound(
            "file_path does not match a file in the completed parse analysis"
        )
    return [entry], safe_path


def _read_source(root: Path, relative_path: str) -> str:
    root = root.resolve()
    candidate = root.joinpath(*relative_path.split("/"))
    current = root
    for part in relative_path.split("/"):
        current = current / part
        if current.is_symlink():
            raise DocumentationPathError("Symbolic-link source paths are not supported")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            raise DocumentationSourceFileNotFound("Requested source file is unavailable")
        if resolved.stat().st_size > settings.MAX_SCAN_FILE_SIZE_BYTES:
            raise DocumentationSourceFileUnavailable(
                "Requested source file exceeds the configured size limit"
            )
        content = resolved.read_bytes()
    except (DocumentationSourceFileNotFound, DocumentationSourceFileUnavailable):
        raise
    except FileNotFoundError:
        raise DocumentationSourceFileNotFound(
            "Requested source file is unavailable"
        ) from None
    except (OSError, RuntimeError, ValueError):
        raise DocumentationSourceFileUnavailable(
            "Requested source file is unavailable"
        ) from None
    if len(content) > settings.MAX_SCAN_FILE_SIZE_BYTES or b"\x00" in content:
        raise DocumentationSourceFileUnavailable(
            "Requested source file is not readable source text"
        )
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        raise DocumentationSourceFileUnavailable(
            "Requested source file is not readable UTF-8 text"
        ) from None


def load_parsed_source_file(
    *,
    user_id: int,
    repository_id: int,
    parse_summary: dict[str, Any],
    file_path: str,
) -> tuple[dict[str, Any], str]:
    try:
        root = repository_storage_path(user_id, repository_id)
    except RepositoryCloneError as exc:
        raise DocumentationRepositoryError(
            "Unable to determine repository storage"
        ) from exc
    expected_root = (
        settings.CODEMIND_STORAGE_DIR.expanduser().resolve()
        / str(user_id)
        / str(repository_id)
    )
    if expected_root.parent.is_symlink() or expected_root.is_symlink():
        raise DocumentationRepositoryError("Repository storage path is unsafe")
    git_directory = root / ".git"
    if (
        not root.is_dir()
        or git_directory.is_symlink()
        or not git_directory.is_dir()
    ):
        raise DocumentationRepositoryError("Repository has not been cloned successfully")

    files = _parsed_files(parse_summary)
    selected_files, normalized_path = _select_files(files, file_path)
    entry = selected_files[0]
    if entry.get("status") != "parsed":
        raise DocumentationSourceFileUnavailable(
            "Requested source file was not successfully parsed"
        )
    if normalized_path is None:
        raise DocumentationPathError("file_path must be a repository-relative path")
    return entry, _read_source(root, normalized_path)


def _bounded_context(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= MAX_DOCUMENTATION_CONTEXT_CHARS:
        return serialized
    return (
        serialized[:MAX_DOCUMENTATION_CONTEXT_CHARS]
        + "\n[Context truncated at the configured documentation limit.]"
    )


def _insufficient(
    documentation_type: DocumentationType,
    file_path: str | None,
    notice: str,
    source_file_count: int = 0,
) -> DocumentationResult:
    return DocumentationResult(
        documentation_type=documentation_type,
        file_path=file_path,
        documentation=notice,
        sufficient_information=False,
        notice=notice,
        limitations=[notice],
        source_file_count=source_file_count,
        model=None,
    )


def _symbol_entries(
    file_entry: dict[str, Any],
    key: str,
) -> list[dict[str, Any]]:
    values = file_entry.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _source_excerpt(
    source: str,
    entry: dict[str, Any],
    max_chars: int = 6000,
) -> str:
    start = entry.get("start_line")
    end = entry.get("end_line")
    if type(start) is not int or type(end) is not int or start < 1 or end < start:
        return ""
    lines = source.splitlines(keepends=True)
    excerpt = "".join(lines[start - 1 : end])
    return excerpt[:max_chars]


def _route_path(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant):
        value = call.args[0].value
        if isinstance(value, str):
            return value
    for keyword in call.keywords:
        if keyword.arg in {"path", "route"} and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            if isinstance(value, str):
                return value
    return None


def _route_methods(call: ast.Call, decorator_name: str) -> list[str]:
    if decorator_name in API_DECORATORS and API_DECORATORS[decorator_name]:
        return [API_DECORATORS[decorator_name] or ""]
    for keyword in call.keywords:
        if keyword.arg != "methods" or not isinstance(keyword.value, (ast.List, ast.Tuple)):
            continue
        methods = []
        for item in keyword.value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                method = item.value.upper()
                if method in API_METHODS:
                    methods.append(method)
        return sorted(set(methods))
    return []


def _api_routes(
    source: str,
    relative_path: str,
    file_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    if file_entry.get("language") != "Python":
        return []
    parsed_functions = {
        function.get("name")
        for function in _symbol_entries(file_entry, "functions")
        if isinstance(function.get("name"), str)
    }
    if not parsed_functions:
        return []

    try:
        tree = ast.parse(source, filename=relative_path)
    except (SyntaxError, ValueError):
        return []

    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in parsed_functions:
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            decorator_name = decorator.func.attr.lower()
            if decorator_name not in API_DECORATORS:
                continue
            path = _route_path(decorator)
            methods = _route_methods(decorator, decorator_name)
            if path is None or not methods:
                continue
            routes.append(
                {
                    "file_path": relative_path,
                    "method": methods,
                    "path_as_declared": path,
                    "handler": node.name,
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "docstring": ast.get_docstring(node, clean=True),
                    "source": _source_excerpt(
                        source,
                        {
                            "start_line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno),
                        },
                    ),
                }
            )
    return routes


def _build_context(
    documentation_type: DocumentationType,
    files: list[dict[str, Any]],
    root: Path,
    file_path: str | None,
    repository_name: str,
    default_branch: str,
    parse_summary: dict[str, Any],
) -> tuple[str | None, int, str | None]:
    parsed_files = [entry for entry in files if entry.get("status") == "parsed"]
    if documentation_type == "readme":
        if not parsed_files:
            return None, 0, "Insufficient source information: no successfully parsed files are available."
        language_counts = {
            language: data.get("total_files", 0)
            for language, data in parse_summary.get("languages", {}).items()
            if isinstance(language, str) and isinstance(data, dict)
        } if isinstance(parse_summary.get("languages"), dict) else {}
        file_data = []
        for entry in parsed_files:
            file_data.append(
                {
                    "path": entry["path"],
                    "language": entry.get("language", "unknown"),
                    "classes": [
                        item.get("name")
                        for item in _symbol_entries(entry, "classes")
                        if isinstance(item.get("name"), str)
                    ][:20],
                    "interfaces": [
                        item.get("name")
                        for item in _symbol_entries(entry, "interfaces")
                        if isinstance(item.get("name"), str)
                    ][:20],
                    "functions": [
                        item.get("name")
                        for item in _symbol_entries(entry, "functions")
                        if isinstance(item.get("name"), str)
                    ][:30],
                    "imports": [
                        item.get("module")
                        for item in _symbol_entries(entry, "imports")
                        if isinstance(item.get("module"), str)
                    ][:20],
                }
            )
        return (
            _bounded_context(
                {
                    "repository_name": repository_name,
                    "default_branch": default_branch,
                    "language_file_counts": language_counts,
                    "parsed_files": file_data,
                    "parse_file_count": len(parsed_files),
                    "source_note": (
                        "Only parsed paths, symbols, and imports are supplied; "
                        "do not infer build, install, or runtime instructions."
                    ),
                }
            ),
            len(parsed_files),
            None,
        )

    if documentation_type == "module":
        if not files or files[0].get("status") != "parsed":
            return None, 0, "Insufficient source information: the requested file was not successfully parsed."
        source = _read_source(root, files[0]["path"])
        if not source.strip():
            return None, 0, "Insufficient source information: the requested file is empty."
        context = {
            "file_path": files[0]["path"],
            "language": files[0].get("language", "unknown"),
            "parsed_symbols": {
                kind: _symbol_entries(files[0], kind)
                for kind in ("classes", "interfaces", "functions", "imports")
            },
            "source": source,
        }
        return _bounded_context(context), 1, None

    if documentation_type in {"function", "class"}:
        key = "functions" if documentation_type == "function" else "classes"
        context_entries = []
        used_paths = set()
        for file_entry in parsed_files:
            if file_path is not None and file_entry["path"] != file_path:
                continue
            symbols = _symbol_entries(file_entry, key)
            if not symbols:
                continue
            source = _read_source(root, file_entry["path"])
            for symbol in symbols:
                excerpt = _source_excerpt(source, symbol)
                if not excerpt.strip():
                    continue
                context_entries.append(
                    {
                        "file_path": file_entry["path"],
                        "language": file_entry.get("language", "unknown"),
                        "symbol": symbol,
                        "source": excerpt,
                    }
                )
                used_paths.add(file_entry["path"])
                if len(context_entries) >= MAX_DOCUMENTATION_SYMBOLS:
                    break
            if len(context_entries) >= MAX_DOCUMENTATION_SYMBOLS:
                break
        if not context_entries:
            return None, 0, f"Insufficient source information: no parsed {documentation_type} definitions were found."
        return _bounded_context({"definitions": context_entries}), len(used_paths), None

    routes = []
    used_paths = set()
    for file_entry in parsed_files:
        if file_path is not None and file_entry["path"] != file_path:
            continue
        if file_entry.get("language") != "Python":
            continue
        source = _read_source(root, file_entry["path"])
        file_routes = _api_routes(source, file_entry["path"], file_entry)
        routes.extend(file_routes)
        if file_routes:
            used_paths.add(file_entry["path"])
        if len(routes) >= MAX_DOCUMENTATION_SYMBOLS:
            routes = routes[:MAX_DOCUMENTATION_SYMBOLS]
            break
    if not routes:
        return None, 0, (
            "Insufficient source information: no statically recognizable API route "
            "declarations were found in the parsed Python files."
        )
    return (
        _bounded_context(
            {
                "routes": routes,
                "route_path_note": (
                    "Paths are literal decorator values; mounted router prefixes "
                    "and dynamically constructed paths are not resolved."
                ),
            }
        ),
        len(used_paths),
        None,
    )


def generate_repository_documentation(
    *,
    user_id: int,
    repository_id: int,
    repository_name: str,
    default_branch: str,
    parse_summary: dict[str, Any],
    documentation_type: DocumentationType,
    file_path: str | None = None,
) -> DocumentationResult:
    try:
        root = repository_storage_path(user_id, repository_id)
    except RepositoryCloneError as exc:
        raise DocumentationRepositoryError("Unable to determine repository storage") from exc
    expected_root = (
        settings.CODEMIND_STORAGE_DIR.expanduser().resolve()
        / str(user_id)
        / str(repository_id)
    )
    if expected_root.parent.is_symlink() or expected_root.is_symlink():
        raise DocumentationRepositoryError("Repository storage path is unsafe")
    git_directory = root / ".git"
    if (
        not root.is_dir()
        or git_directory.is_symlink()
        or not git_directory.is_dir()
    ):
        raise DocumentationRepositoryError("Repository has not been cloned successfully")

    parsed_files = _parsed_files(parse_summary)
    selected_files, normalized_path = _select_files(parsed_files, file_path)
    context, source_file_count, insufficient_notice = _build_context(
        documentation_type,
        selected_files,
        root,
        normalized_path,
        repository_name,
        default_branch,
        parse_summary,
    )
    if insufficient_notice is not None or context is None:
        return _insufficient(
            documentation_type,
            normalized_path,
            insufficient_notice
            or "Insufficient source information is available for this documentation request.",
            source_file_count,
        )

    generated = generate_documentation_response(
        documentation_type=documentation_type,
        context=context,
    )
    documentation = generated["documentation"].strip()
    sufficient_information = generated["sufficient_information"]
    limitations = list(generated["limitations"])
    if documentation_type == "api":
        limitations.append(
            "Mounted router prefixes and dynamically constructed route paths are not resolved."
        )
    notice = None
    if not sufficient_information:
        notice = (
            "The available source information was not sufficient to document every "
            "requested detail."
        )
        if not limitations:
            limitations = [notice]

    return DocumentationResult(
        documentation_type=documentation_type,
        file_path=normalized_path,
        documentation=documentation,
        sufficient_information=sufficient_information,
        notice=notice,
        limitations=limitations,
        source_file_count=source_file_count,
        model=settings.GROQ_MODEL,
    )


__all__ = [
    "DocumentationPathError",
    "DocumentationRepositoryError",
    "DocumentationResult",
    "DocumentationType",
    "LLMConfigurationError",
    "LLMProviderError",
    "generate_repository_documentation",
]
