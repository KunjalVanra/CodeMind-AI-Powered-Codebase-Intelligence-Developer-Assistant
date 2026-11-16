import os
import re
from pathlib import Path

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from app.core.config import settings
from app.services.repository_cloning import (
    RepositoryCloneError,
    repository_storage_path,
)
from app.services.source_scanner import IGNORED_DIRECTORIES


TREE_SITTER_LANGUAGES = {
    ".js": ("JavaScript", "javascript"),
    ".jsx": ("JavaScript", "javascript"),
    ".ts": ("TypeScript", "typescript"),
    ".tsx": ("TypeScript", "tsx"),
    ".java": ("Java", "java"),
    ".c": ("C", "c"),
    ".h": ("C", "c"),
    ".cc": ("C++", "cpp"),
    ".cpp": ("C++", "cpp"),
    ".cxx": ("C++", "cpp"),
    ".hpp": ("C++", "cpp"),
    ".cs": ("C#", "csharp"),
    ".go": ("Go", "go"),
    ".rs": ("Rust", "rust"),
    ".php": ("PHP", "php"),
    ".rb": ("Ruby", "ruby"),
}

STRUCTURE_NODES = {
    "class": {
        "class_declaration",
        "class_definition",
        "class_specifier",
        "class",
        "struct_item",
        "struct_specifier",
        "type_declaration",
    },
    "interface": {
        "interface_declaration",
        "interface_definition",
        "trait_item",
    },
    "function": {
        "function_declaration",
        "function_definition",
        "function_item",
        "function",
        "method_declaration",
        "method_definition",
        "method",
        "method_item",
        "constructor_declaration",
        "singleton_method",
    },
    "import": {
        "import_statement",
        "import_declaration",
        "using_directive",
        "use_declaration",
        "namespace_use_declaration",
        "preproc_include",
    },
}
NAME_NODE_TYPES = {
    "identifier",
    "type_identifier",
    "property_identifier",
    "field_identifier",
    "namespace_identifier",
    "constant",
    "simple_identifier",
}


class TreeSitterParseError(Exception):
    """Raised when a non-Python source repository cannot be parsed safely."""


def _is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _name(node: Node, source: bytes) -> str | None:
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node, source).strip() or None
    for child in node.named_children:
        if child.type in NAME_NODE_TYPES:
            return _node_text(child, source).strip() or None
    return None


def _import_module(statement: str) -> str | None:
    patterns = (
        r"\bimport\s+(?:[^'\"]*?\s+from\s+)?[\"']([^\"']+)[\"']",
        r"\bexport\b[\s\S]*?\bfrom\s+[\"']([^\"']+)[\"']",
        r"\bfrom\s+([A-Za-z0-9_.$:/-]+)",
        r"\bimport\s+([A-Za-z0-9_.$:/-]+)",
        r"\buse\s+([A-Za-z0-9_:$./-]+)",
        r"\brequire\s*\(\s*[\"']([^\"']+)",
        r"#include\s*[<\"]([^>\"]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, statement)
        if match:
            return match.group(1)
    return statement.strip().splitlines()[0][:200] or None


def _entry(
    node: Node,
    source: bytes,
    kind: str,
    parent_type: str | None,
) -> dict:
    entry = {
        "kind": kind,
        "name": _name(node, source),
        "parent_type": parent_type,
        "start_line": node.start_point[0] + 1,
        "end_line": node.end_point[0] + 1,
    }
    if kind == "import":
        entry["module"] = _import_module(_node_text(node, source))
    return entry


def _walk(node: Node, source: bytes, parent_type: str | None = None):
    kind = None
    if node.type in STRUCTURE_NODES["class"]:
        kind = "class"
    elif node.type in STRUCTURE_NODES["interface"]:
        kind = "interface"
    elif node.type in STRUCTURE_NODES["function"]:
        kind = "function"
    elif node.type in STRUCTURE_NODES["import"]:
        kind = "import"
    if kind is not None:
        yield _entry(node, source, kind, parent_type)
    next_parent = (
        _name(node, source)
        if kind in {"class", "interface"}
        else parent_type
    )
    for child in node.named_children:
        yield from _walk(child, source, next_parent)


def _parse_file(path: Path, relative_path: str, language: str, grammar: str) -> dict:
    try:
        if path.stat().st_size > settings.MAX_SCAN_FILE_SIZE_BYTES:
            raise OSError("file exceeds configured size limit")
        source = path.read_bytes()
        if b"\x00" in source:
            raise OSError("binary source file")
    except OSError as exc:
        return {"path": relative_path, "status": "unreadable"}

    try:
        tree = get_parser(grammar).parse(source)
    except (OSError, TypeError, ValueError, RuntimeError):
        return {"path": relative_path, "status": "parser_error"}

    classes = []
    interfaces = []
    functions = []
    imports = []
    for item in _walk(tree.root_node, source):
        if item["kind"] == "class":
            classes.append(item)
        elif item["kind"] == "interface":
            interfaces.append(item)
        elif item["kind"] == "function":
            functions.append(item)
        elif item["kind"] == "import":
            imports.append(item)
    return {
        "path": relative_path,
        "status": "syntax_error" if tree.root_node.has_error else "parsed",
        "classes": classes,
        "interfaces": interfaces,
        "functions": functions,
        "imports": imports,
        "language": language,
    }


def parse_tree_sitter_repository(user_id: int, repository_id: int) -> dict:
    try:
        root = repository_storage_path(user_id, repository_id)
    except RepositoryCloneError as exc:
        raise TreeSitterParseError("Unable to determine repository storage") from exc
    if not root.is_dir() or not (root / ".git").is_dir():
        raise TreeSitterParseError("Repository has not been cloned successfully")

    paths: list[tuple[Path, str, str, str]] = []
    for current_root, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        current_path = Path(current_root)
        if len(current_path.relative_to(root).parts) >= settings.MAX_SCAN_DIRECTORY_DEPTH:
            directory_names[:] = []
            continue
        directory_names[:] = [
            name for name in directory_names
            if name not in IGNORED_DIRECTORIES
            and not (current_path / name).is_symlink()
            and _is_inside(root, current_path / name)
        ]
        for file_name in file_names:
            if len(paths) >= settings.MAX_SCAN_FILE_COUNT:
                raise TreeSitterParseError("Repository contains too many files to parse")
            path = current_path / file_name
            language_info = TREE_SITTER_LANGUAGES.get(path.suffix.lower())
            if (
                language_info is None
                or path.is_symlink()
                or not _is_inside(root, path)
            ):
                continue
            language, grammar = language_info
            paths.append((path, path.relative_to(root).as_posix(), language, grammar))

    languages: dict[str, dict] = {}
    for path, relative_path, language, grammar in paths:
        parsed_file = _parse_file(path, relative_path, language, grammar)
        stats = languages.setdefault(
            language,
            {
                "total_files": 0,
                "successfully_parsed_files": 0,
                "syntax_error_files": 0,
                "unreadable_files": 0,
                "parser_error_files": 0,
                "total_classes": 0,
                "total_interfaces": 0,
                "total_functions": 0,
                "total_imports": 0,
                "files": [],
            },
        )
        stats["total_files"] += 1
        stats["files"].append(parsed_file)
        if parsed_file["status"] == "parsed":
            stats["successfully_parsed_files"] += 1
            stats["total_classes"] += len(parsed_file["classes"])
            stats["total_interfaces"] += len(parsed_file["interfaces"])
            stats["total_functions"] += len(parsed_file["functions"])
            stats["total_imports"] += len(parsed_file["imports"])
        elif parsed_file["status"] == "syntax_error":
            stats["syntax_error_files"] += 1
        else:
            stats["unreadable_files"] += parsed_file["status"] == "unreadable"
            stats["parser_error_files"] += parsed_file["status"] == "parser_error"
    return dict(sorted(languages.items()))
