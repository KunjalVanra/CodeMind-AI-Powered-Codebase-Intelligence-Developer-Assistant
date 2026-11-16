from pathlib import Path

import pytest

from app.core.config import settings
from app.services.code_chunking import chunk_repository


def test_chunks_python_javascript_and_typescript_with_relative_lines(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "7" / "11"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "service.py").write_text(
        "import os\n\n"
        "class Service:\n"
        "    def run(self):\n"
        "        return True\n\n"
        "def helper():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (root / "src" / "app.js").write_text(
        'import util from "./utils.js";\n'
        "class App { run() { return util; } }\n"
        "const start = () => true;\n",
        encoding="utf-8",
    )
    (root / "src" / "app.ts").write_text(
        "interface Runner {\n"
        "  run(): void;\n"
        "}\n"
        "function start(): void {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    result = chunk_repository(7, 11)

    chunks = result["chunks"]
    assert result["total_chunks"] == len(chunks)
    assert len({chunk["chunk_id"] for chunk in chunks}) == len(chunks)
    assert {chunk["language"] for chunk in chunks} == {
        "Python",
        "JavaScript",
        "TypeScript",
    }
    assert all(not Path(chunk["file_path"]).is_absolute() for chunk in chunks)
    assert all(chunk["start_line"] <= chunk["end_line"] for chunk in chunks)
    assert any(
        chunk["chunk_type"] == "method"
        and chunk["parent_type"] == "Service"
        for chunk in chunks
    )
    assert any(chunk["chunk_type"] == "interface" for chunk in chunks)
    assert any(chunk["chunk_type"] == "class" and chunk["name"] == "App" for chunk in chunks)
    assert any(
        chunk["chunk_type"] == "function" and chunk["name"] == "start"
        for chunk in chunks
    )
    assert any("./utils.js" in chunk["source_content"] for chunk in chunks)


def test_oversized_semantic_unit_is_split_without_loss_or_overlap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "3" / "5"
    (root / ".git").mkdir(parents=True)
    source_lines = [
        "def large_function():\n",
        *[f"    value_{index} = {index}\n" for index in range(20)],
    ]
    (root / "large.py").write_text("".join(source_lines), encoding="utf-8")
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(settings, "MAX_CODE_CHUNK_CHARS", 50)

    result = chunk_repository(3, 5)
    function_chunks = [
        chunk for chunk in result["chunks"] if chunk["chunk_type"] == "function"
    ]

    assert len(function_chunks) > 1
    assert all(len(chunk["source_content"]) <= 50 for chunk in function_chunks)
    expected_source = (root / "large.py").read_bytes().decode("utf-8")
    assert "".join(chunk["source_content"] for chunk in function_chunks) == expected_source
    assert function_chunks[0]["start_line"] == 1
    assert function_chunks[-1]["end_line"] == len(source_lines)


def test_chunker_skips_empty_binary_ignored_and_unsafe_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "9" / "10"
    (root / ".git").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "empty.ts").write_text("", encoding="utf-8")
    (root / "binary.js").write_bytes(b"\x00binary")
    (root / "node_modules" / "ignored.js").write_text(
        "function ignored() {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    result = chunk_repository(9, 10)

    assert result["total_chunks"] == 0
    assert result["file_statuses"]["unreadable"] == 1
    assert result["file_statuses"]["chunked"] == 1
