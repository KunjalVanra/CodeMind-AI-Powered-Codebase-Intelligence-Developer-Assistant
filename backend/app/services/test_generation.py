import ast
import json
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.schemas.test_generation import TestFramework
from app.services.documentation import load_parsed_source_file
from app.services.llm_service import (
    LLMConfigurationError,
    LLMProviderError,
    generate_unit_test_response,
)


__test__ = False


MAX_TEST_SOURCE_CHARS = 20_000
SUPPORTED_LANGUAGE = "Python"


class TestGenerationError(Exception):
    """Raised when source data cannot be used safely for test generation."""


class UnsupportedTestLanguageError(TestGenerationError):
    """Raised when the requested source language is not supported."""


@dataclass(frozen=True)
class TestGenerationResult:
    source_file_path: str
    language: str
    test_framework: TestFramework
    generated_test_code: str
    explanation: str
    sufficient_source_information: bool
    limitations: list[str]
    model: str | None


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    positional = [arg.arg for arg in node.args.posonlyargs + node.args.args]
    if node.args.vararg is not None:
        positional.append(f"*{node.args.vararg.arg}")
    positional.extend(arg.arg for arg in node.args.kwonlyargs)
    if node.args.kwarg is not None:
        positional.append(f"**{node.args.kwarg.arg}")
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({', '.join(positional)})"


def _symbols(tree: ast.Module) -> list[dict[str, Any]]:
    symbols = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                symbols.append(
                    {
                        "kind": "function",
                        "name": node.name,
                        "signature": _function_signature(node),
                        "start_line": node.lineno,
                        "end_line": getattr(node, "end_lineno", node.lineno),
                        "docstring": ast.get_docstring(node, clean=True),
                    }
                )
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            methods = [
                _function_signature(item)
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not item.name.startswith("_")
            ]
            symbols.append(
                {
                    "kind": "class",
                    "name": node.name,
                    "start_line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "docstring": ast.get_docstring(node, clean=True),
                    "public_methods": methods,
                }
            )
    return symbols


def _insufficient(
    source_file_path: str,
    framework: TestFramework,
    explanation: str,
    limitation: str,
) -> TestGenerationResult:
    return TestGenerationResult(
        source_file_path=source_file_path,
        language=SUPPORTED_LANGUAGE,
        test_framework=framework,
        generated_test_code="",
        explanation=explanation,
        sufficient_source_information=False,
        limitations=[limitation],
        model=None,
    )


def generate_tests_for_source(
    *,
    user_id: int,
    repository_id: int,
    parse_summary: dict[str, Any],
    file_path: str,
    framework: TestFramework | None = None,
) -> TestGenerationResult:
    file_entry, source = load_parsed_source_file(
        user_id=user_id,
        repository_id=repository_id,
        parse_summary=parse_summary,
        file_path=file_path,
    )

    language = file_entry.get("language")
    normalized_path = str(file_entry["path"])
    if language != SUPPORTED_LANGUAGE or not normalized_path.lower().endswith(".py"):
        raise UnsupportedTestLanguageError(
            "Automated test generation currently supports Python source files only"
        )

    selected_framework: TestFramework = framework or "unittest"
    if not source.strip():
        return _insufficient(
            normalized_path,
            selected_framework,
            "The source file is empty, so there is no code to generate tests for.",
            "Empty source files are not sent to the AI provider.",
        )

    try:
        tree = ast.parse(source, filename=normalized_path)
    except (SyntaxError, ValueError):
        return _insufficient(
            normalized_path,
            selected_framework,
            "The current source file could not be parsed as valid Python.",
            "The source may have changed since the repository was last parsed.",
        )

    symbols = _symbols(tree)
    if not symbols:
        return _insufficient(
            normalized_path,
            selected_framework,
            "No public functions or classes were found in the parsed source.",
            "Test generation currently targets public Python functions and classes.",
        )
    if len(source) > MAX_TEST_SOURCE_CHARS:
        return _insufficient(
            normalized_path,
            selected_framework,
            "The source file is too large to include safely in the bounded generation context.",
            f"Source files over {MAX_TEST_SOURCE_CHARS} characters are not sent to the AI provider.",
        )

    context = json.dumps(
        {
            "source_file_path": normalized_path,
            "language": SUPPORTED_LANGUAGE,
            "test_framework": selected_framework,
            "symbols_extracted_from_source": symbols,
            "source_code": source,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    generated = generate_unit_test_response(
        source_file_path=normalized_path,
        framework=selected_framework,
        context=context,
    )
    return TestGenerationResult(
        source_file_path=normalized_path,
        language=SUPPORTED_LANGUAGE,
        test_framework=selected_framework,
        generated_test_code=generated["generated_test_code"],
        explanation=generated["explanation"],
        sufficient_source_information=generated["sufficient_source_information"],
        limitations=list(generated["limitations"])
        + [
            "AI-generated tests are not verified; they were not executed.",
            "Project-specific import paths and test-runner availability were not verified.",
        ],
        model=settings.GROQ_MODEL,
    )


__all__ = [
    "LLMConfigurationError",
    "LLMProviderError",
    "TestGenerationError",
    "TestGenerationResult",
    "UnsupportedTestLanguageError",
    "generate_tests_for_source",
]
