import os
import shutil
from pathlib import Path

from git import Repo
from git.exc import GitCommandError, GitCommandNotFound

from app.core.config import settings


class RepositoryCloneError(Exception):
    """Raised when a repository cannot be cloned safely."""


def repository_storage_path(user_id: int, repository_id: int) -> Path:
    if user_id <= 0 or repository_id <= 0:
        raise RepositoryCloneError("Invalid repository ownership identifiers")

    storage_root = settings.CODEMIND_STORAGE_DIR.expanduser().resolve()
    destination = (storage_root / str(user_id) / str(repository_id)).resolve()
    try:
        destination.relative_to(storage_root)
    except ValueError:
        raise RepositoryCloneError("Unsafe repository storage path") from None
    return destination


def _directory_usage(path: Path) -> tuple[int, int]:
    total_bytes = 0
    file_count = 0
    for root, directories, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        directories[:] = [
            directory
            for directory in directories
            if not (root_path / directory).is_symlink()
        ]
        for filename in files:
            file_path = root_path / filename
            if file_path.is_symlink():
                continue
            try:
                total_bytes += file_path.stat().st_size
            except OSError as exc:
                raise RepositoryCloneError(
                    "Unable to inspect the cloned repository"
                ) from exc
            file_count += 1
    return total_bytes, file_count


def _ensure_clone_size(destination: Path) -> None:
    total_bytes, file_count = _directory_usage(destination)
    if (
        total_bytes > settings.MAX_CLONE_SIZE_BYTES
        or file_count > settings.MAX_CLONE_FILE_COUNT
    ):
        raise RepositoryCloneError(
            "Repository exceeds the configured clone size limits"
        )


def clone_repository(
    github_url: str,
    default_branch: str,
    user_id: int,
    repository_id: int,
) -> Path:
    destination = repository_storage_path(user_id, repository_id)

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.is_dir() and (destination / ".git").is_dir():
                return destination
            raise RepositoryCloneError(
                "The repository storage directory is already in use"
            )

        Repo.clone_from(
            github_url,
            destination,
            branch=default_branch,
            depth=1,
            no_tags=True,
            single_branch=True,
        )
        _ensure_clone_size(destination)
    except (GitCommandNotFound, GitCommandError, OSError) as exc:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if isinstance(exc, GitCommandNotFound):
            message = "Git is not installed or is not available on the server"
        elif isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
            message = "Insufficient disk space for the repository clone"
        else:
            message = "Unable to clone the GitHub repository"
        raise RepositoryCloneError(message) from exc
    except RepositoryCloneError:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise

    return destination
