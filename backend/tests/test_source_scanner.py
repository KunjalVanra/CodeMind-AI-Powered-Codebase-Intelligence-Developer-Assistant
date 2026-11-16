from pathlib import Path

import pytest

from app.core.config import settings
from app.services import source_scanner


def test_scanner_counts_supported_sources_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "1" / "2"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "node_modules").mkdir()
    (root / "src" / "main.py").write_text("print('hello')\n\n", encoding="utf-8")
    (root / "src" / "app.ts").write_text("const value = 1;\r\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    (root / "node_modules" / "ignored.js").write_text("bad()\n", encoding="utf-8")
    (root / "binary.py").write_bytes(b"\x00not source")
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    result = source_scanner.scan_repository(1, 2)

    assert result.total_files == 4
    assert result.total_source_files == 2
    assert result.total_lines == 3
    assert result.languages["Python"]["files"] == 1
    assert result.languages["Python"]["lines"] == 2
    assert result.languages["TypeScript"]["files"] == 1
    assert result.languages["TypeScript"]["lines"] == 1
    assert result.directories == ["src"]
    assert result.important_files == ["README.md"]


def test_scanner_rejects_uncloned_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)

    with pytest.raises(source_scanner.SourceScanError):
        source_scanner.scan_repository(1, 2)
