from urllib.parse import urlparse
import json
import logging
import math
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.services.repository_cloning import (
    RepositoryCloneError,
    clone_repository,
)
from app.services.documentation import (
    DocumentationPathError,
    DocumentationRepositoryError,
    DocumentationSourceFileNotFound,
    DocumentationSourceFileUnavailable,
    generate_repository_documentation,
)
from app.models.repository import Repository
from app.models.analysis import Analysis
from app.models.user import User
from app.schemas.repository import RepositoryCreate, RepositoryResponse
from app.schemas.scan import ScanResponse
from app.schemas.parse import ParseResponse
from app.schemas.indexing import IndexingResponse
from app.schemas.search import CodeSearchRequest, CodeSearchResponse, CodeSearchResult
from app.schemas.ask import CodeAskRequest, CodeAskResponse
from app.schemas.dependency import DependencyGraphResponse
from app.schemas.architecture import ArchitectureAnalysisResponse
from app.schemas.security import SecurityScanResponse
from app.schemas.documentation import (
    DocumentationRequest,
    DocumentationResponse,
)
from app.schemas.test_generation import (
    TestGenerationRequest,
    TestGenerationResponse,
)
from app.services.code_parser import CodeParseError, parse_repository
from app.services.dependency_graph import (
    SUPPORTED_ANALYSIS_LANGUAGES,
    build_dependency_graph,
)
from app.services.architecture_analysis import build_architecture_analysis
from app.services.security_analysis import (
    SecurityRepositoryError,
    SecurityScanError,
    SecurityScannerUnavailable,
    scan_repository_security,
)
from app.services.llm_service import LLMConfigurationError, LLMProviderError
from app.services.rag_service import RAGRetrievalError, answer_repository_question
from app.services.semantic_retrieval import (
    SemanticRetrievalError,
    has_indexed_chunks,
    retrieve_code,
)
from app.services.vector_indexing import VectorIndexingError, index_chunks
from app.services.source_scanner import SourceScanError, scan_repository
from app.services.test_generation import (
    UnsupportedTestLanguageError,
    generate_tests_for_source,
)
router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])
GITHUB_API_URL = "https://api.github.com/repos"
logger = logging.getLogger(__name__)


def parse_github_repository_url(github_url: str) -> tuple[str, str, str]:
    parsed_url = urlparse(github_url)
    if parsed_url.scheme != "https" or parsed_url.netloc.lower() not in {
        "github.com",
        "www.github.com",
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL must be an HTTPS GitHub repository URL",
        )

    path_parts = [part for part in parsed_url.path.split("/") if part]
    if (
        len(path_parts) != 2
        or parsed_url.query
        or parsed_url.fragment
        or any(character in path_parts[0] + path_parts[1] for character in "?#")
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL must point to a GitHub repository in the form https://github.com/owner/repository",
        )

    owner_name, repository_name = path_parts
    if repository_name.endswith(".git"):
        repository_name = repository_name[:-4]
    if not owner_name or not repository_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="URL must point to a GitHub repository in the form https://github.com/owner/repository",
        )

    canonical_url = f"https://github.com/{owner_name}/{repository_name}"
    return owner_name, repository_name, canonical_url


def fetch_github_repository(owner_name: str, repository_name: str) -> dict:
    try:
        response = httpx.get(
            f"{GITHUB_API_URL}/{owner_name}/{repository_name}",
            headers={"Accept": "application/vnd.github+json"},
            timeout=10.0,
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach the GitHub API",
        ) from None

    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub repository was not found or is not public",
        )
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub API request failed",
        )

    try:
        metadata = response.json()
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub API returned an invalid response",
        ) from None
    if not isinstance(metadata, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub API returned an invalid response",
        )
    if metadata.get("private") is not False:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub repository was not found or is not public",
        )
    return metadata


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_repository(
    payload: RepositoryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Repository:
    owner_name, repository_name, canonical_url = parse_github_repository_url(
        str(payload.github_url)
    )
    try:
        existing_repository = (
            db.query(Repository)
            .filter(
                Repository.user_id == current_user.id,
                Repository.github_url == canonical_url,
            )
            .first()
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to check repository ownership",
        ) from None
    if existing_repository is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This repository is already connected",
        )

    metadata = fetch_github_repository(owner_name, repository_name)
    if metadata.get("private") is not False:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub repository was not found or is not public",
        )

    repository = Repository(
        user_id=current_user.id,
        github_url=canonical_url,
        name=metadata.get("name", repository_name),
        owner_name=metadata.get("owner", {}).get("login", owner_name),
        default_branch=metadata.get("default_branch") or "main",
        status="connected",
    )
    db.add(repository)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This repository is already connected",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save repository",
        ) from None
    db.refresh(repository)
    return repository


@router.get("", response_model=list[RepositoryResponse])
def list_repositories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Repository]:
    try:
        return (
            db.query(Repository)
            .filter(Repository.user_id == current_user.id)
            .order_by(Repository.id)
            .all()
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repositories",
        ) from None


@router.get("/{repository_id}", response_model=RepositoryResponse)
def get_repository(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Repository:
    try:
        repository = (
            db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.user_id == current_user.id,
            )
            .first()
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repository",
        ) from None
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    return repository


@router.get(
    "/{repository_id}/dependencies",
    response_model=DependencyGraphResponse,
)
def get_repository_dependencies(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        repository = (
            db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.user_id == current_user.id,
            )
            .first()
        )
        if repository is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository not found",
            )
        analyses = (
            db.query(Analysis)
            .filter(
                Analysis.user_id == current_user.id,
                Analysis.repository_id == repository.id,
                Analysis.status == "completed",
                Analysis.summary.isnot(None),
            )
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .all()
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repository analysis",
        ) from None

    latest_parse = None
    latest_scan_languages: set[str] = set()
    latest_scan_found = False
    for analysis in analyses:
        try:
            summary = json.loads(analysis.summary or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(summary, dict):
            continue
        if (
            latest_parse is None
            and isinstance(summary.get("total_python_files"), int)
            and isinstance(summary.get("languages"), dict)
        ):
            latest_parse = (analysis, summary)
        if not latest_scan_found and isinstance(
            summary.get("total_source_files"), int
        ):
            latest_scan_found = True
            languages = summary.get("languages")
            if isinstance(languages, dict):
                latest_scan_languages = {
                    language for language in languages if isinstance(language, str)
                }

    if latest_parse is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No completed parse analysis is available; parse the repository first",
        )

    analysis, parse_summary = latest_parse
    graph = build_dependency_graph(parse_summary)
    graph.update(
        {
            "repository_id": repository.id,
            "analysis_id": analysis.id,
            "status": analysis.status,
            "unsupported_languages": sorted(
                latest_scan_languages - SUPPORTED_ANALYSIS_LANGUAGES
            ),
        }
    )
    return graph


@router.get(
    "/{repository_id}/architecture",
    response_model=ArchitectureAnalysisResponse,
)
def get_repository_architecture(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ArchitectureAnalysisResponse:
    try:
        repository = (
            db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.user_id == current_user.id,
            )
            .first()
        )
        if repository is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository not found",
            )
        analysis_query = db.query(Analysis.id, Analysis.summary).filter(
            Analysis.user_id == current_user.id,
            Analysis.repository_id == repository.id,
            Analysis.status == "completed",
            Analysis.summary.isnot(None),
        )
        scan_candidates = (
            analysis_query.filter(Analysis.summary.like('%"total_source_files"%'))
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .limit(20)
            .all()
        )
        parse_candidates = (
            analysis_query.filter(Analysis.summary.like('%"total_python_files"%'))
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .limit(20)
            .all()
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repository analysis",
        ) from None

    def find_latest_summary(
        candidates: list[tuple[int, str]],
        required_keys: tuple[str, ...],
    ) -> tuple[int, dict] | None:
        for analysis_id, stored_summary in candidates:
            try:
                summary = json.loads(stored_summary or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(summary, dict) or not all(
                key in summary for key in required_keys
            ):
                continue
            return analysis_id, summary
        return None

    scan_record = find_latest_summary(
        scan_candidates,
        ("total_source_files", "total_lines"),
    )
    parse_record = find_latest_summary(
        parse_candidates,
        ("total_python_files", "languages"),
    )

    return build_architecture_analysis(
        repository_id=repository.id,
        scan_analysis_id=scan_record[0] if scan_record else None,
        scan_summary=scan_record[1] if scan_record else None,
        parse_analysis_id=parse_record[0] if parse_record else None,
        parse_summary=parse_record[1] if parse_record else None,
    )


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_repository(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    repository = (
        db.query(Repository)
        .filter(
            Repository.id == repository_id,
            Repository.user_id == current_user.id,
        )
        .first()
    )
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    try:
        db.delete(repository)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            "Failed to persist Python parse results for repository_id=%s "
            "user_id=%s",
            repository_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete repository",
        ) from None


@router.post(
    "/{repository_id}/clone",
    response_model=RepositoryResponse,
)
def clone_repository_endpoint(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Repository:
    try:
        repository = (
            db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.user_id == current_user.id,
            )
            .first()
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repository",
        ) from None

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    if repository.status == "cloned":
        return repository

    repository.status = "cloning"
    try:
        db.commit()
        clone_repository(
            repository.github_url,
            repository.default_branch or "main",
            current_user.id,
            repository.id,
        )
        repository.status = "cloned"
        db.commit()
    except RepositoryCloneError as exc:
        db.rollback()
        repository.status = "clone_failed"
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update repository status",
        ) from None

    db.refresh(repository)
    return repository


@router.post(
    "/{repository_id}/scan",
    response_model=ScanResponse,
)
def scan_repository_endpoint(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScanResponse:
    repository = (
        db.query(Repository)
        .filter(
            Repository.id == repository_id,
            Repository.user_id == current_user.id,
        )
        .first()
    )
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    if repository.status != "cloned":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository must be cloned before scanning",
        )

    analysis = Analysis(
        user_id=current_user.id,
        repository_id=repository.id,
        status="scanning",
    )
    db.add(analysis)
    try:
        db.commit()
        db.refresh(analysis)
        result = scan_repository(current_user.id, repository.id)
        analysis.status = "completed"
        analysis.total_files = result.total_files
        analysis.summary = json.dumps(result.as_dict())
        db.commit()
        db.refresh(analysis)
    except SourceScanError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save scan results",
        ) from None

    summary = json.loads(analysis.summary or "{}")
    return ScanResponse(
        analysis_id=analysis.id,
        repository_id=analysis.repository_id,
        status=analysis.status,
        total_files=analysis.total_files,
        total_source_files=summary.get("total_source_files", 0),
        total_lines=summary.get("total_lines", 0),
        languages=summary.get("languages", {}),
        directories=summary.get("directories", []),
        important_files=summary.get("important_files", []),
        created_at=analysis.created_at,
    )


@router.post(
    "/{repository_id}/security-scan",
    response_model=SecurityScanResponse,
)
def security_scan_repository_endpoint(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SecurityScanResponse:
    try:
        repository = (
            db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.user_id == current_user.id,
            )
            .first()
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repository",
        ) from None

    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    if repository.status != "cloned":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository must be cloned before security scanning",
        )

    try:
        result = scan_repository_security(current_user.id, repository.id)
    except SecurityScannerUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Static security scanning is unavailable because Semgrep is not installed",
        ) from None
    except SecurityRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    except SecurityScanError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from None

    analysis = Analysis(
        user_id=current_user.id,
        repository_id=repository.id,
        status="completed",
        total_files=result["scanned_files"],
        summary=json.dumps(
            {
                "analysis_type": "security_scan",
                **result,
            }
        ),
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(analysis)
    try:
        db.commit()
        db.refresh(analysis)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save security scan results",
        ) from None

    return SecurityScanResponse(
        analysis_id=analysis.id,
        repository_id=repository.id,
        status=analysis.status,
        created_at=analysis.created_at,
        **result,
    )


@router.post(
    "/{repository_id}/parse",
    response_model=ParseResponse,
)
def parse_repository_endpoint(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ParseResponse:
    repository = (
        db.query(Repository)
        .filter(
            Repository.id == repository_id,
            Repository.user_id == current_user.id,
        )
        .first()
    )
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    if repository.status != "cloned":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository must be cloned before parsing",
        )

    analysis = Analysis(
        user_id=current_user.id,
        repository_id=repository.id,
        status="parsing",
    )
    db.add(analysis)
    try:
        db.commit()
        db.refresh(analysis)
        result = parse_repository(current_user.id, repository.id)
        analysis.status = "completed"
        analysis.total_files = result.total_python_files
        analysis.summary = json.dumps(result.as_dict())
        analysis.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        db.refresh(analysis)
    except CodeParseError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save parse results",
        ) from None

    summary = json.loads(analysis.summary or "{}")
    return ParseResponse(
        analysis_id=analysis.id,
        repository_id=analysis.repository_id,
        status=analysis.status,
        created_at=analysis.created_at,
        **{
            key: summary.get(key, 0)
            for key in (
                "total_python_files",
                "successfully_parsed_files",
                "syntax_error_files",
                "unreadable_files",
                "total_classes",
                "total_functions",
                "total_imports",
            )
        },
        files=summary.get("files", []),
        languages=summary.get("languages", {}),
        chunk_count=summary.get("chunking", {}).get("total_chunks", 0),
        chunk_file_statuses=summary.get("chunking", {}).get("file_statuses", {}),
    )


@router.post(
    "/{repository_id}/documentation",
    response_model=DocumentationResponse,
)
def generate_repository_documentation_endpoint(
    repository_id: int,
    request: DocumentationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentationResponse:
    try:
        repository = (
            db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.user_id == current_user.id,
            )
            .first()
        )
        if repository is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository not found",
            )
        if repository.status != "cloned":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Repository must be cloned before documentation can be generated",
            )

        analyses = (
            db.query(Analysis)
            .filter(
                Analysis.user_id == current_user.id,
                Analysis.repository_id == repository.id,
                Analysis.status == "completed",
                Analysis.summary.isnot(None),
            )
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .all()
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repository analysis",
        ) from None

    parse_summary = None
    for analysis in analyses:
        try:
            summary = json.loads(analysis.summary or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            isinstance(summary, dict)
            and type(summary.get("total_python_files")) is int
            and isinstance(summary.get("languages"), dict)
        ):
            parse_summary = summary
            break
    if parse_summary is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No completed parse analysis is available; parse the repository first",
        )

    try:
        result = generate_repository_documentation(
            user_id=current_user.id,
            repository_id=repository.id,
            repository_name=repository.name,
            default_branch=repository.default_branch or "main",
            parse_summary=parse_summary,
            documentation_type=request.documentation_type,
            file_path=request.file_path,
        )
    except DocumentationPathError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except DocumentationRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    except LLMConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI documentation generation is not configured",
        ) from None
    except LLMProviderError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI documentation service is temporarily unavailable",
        ) from None

    analysis = Analysis(
        user_id=current_user.id,
        repository_id=repository.id,
        status="completed",
        total_files=result.source_file_count,
        summary=json.dumps(
            {
                "analysis_type": "documentation",
                "documentation_type": result.documentation_type,
                "file_path": result.file_path,
                "documentation": result.documentation,
                "sufficient_information": result.sufficient_information,
                "notice": result.notice,
                "limitations": result.limitations,
                "source_file_count": result.source_file_count,
                "model": result.model,
            }
        ),
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(analysis)
    try:
        db.commit()
        db.refresh(analysis)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save generated documentation",
        ) from None

    return DocumentationResponse(
        analysis_id=analysis.id,
        repository_id=repository.id,
        documentation_type=result.documentation_type,
        file_path=result.file_path,
        status=analysis.status,
        documentation=result.documentation,
        sufficient_information=result.sufficient_information,
        notice=result.notice,
        limitations=result.limitations,
        source_file_count=result.source_file_count,
        model=result.model,
        created_at=analysis.created_at,
    )


@router.post(
    "/{repository_id}/generate-tests",
    response_model=TestGenerationResponse,
)
def generate_repository_tests_endpoint(
    repository_id: int,
    request: TestGenerationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TestGenerationResponse:
    try:
        repository = (
            db.query(Repository)
            .filter(
                Repository.id == repository_id,
                Repository.user_id == current_user.id,
            )
            .first()
        )
        if repository is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Repository not found",
            )
        if repository.status != "cloned":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Repository must be cloned before generating tests",
            )

        analyses = (
            db.query(Analysis)
            .filter(
                Analysis.user_id == current_user.id,
                Analysis.repository_id == repository.id,
                Analysis.status == "completed",
                Analysis.summary.isnot(None),
            )
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .all()
        )
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repository analysis",
        ) from None

    parse_summary = None
    for analysis in analyses:
        try:
            summary = json.loads(analysis.summary or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            isinstance(summary, dict)
            and type(summary.get("total_python_files")) is int
            and isinstance(summary.get("languages"), dict)
        ):
            parse_summary = summary
            break
    if parse_summary is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No completed parse analysis is available; parse the repository first",
        )

    try:
        result = generate_tests_for_source(
            user_id=current_user.id,
            repository_id=repository.id,
            parse_summary=parse_summary,
            file_path=request.file_path,
            framework=request.framework,
        )
    except DocumentationSourceFileNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from None
    except DocumentationSourceFileUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except DocumentationPathError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except DocumentationRepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    except UnsupportedTestLanguageError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    except LLMConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI test generation is not configured",
        ) from None
    except LLMProviderError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI test generation service is temporarily unavailable",
        ) from None

    analysis = Analysis(
        user_id=current_user.id,
        repository_id=repository.id,
        status="completed",
        total_files=1,
        summary=json.dumps(
            {
                "analysis_type": "test_generation",
                "source_file_path": result.source_file_path,
                "language": result.language,
                "test_framework": result.test_framework,
                "generated_test_code": result.generated_test_code,
                "explanation": result.explanation,
                "sufficient_source_information": result.sufficient_source_information,
                "verified": False,
                "verification_status": "not_executed",
                "limitations": result.limitations,
                "model": result.model,
            }
        ),
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(analysis)
    try:
        db.commit()
        db.refresh(analysis)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save generated tests",
        ) from None

    return TestGenerationResponse(
        analysis_id=analysis.id,
        repository_id=repository.id,
        status=analysis.status,
        source_file_path=result.source_file_path,
        language=result.language,
        test_framework=result.test_framework,
        generated_test_code=result.generated_test_code,
        explanation=result.explanation,
        sufficient_source_information=result.sufficient_source_information,
        verified=False,
        verification_status="not_executed",
        limitations=result.limitations,
        model=result.model,
        created_at=analysis.created_at,
    )


@router.post(
    "/{repository_id}/index",
    response_model=IndexingResponse,
)
def index_repository_endpoint(
    repository_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> IndexingResponse:
    repository = (
        db.query(Repository)
        .filter(
            Repository.id == repository_id,
            Repository.user_id == current_user.id,
        )
        .first()
    )
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )
    if repository.status != "cloned":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository must be cloned before indexing",
        )

    try:
        analyses = (
            db.query(Analysis)
            .filter(
                Analysis.user_id == current_user.id,
                Analysis.repository_id == repository.id,
                Analysis.status == "completed",
                Analysis.summary.isnot(None),
            )
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .all()
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve repository analysis",
        ) from None

    latest_analysis = None
    chunk_records = []
    for candidate in analyses:
        try:
            candidate_summary = json.loads(candidate.summary or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        candidate_chunks = candidate_summary.get("chunking", {}).get("chunks")
        if isinstance(candidate_chunks, list) and candidate_chunks:
            latest_analysis = candidate
            chunk_records = candidate_chunks
            break
    if latest_analysis is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No completed analysis with code chunks is available",
        )

    try:
        result = index_chunks(
            chunk_records,
            user_id=current_user.id,
            repository_id=repository.id,
            analysis_id=latest_analysis.id,
        )
    except VectorIndexingError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector indexing is unavailable",
        ) from None

    indexing_status = (
        "indexed"
        if result["failed_chunks"] == 0
        else "partially_indexed"
        if result["indexed_chunks"] > 0
        else "failed"
    )
    return IndexingResponse(
        status=indexing_status,
        analysis_id=latest_analysis.id,
        repository_id=repository.id,
        total_chunks=result["total_chunks"],
        indexed_chunks=result["indexed_chunks"],
        failed_chunks=result["failed_chunks"],
        collection_name=result["collection_name"],
    )


def _safe_relative_file_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        return None

    normalized = value.replace("\\", "/")
    path_parts = normalized.split("/")
    if (
        normalized.startswith("/")
        or ":" in path_parts[0]
        or any(part == ".." for part in path_parts)
    ):
        return None

    relative_path = "/".join(part for part in path_parts if part not in {"", "."})
    return relative_path or None


def _to_search_result(match: dict) -> CodeSearchResult | None:
    metadata = match.get("metadata")
    source_content = match.get("source_content")
    if not isinstance(metadata, dict) or not isinstance(source_content, str):
        return None

    file_path = _safe_relative_file_path(metadata.get("file_path"))
    start_line = metadata.get("start_line")
    end_line = metadata.get("end_line")
    distance = match.get("distance")
    if (
        file_path is None
        or type(start_line) is not int
        or type(end_line) is not int
        or start_line < 1
        or end_line < start_line
        or not isinstance(distance, (int, float))
        or not math.isfinite(distance)
    ):
        return None

    def optional_text(key: str) -> str | None:
        value = metadata.get(key)
        return value if isinstance(value, str) and value else None

    return CodeSearchResult(
        file_path=file_path,
        language=optional_text("language") or "unknown",
        chunk_type=optional_text("chunk_type") or "unknown",
        symbol=optional_text("symbol"),
        parent_type=optional_text("parent_type"),
        start_line=start_line,
        end_line=end_line,
        similarity=1.0 - float(distance),
        snippet=source_content,
    )


@router.post(
    "/{repository_id}/search",
    response_model=CodeSearchResponse,
)
def search_repository_endpoint(
    repository_id: int,
    request: CodeSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CodeSearchResponse:
    repository = (
        db.query(Repository)
        .filter(
            Repository.id == repository_id,
            Repository.user_id == current_user.id,
        )
        .first()
    )
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    try:
        if not has_indexed_chunks(current_user.id, repository.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Repository has not been indexed",
            )
        matches = retrieve_code(
            request.query,
            user_id=current_user.id,
            repository_id=repository.id,
            limit=request.top_k,
        )
    except SemanticRetrievalError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic search is unavailable",
        ) from None

    results = []
    for match in matches:
        result = _to_search_result(match)
        if result is not None:
            results.append(result)

    return CodeSearchResponse(
        repository_id=repository.id,
        query=request.query,
        total_results=len(results),
        results=results,
    )


@router.post(
    "/{repository_id}/ask",
    response_model=CodeAskResponse,
)
def ask_repository_endpoint(
    repository_id: int,
    request: CodeAskRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CodeAskResponse:
    repository = (
        db.query(Repository)
        .filter(
            Repository.id == repository_id,
            Repository.user_id == current_user.id,
        )
        .first()
    )
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Repository not found",
        )

    try:
        if not has_indexed_chunks(current_user.id, repository.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Repository has not been indexed",
            )
    except SemanticRetrievalError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository vectors are unavailable",
        ) from None

    try:
        result = answer_repository_question(
            question=request.question,
            user_id=current_user.id,
            repository_id=repository.id,
            top_k=request.top_k,
        )
    except RAGRetrievalError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Repository context is unavailable",
        ) from None
    except LLMConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI question answering is not configured",
        ) from None
    except LLMProviderError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI answer service is temporarily unavailable",
        ) from None

    return CodeAskResponse(
        repository_id=repository.id,
        question=request.question,
        answer=result.answer,
        citations=result.citations,
        model=result.model,
    )
