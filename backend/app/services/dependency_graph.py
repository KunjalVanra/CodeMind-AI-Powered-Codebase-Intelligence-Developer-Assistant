import posixpath
from pathlib import PurePosixPath

from app.services.tree_sitter_parser import TREE_SITTER_LANGUAGES


SUPPORTED_ANALYSIS_LANGUAGES = {"Python"} | {
    language for language, _ in TREE_SITTER_LANGUAGES.values()
}
_MODULE_EXTENSIONS = {
    "Python": (".py",),
    "JavaScript": (".js", ".jsx", ".mjs", ".cjs"),
    "TypeScript": (".ts", ".tsx", ".js", ".jsx"),
    "Java": (".java",),
    "C": (".c", ".h"),
    "C++": (".cc", ".cpp", ".cxx", ".hpp"),
    "C#": (".cs",),
    "Go": (".go",),
    "Rust": (".rs",),
    "PHP": (".php",),
    "Ruby": (".rb",),
}


def _safe_file_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or normalized in {"", "."}:
        return None
    return path.as_posix()


def _module_aliases(file_path: str) -> set[str]:
    path = PurePosixPath(file_path)
    stem = path.with_suffix("").as_posix()
    aliases = {stem, stem.replace("/", "."), stem.replace("/", "::")}
    if path.name == "__init__.py":
        package = path.parent.as_posix()
        aliases.update({package, package.replace("/", "."), package.replace("/", "::")})
    return aliases


def _lookup_module(
    module: str,
    file_paths: set[str],
    aliases: dict[str, set[str]],
    *,
    suffix_match: bool = False,
) -> str | None:
    candidates = aliases.get(module, set())
    if not candidates and suffix_match:
        candidates = {
            path
            for alias, paths in aliases.items()
            if alias.endswith(f".{module}") or alias.endswith(f"::{module}")
            for path in paths
        }
    if len(candidates) == 1:
        return next(iter(candidates))

    module_path = module.replace(".", "/").replace("::", "/")
    if module_path in file_paths:
        return module_path
    return None


def _resolve_path_import(
    source: str,
    module: str,
    language: str,
    file_paths: set[str],
) -> str | None:
    if module.startswith("/"):
        candidate = posixpath.normpath(module.lstrip("/"))
    else:
        candidate = posixpath.normpath(
            posixpath.join(posixpath.dirname(source), module)
        )
    if candidate == ".." or candidate.startswith("../"):
        return None
    if candidate in file_paths:
        return candidate

    suffix = PurePosixPath(candidate).suffix
    if suffix:
        return None
    extensions = _MODULE_EXTENSIONS.get(language, ())
    for extension in extensions:
        path = candidate + extension
        if path in file_paths:
            return path
    if language == "Rust":
        path = posixpath.join(candidate, "mod.rs")
        if path in file_paths:
            return path
    for extension in extensions:
        path = posixpath.join(candidate, f"index{extension}")
        if path in file_paths:
            return path
        path = posixpath.join(candidate, "__init__" + extension)
        if path in file_paths:
            return path
    return None


def _python_import_targets(
    source: str,
    import_info: dict,
    aliases: dict[str, set[str]],
    file_paths: set[str],
) -> tuple[list[str], bool]:
    module = import_info.get("module")
    if not isinstance(module, str) or not module:
        return [], True

    relative = bool(import_info.get("relative")) or module.startswith(".")
    if relative:
        level = import_info.get("level")
        if not isinstance(level, int) or level < 1:
            level = len(module) - len(module.lstrip("."))
        parts = list(PurePosixPath(source).parent.parts)
        ascend = max(level - 1, 0)
        if ascend:
            parts = parts[: max(0, len(parts) - ascend)]
        module_parts = [part for part in module.lstrip(".").split(".") if part]
        base_parts = parts + module_parts
        local = True
    else:
        base_parts = [part for part in module.split(".") if part]
        local = False

    names = import_info.get("names")
    imported_names = names if isinstance(names, list) else []
    targets: set[str] = set()
    for name in imported_names:
        if not isinstance(name, str) or not name or name == "*":
            continue
        target = _lookup_module(
            ".".join(base_parts + [name]),
            file_paths,
            aliases,
        )
        if target:
            targets.add(target)

    if not targets and base_parts:
        target = _lookup_module(
            ".".join(base_parts),
            file_paths,
            aliases,
        )
        if target:
            targets.add(target)

    if targets:
        return sorted(targets), True
    if relative:
        return [], True
    return [], local


def _resolve_import(
    source: str,
    language: str,
    import_info: dict,
    file_paths: set[str],
    aliases: dict[str, set[str]],
) -> tuple[list[str], str, str]:
    module = import_info.get("module")
    if not isinstance(module, str) or not module.strip():
        return [], "unresolved", ""
    module = module.strip()

    if language == "Python":
        targets, local = _python_import_targets(
            source, import_info, aliases, file_paths
        )
        if targets:
            return targets, "internal", module
        return [], "unresolved" if local else "external", module

    if language == "Rust" and module.startswith("crate::"):
        rust_path = module.removeprefix("crate::").replace("::", "/")
        for root_source in ("src/lib.rs", "src/main.rs", "lib.rs", "main.rs"):
            target = _resolve_path_import(
                root_source, rust_path, language, file_paths
            )
            if target:
                return [target], "internal", module
        return [], "unresolved", module
    if language == "Rust" and module.startswith("super::"):
        rust_path = "../" + module.removeprefix("super::").replace("::", "/")
        target = _resolve_path_import(source, rust_path, language, file_paths)
        if target:
            return [target], "internal", module
        return [], "unresolved", module
    if language == "Rust" and module.startswith("self::"):
        rust_path = module.removeprefix("self::").replace("::", "/")
        target = _resolve_path_import(source, rust_path, language, file_paths)
        if target:
            return [target], "internal", module
        return [], "unresolved", module

    local = (
        module.startswith(("./", "../", "/"))
        or (language == "Ruby" and module.startswith("."))
    )
    if local:
        target = _resolve_path_import(source, module, language, file_paths)
        if target:
            return [target], "internal", module
        return [], "unresolved", module

    module_alias = module.lstrip("\\").replace("\\", ".")
    target = _lookup_module(
        module_alias,
        file_paths,
        aliases,
        suffix_match=language == "Java",
    )
    if target:
        return [target], "internal", module

    return [], "external", module


def build_dependency_graph(parse_summary: dict) -> dict:
    """Build a file dependency graph from a persisted repository parse summary."""
    nodes_by_path: dict[str, dict] = {}
    imports_by_path: dict[str, list[tuple[str, dict]]] = {}
    languages = parse_summary.get("languages")
    if not isinstance(languages, dict):
        languages = {}

    for language, language_data in languages.items():
        if not isinstance(language, str) or not isinstance(language_data, dict):
            continue
        files = language_data.get("files")
        if not isinstance(files, list):
            continue
        for file_data in files:
            if not isinstance(file_data, dict):
                continue
            file_path = _safe_file_path(file_data.get("path"))
            if file_path is None:
                continue
            nodes_by_path.setdefault(
                file_path,
                {
                    "id": file_path,
                    "file_path": file_path,
                    "language": language,
                    "status": file_data.get("status", "parsed"),
                },
            )
            imports = file_data.get("imports")
            if isinstance(imports, list):
                imports_by_path.setdefault(file_path, []).extend(
                    (language, item)
                    for item in imports
                    if isinstance(item, dict)
                )

    file_paths = set(nodes_by_path)
    aliases: dict[str, set[str]] = {}
    for file_path in file_paths:
        for alias in _module_aliases(file_path):
            aliases.setdefault(alias, set()).add(file_path)

    edges_by_key: dict[tuple[str, str, str], dict] = {}
    for source in sorted(file_paths):
        for language, import_info in imports_by_path.get(source, []):
            targets, dependency_type, dependency = _resolve_import(
                source, language, import_info, file_paths, aliases
            )
            line = import_info.get("start_line")
            if not isinstance(line, int):
                line = None
            edge_targets: list[str | None] = targets or [None]
            for target in edge_targets:
                key = (source, target or dependency, dependency_type)
                edges_by_key.setdefault(
                    key,
                    {
                        "source": source,
                        "target": target,
                        "dependency": dependency,
                        "dependency_type": dependency_type,
                        "relationship": "import",
                        "line": line,
                    },
                )

    edges = sorted(
        edges_by_key.values(),
        key=lambda edge: (
            edge["source"],
            edge["dependency_type"],
            edge["target"] or "",
            edge["dependency"],
        ),
    )
    summary = {
        "total_files": len(nodes_by_path),
        "nodes": len(nodes_by_path),
        "edges": len(edges),
        "internal_dependencies": sum(
            edge["dependency_type"] == "internal" for edge in edges
        ),
        "external_dependencies": sum(
            edge["dependency_type"] == "external" for edge in edges
        ),
        "unresolved_imports": sum(
            edge["dependency_type"] == "unresolved" for edge in edges
        ),
    }
    return {
        "summary": summary,
        "nodes": [nodes_by_path[path] for path in sorted(nodes_by_path)],
        "edges": edges,
    }
