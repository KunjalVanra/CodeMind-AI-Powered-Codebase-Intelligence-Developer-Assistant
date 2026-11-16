import os
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.services.repository_cloning import (
    RepositoryCloneError,
    repository_storage_path,
)


LANGUAGE_EXTENSIONS = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".php": "PHP",
    ".rb": "Ruby",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
}

IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".idea",
    ".vscode",
    "coverage",
}
IMPORTANT_FILES = {
    "README.md",
    "requirements.txt",
    "package.json",
    "pyproject.toml",
    "Dockerfile",
    "docker-compose.yml",
}


class SourceScanError(Exception):
    """Raised when a cloned repository cannot be scanned safely."""


@dataclass(frozen=True)
class ScanResult:
    total_files: int
    total_source_files: int
    total_lines: int
    languages: dict[str, dict[str, int]]
    directories: list[str]
    important_files: list[str]

    def as_dict(self) -> dict:
        return {
            "total_files": self.total_files,
            "total_source_files": self.total_source_files,
            "total_lines": self.total_lines,
            "languages": self.languages,
            "directories": self.directories,
            "important_files": self.important_files,
        }


def _is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _count_lines(path: Path) -> int | None:
    try:
        if path.stat().st_size > settings.MAX_SCAN_FILE_SIZE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        text = data.decode("utf-8")
        text = text.replace("\r\r\n", "\r\n")
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
        return len(normalized_text.splitlines())
    except UnicodeDecodeError:
        return None


def scan_repository(user_id: int, repository_id: int) -> ScanResult:
    try:
        root = repository_storage_path(user_id, repository_id)
    except RepositoryCloneError as exc:
        raise SourceScanError("Unable to determine repository storage") from exc

    if not root.is_dir() or not (root / ".git").is_dir():
        raise SourceScanError("Repository has not been cloned successfully")

    total_files = 0
    total_source_files = 0
    total_lines = 0
    languages: dict[str, dict[str, int]] = {}
    directories: set[str] = set()
    important_files: set[str] = set()

    for current_root, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current_root)
        relative_directory = current_path.relative_to(root)
        depth = len(relative_directory.parts)
        if depth > settings.MAX_SCAN_DIRECTORY_DEPTH:
            directory_names[:] = []
            continue

        safe_directories = []
        for directory_name in directory_names:
            directory_path = current_path / directory_name
            if (
                directory_name not in IGNORED_DIRECTORIES
                and not directory_path.is_symlink()
                and _is_inside(root, directory_path)
            ):
                safe_directories.append(directory_name)
                relative_path = directory_path.relative_to(root).as_posix()
                directories.add(relative_path)
        directory_names[:] = safe_directories

        for file_name in file_names:
            if total_files >= settings.MAX_SCAN_FILE_COUNT:
                raise SourceScanError("Repository contains too many files to scan")
            file_path = current_path / file_name
            if file_path.is_symlink() or not _is_inside(root, file_path):
                continue
            total_files += 1
            relative_file = file_path.relative_to(root).as_posix()
            if file_name in IMPORTANT_FILES:
                important_files.add(relative_file)

            language = LANGUAGE_EXTENSIONS.get(file_path.suffix.lower())
            if language is None:
                continue
            lines = _count_lines(file_path)
            if lines is None:
                continue
            total_source_files += 1
            total_lines += lines
            stats = languages.setdefault(language, {"files": 0, "lines": 0})
            stats["files"] += 1
            stats["lines"] += lines

    return ScanResult(
        total_files=total_files,
        total_source_files=total_source_files,
        total_lines=total_lines,
        languages=dict(sorted(languages.items())),
        directories=sorted(directories),
        important_files=sorted(important_files),
    )
