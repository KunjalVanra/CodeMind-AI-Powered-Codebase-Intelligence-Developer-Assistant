import ast
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.services.code_chunking import CodeChunkingError, chunk_repository
from app.services.source_scanner import IGNORED_DIRECTORIES
from app.services.tree_sitter_parser import (
    TreeSitterParseError,
    parse_tree_sitter_repository,
)
from app.services.repository_cloning import (
    RepositoryCloneError,
    repository_storage_path,
)


class CodeParseError(Exception):
    """Raised when a cloned repository cannot be parsed safely."""


@dataclass(frozen=True)
class ParseResult:
    total_python_files: int
    successfully_parsed_files: int
    syntax_error_files: int
    unreadable_files: int
    total_classes: int
    total_functions: int
    total_imports: int
    files: list[dict]
    languages: dict[str, dict] = field(default_factory=dict)
    chunking: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "total_python_files": self.total_python_files,
            "successfully_parsed_files": self.successfully_parsed_files,
            "syntax_error_files": self.syntax_error_files,
            "unreadable_files": self.unreadable_files,
            "total_classes": self.total_classes,
            "total_functions": self.total_functions,
            "total_imports": self.total_imports,
            "files": self.files,
            "languages": self.languages,
            "chunking": self.chunking,
            "complexity_metric": "cyclomatic_complexity_v1",
        }


def _is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _docstring(node: ast.AST) -> str | None:
    value = ast.get_docstring(node, clean=True)
    return value if value else None


def _cyclomatic_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    class DecisionVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.decisions = 0

        def visit_FunctionDef(self, child: ast.FunctionDef) -> None:
            if child is node:
                for statement in child.body:
                    self.visit(statement)

        def visit_AsyncFunctionDef(self, child: ast.AsyncFunctionDef) -> None:
            if child is node:
                for statement in child.body:
                    self.visit(statement)

        def visit_ClassDef(self, child: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, child: ast.Lambda) -> None:
            return

        def visit_If(self, child: ast.If) -> None:
            self.decisions += 1
            self.generic_visit(child)

        def visit_IfExp(self, child: ast.IfExp) -> None:
            self.decisions += 1
            self.generic_visit(child)

        def visit_For(self, child: ast.For) -> None:
            self.decisions += 1
            self.generic_visit(child)

        def visit_AsyncFor(self, child: ast.AsyncFor) -> None:
            self.decisions += 1
            self.generic_visit(child)

        def visit_While(self, child: ast.While) -> None:
            self.decisions += 1
            self.generic_visit(child)

        def visit_ExceptHandler(self, child: ast.ExceptHandler) -> None:
            self.decisions += 1
            self.generic_visit(child)

        def visit_BoolOp(self, child: ast.BoolOp) -> None:
            self.decisions += max(0, len(child.values) - 1)
            self.generic_visit(child)

        def visit_comprehension(self, child: ast.comprehension) -> None:
            self.decisions += 1 + len(child.ifs)
            self.generic_visit(child)

        def visit_Match(self, child: ast.Match) -> None:
            self.decisions += max(0, len(child.cases) - 1)
            self.generic_visit(child)

    visitor = DecisionVisitor()
    visitor.visit(node)
    return 1 + visitor.decisions


def _function_metadata(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parent_class: str | None = None,
) -> dict:
    return {
        "name": node.name,
        "parent_class": parent_class,
        "start_line": node.lineno,
        "end_line": getattr(node, "end_lineno", node.lineno),
        "docstring": _docstring(node),
        "cyclomatic_complexity": _cyclomatic_complexity(node),
    }


def _parse_file(path: Path, relative_path: str) -> dict:
    try:
        if path.stat().st_size > settings.MAX_SCAN_FILE_SIZE_BYTES:
            raise OSError("file exceeds configured size limit")
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CodeParseError("unreadable source file") from exc

    try:
        tree = ast.parse(source, filename=relative_path)
    except SyntaxError as exc:
        return {
            "path": relative_path,
            "status": "syntax_error",
            "error_line": exc.lineno,
            "error": "Python syntax error",
        }

    functions: list[dict] = []
    classes: list[dict] = []
    imports: list[dict] = []

    class ParserVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            class_info = {
                "name": node.name,
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "docstring": _docstring(node),
                "methods": [],
            }
            classes.append(class_info)
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(
            self,
            node: ast.FunctionDef,
        ) -> None:
            parent_class = self.class_stack[-1] if self.class_stack else None
            metadata = _function_metadata(node, parent_class)
            functions.append(metadata)
            if parent_class is not None:
                for class_info in reversed(classes):
                    if class_info["name"] == parent_class:
                        class_info["methods"].append(metadata)
                        break
            self.generic_visit(node)

        def visit_AsyncFunctionDef(
            self,
            node: ast.AsyncFunctionDef,
        ) -> None:
            parent_class = self.class_stack[-1] if self.class_stack else None
            metadata = _function_metadata(node, parent_class)
            functions.append(metadata)
            if parent_class is not None:
                for class_info in reversed(classes):
                    if class_info["name"] == parent_class:
                        class_info["methods"].append(metadata)
                        break
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                imports.append(
                    {
                        "module": alias.name,
                        "name": alias.asname,
                        "relative": False,
                        "level": 0,
                        "start_line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                    }
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = node.module or ""
            prefix = "." * node.level
            imports.append(
                {
                    "module": f"{prefix}{module}",
                    "name": None,
                    "relative": node.level > 0,
                    "level": node.level,
                    "names": [alias.name for alias in node.names],
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                }
            )

    ParserVisitor().visit(tree)
    return {
        "path": relative_path,
        "status": "parsed",
        "classes": classes,
        "functions": functions,
        "imports": imports,
    }


def parse_repository(user_id: int, repository_id: int) -> ParseResult:
    try:
        root = repository_storage_path(user_id, repository_id)
    except RepositoryCloneError as exc:
        raise CodeParseError("Unable to determine repository storage") from exc

    if not root.is_dir() or not (root / ".git").is_dir():
        raise CodeParseError("Repository has not been cloned successfully")

    python_paths: list[tuple[Path, str]] = []
    for current_root, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current_root)
        depth = len(current_path.relative_to(root).parts)
        if depth >= settings.MAX_SCAN_DIRECTORY_DEPTH:
            directory_names[:] = []
            continue
        directory_names[:] = [
            name
            for name in directory_names
            if (
                name not in IGNORED_DIRECTORIES
                and not (current_path / name).is_symlink()
                and _is_inside(root, current_path / name)
            )
        ]
        for file_name in file_names:
            if len(python_paths) >= settings.MAX_SCAN_FILE_COUNT:
                raise CodeParseError("Repository contains too many Python files")
            path = current_path / file_name
            if (
                path.suffix.lower() != ".py"
                or path.is_symlink()
                or not _is_inside(root, path)
            ):
                continue
            python_paths.append((path, path.relative_to(root).as_posix()))

    files: list[dict] = []
    syntax_error_files = 0
    unreadable_files = 0
    total_classes = 0
    total_functions = 0
    total_imports = 0

    for path, relative_path in python_paths:
        try:
            parsed_file = _parse_file(path, relative_path)
        except CodeParseError:
            unreadable_files += 1
            files.append({"path": relative_path, "status": "unreadable"})
            continue
        files.append(parsed_file)
        if parsed_file["status"] == "syntax_error":
            syntax_error_files += 1
            continue
        total_classes += len(parsed_file["classes"])
        total_functions += len(parsed_file["functions"])
        total_imports += len(parsed_file["imports"])

    python_language = {
        "total_files": len(python_paths),
        "successfully_parsed_files": len(python_paths)
        - syntax_error_files
        - unreadable_files,
        "syntax_error_files": syntax_error_files,
        "unreadable_files": unreadable_files,
        "parser_error_files": 0,
        "total_classes": total_classes,
        "total_interfaces": 0,
        "total_functions": total_functions,
        "total_imports": total_imports,
        "files": files,
    }
    try:
        languages = {
            "Python": python_language,
            **parse_tree_sitter_repository(user_id, repository_id),
        }
    except TreeSitterParseError:
        languages = {"Python": python_language}

    try:
        chunking = chunk_repository(user_id, repository_id)
    except CodeChunkingError as exc:
        raise CodeParseError("Unable to safely chunk repository source") from exc

    return ParseResult(
        total_python_files=len(python_paths),
        successfully_parsed_files=len(python_paths)
        - syntax_error_files
        - unreadable_files,
        syntax_error_files=syntax_error_files,
        unreadable_files=unreadable_files,
        total_classes=total_classes,
        total_functions=total_functions,
        total_imports=total_imports,
        files=files,
        languages=languages,
        chunking=chunking,
    )
