import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings
from app.services.repository_cloning import (
    RepositoryCloneError,
    repository_storage_path,
)
from app.services.source_scanner import IGNORED_DIRECTORIES


SEVERITY_COUNTS = ("critical", "high", "medium", "low", "informational")
MAX_SNIPPET_LENGTH = 2_000
SEMGREP_TIMEOUT_SECONDS = 300


class SecurityScannerUnavailable(Exception):
    """Raised when Semgrep is not installed on the backend host."""


class SecurityRepositoryError(Exception):
    """Raised when a cloned repository cannot be accessed safely."""


class SecurityScanError(Exception):
    """Raised when the static security scan cannot be completed."""


def _is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _stage_repository(root: Path, staging_root: Path) -> tuple[int, int]:
    scanned_files = 0
    skipped_files = 0
    visited_files = 0

    for current_root, directory_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current_root)
        if len(current_path.relative_to(root).parts) > settings.MAX_SCAN_DIRECTORY_DEPTH:
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
            if visited_files >= settings.MAX_SCAN_FILE_COUNT:
                raise SecurityScanError(
                    "Repository contains too many files to scan safely"
                )
            path = current_path / file_name
            if path.is_symlink() or not _is_inside(root, path) or not path.is_file():
                continue
            visited_files += 1
            try:
                if path.stat().st_size > settings.MAX_SCAN_FILE_SIZE_BYTES:
                    skipped_files += 1
                    continue
                content = path.read_bytes()
            except OSError:
                skipped_files += 1
                continue
            if len(content) > settings.MAX_SCAN_FILE_SIZE_BYTES or b"\x00" in content:
                skipped_files += 1
                continue

            relative_path = path.relative_to(root)
            target = staging_root / relative_path
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            except OSError as exc:
                raise SecurityScanError(
                    "Unable to prepare repository files for static analysis"
                ) from exc
            scanned_files += 1

    return scanned_files, skipped_files


def _relative_finding_path(value: object, staging_root: Path) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = staging_root / candidate
        return candidate.resolve().relative_to(staging_root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None


def _severity(value: object) -> str:
    normalized = str(value).strip().lower()
    mapping = {
        "critical": "critical",
        "high": "high",
        "error": "high",
        "medium": "medium",
        "warning": "medium",
        "low": "low",
        "informational": "informational",
        "info": "informational",
    }
    return mapping.get(normalized, "informational")


def _finding(result: object, staging_root: Path) -> dict | None:
    if not isinstance(result, dict):
        return None
    extra = result.get("extra")
    start = result.get("start")
    end = result.get("end")
    if not isinstance(extra, dict) or not isinstance(start, dict):
        return None

    rule_id = result.get("check_id")
    message = extra.get("message")
    file_path = _relative_finding_path(result.get("path"), staging_root)
    start_line = start.get("line")
    end_line = end.get("line") if isinstance(end, dict) else start_line
    if (
        not isinstance(rule_id, str)
        or not rule_id
        or not isinstance(message, str)
        or not message
        or file_path is None
        or not isinstance(start_line, int)
        or start_line < 1
        or not isinstance(end_line, int)
        or end_line < start_line
    ):
        return None

    metadata = extra.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    title = metadata.get("shortDescription")
    if not isinstance(title, str) or not title:
        title = message
    snippet = extra.get("lines")
    if not isinstance(snippet, str) or len(snippet) > MAX_SNIPPET_LENGTH:
        snippet = None
    remediation = next(
        (
            metadata[key]
            for key in ("remediation", "fix_guidance", "recommendation", "solution")
            if isinstance(metadata.get(key), str) and metadata[key]
        ),
        None,
    )
    return {
        "rule_id": rule_id,
        "severity": _severity(extra.get("severity")),
        "title": title,
        "message": message,
        "file_path": file_path,
        "start_line": start_line,
        "end_line": end_line,
        "code_snippet": snippet,
        "remediation": remediation,
    }


def _parse_semgrep_output(output: str, staging_root: Path) -> list[dict]:
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError) as exc:
        raise SecurityScanError("Semgrep returned an invalid scan response") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise SecurityScanError("Semgrep returned an invalid scan response")
    if payload.get("errors"):
        raise SecurityScanError("Semgrep reported errors while scanning the repository")

    findings = []
    for result in payload["results"]:
        finding = _finding(result, staging_root)
        if finding is None:
            raise SecurityScanError("Semgrep returned a malformed finding")
        findings.append(finding)
    return sorted(
        findings,
        key=lambda finding: (
            finding["file_path"],
            finding["start_line"],
            finding["rule_id"],
        ),
    )


def scan_repository_security(user_id: int, repository_id: int) -> dict:
    try:
        repository_root = repository_storage_path(user_id, repository_id)
    except RepositoryCloneError as exc:
        raise SecurityRepositoryError(
            "Unable to determine repository storage"
        ) from exc
    git_directory = repository_root / ".git"
    if (
        not repository_root.is_dir()
        or git_directory.is_symlink()
        or not git_directory.is_dir()
    ):
        raise SecurityRepositoryError("Repository has not been cloned successfully")

    semgrep = shutil.which("semgrep")
    if semgrep is None:
        raise SecurityScannerUnavailable("Semgrep is not installed")

    try:
        with tempfile.TemporaryDirectory(prefix="codemind-security-") as directory:
            staging_root = Path(directory)
            scanned_files, skipped_files = _stage_repository(
                repository_root, staging_root
            )
            if scanned_files == 0:
                findings = []
            else:
                try:
                    completed = subprocess.run(
                        [
                            semgrep,
                            "scan",
                            "--config",
                            "auto",
                            "--json",
                            "--quiet",
                            "--metrics=off",
                            "--timeout",
                            "10",
                            ".",
                        ],
                        cwd=staging_root,
                        capture_output=True,
                        text=True,
                        timeout=SEMGREP_TIMEOUT_SECONDS,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise SecurityScanError(
                        "Semgrep timed out while scanning the repository"
                    ) from exc
                except OSError as exc:
                    raise SecurityScanError(
                        "Unable to start the Semgrep scanner"
                    ) from exc
                if completed.returncode not in {0, 1}:
                    raise SecurityScanError(
                        "Semgrep could not complete the repository scan"
                    )
                findings = _parse_semgrep_output(
                    completed.stdout,
                    staging_root,
                )
    except OSError as exc:
        raise SecurityScanError("Unable to safely prepare the repository scan") from exc

    summary = {severity: 0 for severity in SEVERITY_COUNTS}
    for finding in findings:
        summary[finding["severity"]] += 1
    return {
        "scanner": "Semgrep",
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "total_findings": len(findings),
        "summary": summary,
        "findings": findings,
    }
