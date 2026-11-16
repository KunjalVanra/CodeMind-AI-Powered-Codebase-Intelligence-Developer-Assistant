from pathlib import Path

import pytest

from app.core.config import settings
from app.services.tree_sitter_parser import parse_tree_sitter_repository


def test_tree_sitter_parses_mixed_language_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "1" / "2"
    (root / ".git").mkdir(parents=True)
    (root / "app.js").write_text(
        'import client from "./utils.js";\n'
        "class Service { run() {} }\n"
        "function start() {}\n",
        encoding="utf-8",
    )
    (root / "main.go").write_text(
        'package main\nimport "fmt"\nfunc main() {}\n',
        encoding="utf-8",
    )
    (root / "ignored.py").write_text("def python_only():\n    pass\n", encoding="utf-8")
    (root / "empty.ts").write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    result = parse_tree_sitter_repository(1, 2)

    assert set(result) == {"Go", "JavaScript", "TypeScript"}
    assert result["JavaScript"]["total_classes"] == 1
    assert result["JavaScript"]["total_functions"] == 2
    assert (
        result["JavaScript"]["files"][0]["imports"][0]["module"]
        == "./utils.js"
    )
    assert result["JavaScript"]["files"][0]["functions"][0]["parent_type"] == "Service"
    assert result["Go"]["total_functions"] == 1
    assert result["Go"]["total_imports"] == 1
    assert result["TypeScript"]["successfully_parsed_files"] == 1


def test_tree_sitter_handles_syntax_errors_and_binary_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "1" / "2"
    (root / ".git").mkdir(parents=True)
    (root / "broken.js").write_text("function broken( {\n", encoding="utf-8")
    (root / "binary.rs").write_bytes(b"\x00not source")
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    result = parse_tree_sitter_repository(1, 2)

    assert result["JavaScript"]["syntax_error_files"] == 1
    assert result["Rust"]["unreadable_files"] == 1
    assert all("not source" not in str(result) for _ in [0])
