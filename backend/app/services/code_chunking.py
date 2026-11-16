import ast
import hashlib
import os
from pathlib import Path

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from app.core.config import settings
from app.services.repository_cloning import (
    RepositoryCloneError,
    repository_storage_path,
)
from app.services.source_scanner import IGNORED_DIRECTORIES
from app.services.tree_sitter_parser import (
    STRUCTURE_NODES,
)


CHUNK_LANGUAGES = {
    ".py": ("Python", None),
    ".js": ("JavaScript", "javascript"),
    ".jsx": ("JavaScript", "javascript"),
    ".ts": ("TypeScript", "typescript"),
    ".tsx": ("TypeScript", "tsx"),
}
CHUNK_NODE_TYPES = {
    "class": STRUCTURE_NODES["class"],
    "interface": STRUCTURE_NODES["interface"],
    "function": STRUCTURE_NODES["function"]
    | {
        "method_signature",
        "abstract_method_signature",
        "arrow_function",
        "function_expression",
        "generator_function",
    },
}


class CodeChunkingError(Exception):
    """Raised when a repository cannot be chunked within configured limits."""


def _is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _add_node(
    nodes: list[dict],
    kind: str,
    name: str | None,
    start_line: int,
    end_line: int,
    parent_index: int | None,
) -> int:
    if kind == "function" and parent_index is not None:
        parent_kind = nodes[parent_index]["kind"]
        if parent_kind in {"class", "interface"}:
            kind = "method"
    nodes.append(
        {
            "kind": kind,
            "name": name,
            "start_line": start_line,
            "end_line": end_line,
            "parent_index": parent_index,
        }
    )
    return len(nodes) - 1


def _python_nodes(source: str) -> tuple[list[dict], list[tuple[int, int]]]:
    tree = ast.parse(source)
    nodes: list[dict] = []

    def visit(node: ast.AST, parent_index: int | None = None) -> None:
        semantic_index = parent_index
        if isinstance(node, ast.ClassDef):
            start_line = min(
                [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
            )
            semantic_index = _add_node(
                nodes,
                "class",
                node.name,
                start_line,
                getattr(node, "end_lineno", node.lineno),
                parent_index,
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start_line = min(
                [node.lineno] + [decorator.lineno for decorator in node.decorator_list]
            )
            semantic_index = _add_node(
                nodes,
                "function",
                node.name,
                start_line,
                getattr(node, "end_lineno", node.lineno),
                parent_index,
            )
        for child in ast.iter_child_nodes(node):
            visit(child, semantic_index)

    visit(tree)
    roots = [
        (node["start_line"], node["end_line"])
        for node in nodes
        if node["parent_index"] is None
    ]
    return nodes, roots


def _tree_sitter_nodes(
    source: bytes,
    grammar: str,
) -> tuple[list[dict], list[tuple[int, int]]]:
    tree = get_parser(grammar).parse(source)
    if tree.root_node.has_error:
        raise SyntaxError("Source file has syntax errors")

    nodes: list[dict] = []

    def visit(
        node: Node,
        parent_index: int | None = None,
        inferred_name: str | None = None,
    ) -> None:
        node_kind = next(
            (kind for kind, node_types in CHUNK_NODE_TYPES.items()
             if node.type in node_types),
            None,
        )
        semantic_index = parent_index
        if node_kind is not None:
            name_node = node.child_by_field_name("name")
            name = (
                source[name_node.start_byte:name_node.end_byte].decode(
                    "utf-8", errors="replace"
                )
                if name_node is not None
                else inferred_name
            )
            semantic_index = _add_node(
                nodes,
                node_kind,
                name,
                node.start_point[0] + 1,
                node.end_point[0] + 1,
                parent_index,
            )
        variable_name = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        for child in node.named_children:
            child_name = inferred_name if node_kind is None else None
            if node.type in {"variable_declarator", "assignment_expression"}:
                if child == value_node and variable_name is not None:
                    child_name = source[
                        variable_name.start_byte:variable_name.end_byte
                    ].decode("utf-8", errors="replace")
            visit(child, semantic_index, child_name)

    visit(tree.root_node)
    root_nodes = [
        (node["start_line"], node["end_line"])
        for node in nodes
        if node["parent_index"] is None
    ]
    return nodes, root_nodes


def _safe_file_list(root: Path) -> list[tuple[Path, str, str, str | None]]:
    files = []
    seen = 0
    for current_root, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        current_path = Path(current_root)
        if len(current_path.relative_to(root).parts) >= settings.MAX_SCAN_DIRECTORY_DEPTH:
            directory_names[:] = []
            continue
        directory_names[:] = [
            name
            for name in directory_names
            if name not in IGNORED_DIRECTORIES
            and not (current_path / name).is_symlink()
            and _is_inside(root, current_path / name)
        ]
        for file_name in file_names:
            path = current_path / file_name
            if path.is_symlink() or not _is_inside(root, path):
                continue
            seen += 1
            if seen > settings.MAX_SCAN_FILE_COUNT:
                raise CodeChunkingError("Repository contains too many files to chunk")
            language_info = CHUNK_LANGUAGES.get(path.suffix.lower())
            if language_info is None:
                continue
            language, grammar = language_info
            files.append((path, path.relative_to(root).as_posix(), language, grammar))
    return files


def _line_ranges_without_children(
    start_line: int,
    end_line: int,
    child_ranges: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    segments = []
    cursor = start_line
    for child_start, child_end in sorted(child_ranges):
        if child_start > cursor:
            segments.append((cursor, child_start - 1))
        cursor = max(cursor, child_end + 1)
    if cursor <= end_line:
        segments.append((cursor, end_line))
    return segments


def _split_source(
    content: str,
    start_line: int,
    maximum_chars: int,
) -> list[tuple[str, int, int]]:
    maximum_chars = max(1, maximum_chars)
    chunks = []
    offset = 0
    while offset < len(content):
        end = min(offset + maximum_chars, len(content))
        if end < len(content):
            newline = content.rfind("\n", offset, end)
            if newline > offset:
                end = newline + 1
        part = content[offset:end]
        start = start_line + content.count("\n", 0, offset)
        end_line = start + part.count("\n")
        if part.endswith("\n"):
            end_line = max(start, end_line - 1)
        chunks.append((part, start, end_line))
        offset = end
    return chunks


def _make_chunks_for_file(
    path: Path,
    relative_path: str,
    language: str,
    grammar: str | None,
    max_chunks: int,
) -> tuple[list[dict], str]:
    try:
        if path.stat().st_size > settings.MAX_SCAN_FILE_SIZE_BYTES:
            raise OSError("file exceeds configured size limit")
        raw_source = path.read_bytes()
        if b"\x00" in raw_source:
            raise OSError("binary file")
        source = raw_source.decode("utf-8")
        if grammar is None:
            nodes, root_ranges = _python_nodes(source)
        else:
            nodes, root_ranges = _tree_sitter_nodes(raw_source, grammar)
    except (OSError, UnicodeError):
        return [], "unreadable"
    except SyntaxError:
        return [], "syntax_error"
    except (ValueError, RuntimeError):
        return [], "parser_error"

    lines = source.splitlines(keepends=True)
    if source and not lines:
        lines = [source]
    chunks = []
    roots_by_parent: dict[int | None, list[dict]] = {}
    for index, node in enumerate(nodes):
        roots_by_parent.setdefault(node["parent_index"], []).append(
            {**node, "index": index}
        )

    segments: list[tuple[str, str | None, str | None, int, int, str]] = []
    for index, node in enumerate(nodes):
        children = roots_by_parent.get(index, [])
        child_ranges = [
            (child["start_line"], child["end_line"])
            for child in children
        ]
        node_segments = _line_ranges_without_children(
            node["start_line"], node["end_line"], child_ranges
        )
        if not node_segments and children:
            node_segments = [(node["start_line"], node["end_line"])]
        for segment_start, segment_end in node_segments:
            content = "".join(lines[segment_start - 1:segment_end])
            if content.strip():
                parent_name = (
                    nodes[node["parent_index"]]["name"]
                    if node["parent_index"] is not None
                    else None
                )
                segments.append(
                    (
                        node["kind"],
                        node["name"],
                        parent_name,
                        segment_start,
                        segment_end,
                        content,
                    )
                )

    for segment_start, segment_end in _line_ranges_without_children(
        1, len(lines), root_ranges
    ):
        content = "".join(lines[segment_start - 1:segment_end])
        if content.strip():
            segments.append(
                ("module", None, None, segment_start, segment_end, content)
            )

    maximum_chars = settings.MAX_CODE_CHUNK_CHARS
    for chunk_type, name, parent_type, start, end, content in sorted(
        segments, key=lambda item: (item[3], item[4], item[0])
    ):
        for part_index, (part, part_start, part_end) in enumerate(
            _split_source(content, start, maximum_chars)
        ):
            identity = "\0".join(
                (
                    relative_path,
                    language,
                    chunk_type,
                    name or "",
                    str(part_start),
                    str(part_index),
                    part,
                )
            )
            if len(chunks) >= max_chunks:
                raise CodeChunkingError(
                    "Repository exceeds the configured chunk limit"
                )
            chunks.append(
                {
                    "chunk_id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                    "file_path": relative_path,
                    "language": language,
                    "chunk_type": chunk_type,
                    "name": name,
                    "parent_type": parent_type,
                    "start_line": part_start,
                    "end_line": part_end,
                    "source_content": part,
                }
            )
    return chunks, "chunked"


def chunk_repository(user_id: int, repository_id: int) -> dict:
    try:
        root = repository_storage_path(user_id, repository_id)
    except RepositoryCloneError as exc:
        raise CodeChunkingError("Unable to determine repository storage") from exc
    if not root.is_dir() or not (root / ".git").is_dir():
        raise CodeChunkingError("Repository has not been cloned successfully")

    chunks = []
    statuses: dict[str, int] = {}
    files = _safe_file_list(root)
    for path, relative_path, language, grammar in files:
        file_chunks, file_status = _make_chunks_for_file(
            path,
            relative_path,
            language,
            grammar,
            settings.MAX_CODE_CHUNKS_PER_REPOSITORY - len(chunks),
        )
        statuses[file_status] = statuses.get(file_status, 0) + 1
        chunks.extend(file_chunks)

    return {
        "total_files": len(files),
        "total_chunks": len(chunks),
        "file_statuses": statuses,
        "chunks": chunks,
    }
