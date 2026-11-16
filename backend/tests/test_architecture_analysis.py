from collections.abc import Generator
from itertools import count
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Analysis, Repository, User


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
repository_sequence = count()


def _parse_summary() -> dict:
    imports = [
        {"module": ".utils", "relative": True, "level": 1, "names": ["helper"]},
        {"module": ".missing", "relative": True, "level": 1, "names": ["missing"]},
    ] + [{"module": f"external_{index}"} for index in range(10)]
    return {
        "total_python_files": 2,
        "complexity_metric": "cyclomatic_complexity_v1",
        "languages": {
            "Python": {
                "total_files": 2,
                "successfully_parsed_files": 2,
                "syntax_error_files": 0,
                "unreadable_files": 0,
                "parser_error_files": 0,
                "total_classes": 1,
                "total_functions": 2,
                "total_imports": len(imports),
                "files": [
                    {
                        "path": "pkg/main.py",
                        "status": "parsed",
                        "classes": [
                            {"name": "Worker", "start_line": 20, "end_line": 24}
                        ],
                        "functions": [
                            {
                                "name": "calculate",
                                "start_line": 1,
                                "end_line": 12,
                                "cyclomatic_complexity": 5,
                            },
                            {
                                "name": "simple",
                                "start_line": 14,
                                "end_line": 15,
                                "cyclomatic_complexity": 1,
                            },
                        ],
                        "imports": imports,
                    },
                    {
                        "path": "pkg/utils.py",
                        "status": "parsed",
                        "classes": [],
                        "functions": [],
                        "imports": [],
                    },
                ],
            },
            "TypeScript": {
                "total_files": 2,
                "successfully_parsed_files": 2,
                "syntax_error_files": 0,
                "unreadable_files": 0,
                "parser_error_files": 0,
                "total_classes": 0,
                "total_functions": 1,
                "total_imports": 1,
                "files": [
                    {
                        "path": "src/a.ts",
                        "status": "parsed",
                        "classes": [],
                        "interfaces": [
                            {"name": "Service", "start_line": 1, "end_line": 3}
                        ],
                        "functions": [
                            {"name": "run", "start_line": 5, "end_line": 6}
                        ],
                        "imports": [{"module": "./b"}],
                    },
                    {
                        "path": "src/b.ts",
                        "status": "parsed",
                        "classes": [],
                        "interfaces": [],
                        "functions": [],
                        "imports": [],
                    },
                ],
            },
        },
        "files": [],
    }


def _scan_summary() -> dict:
    return {
        "total_files": 8,
        "total_source_files": 4,
        "total_lines": 120,
        "languages": {
            "Python": {"files": 2, "lines": 80},
            "TypeScript": {"files": 2, "lines": 40},
        },
    }


def _add_user_and_token(user_id: int = 1) -> dict[str, str]:
    with Session(test_engine) as db:
        user = User(
            id=user_id,
            full_name="Ada Lovelace",
            email=f"ada{user_id}@example.com",
            hashed_password="unused",
        )
        db.add(user)
        db.commit()
        token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _add_repository(user_id: int = 1) -> Repository:
    suffix = next(repository_sequence)
    with Session(test_engine) as db:
        repository = Repository(
            user_id=user_id,
            github_url=f"https://github.com/user/repo-{user_id}-{suffix}",
            name=f"repo-{user_id}-{suffix}",
            owner_name="user",
            default_branch="main",
            status="cloned",
        )
        db.add(repository)
        db.commit()
        db.refresh(repository)
        db.expunge(repository)
        return repository


def _add_analysis(repository: Repository, summary: object) -> int:
    with Session(test_engine) as db:
        analysis = Analysis(
            user_id=repository.user_id,
            repository_id=repository.id,
            status="completed",
            summary=summary if isinstance(summary, str) else json.dumps(summary),
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)
        return analysis.id


def _client() -> Generator[TestClient, None, None]:
    Base.metadata.create_all(bind=test_engine)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)


def test_architecture_endpoint_returns_grounded_metrics_and_complexity() -> None:
    client = next(_client())
    try:
        headers = _add_user_and_token()
        repository = _add_repository()
        scan_id = _add_analysis(repository, _scan_summary())
        parse_id = _add_analysis(repository, _parse_summary())

        response = client.get(
            f"/api/v1/repositories/{repository.id}/architecture",
            headers=headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "complete"
        assert body["scan_analysis_id"] == scan_id
        assert body["parse_analysis_id"] == parse_id
        assert body["total_source_files"] == 4
        assert body["total_lines_of_code"] == 120
        assert body["languages"]["Python"] == {"files": 2, "lines": 80}
        assert body["total_classes"] == 2
        assert body["total_functions"] == 3
        assert body["total_imports"] == 13
        assert body["dependencies"] == {
            "total_files": 4,
            "nodes": 4,
            "edges": 13,
            "internal_dependencies": 2,
            "external_dependencies": 10,
            "unresolved_imports": 1,
        }
        assert body["top_dependency_files"][0]["file_path"] == "pkg/main.py"
        assert body["top_dependency_files"][0]["dependency_count"] == 12
        assert body["files_with_high_dependency_counts"][0]["file_path"] == "pkg/main.py"
        assert body["files_with_high_import_counts"][0] == {
            "file_path": "pkg/main.py",
            "import_count": 12,
        }
        assert body["complexity_metric"] == "cyclomatic_complexity_v1"
        assert body["most_complex_python_functions"][0] == {
            "file_path": "pkg/main.py",
            "function_name": "calculate",
            "start_line": 1,
            "end_line": 12,
            "cyclomatic_complexity": 5,
        }
        assert body["metrics_availability"]["complexity"]["status"] == "available"
        assert "C:\\" not in response.text
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)


def test_architecture_endpoint_enforces_authentication_ownership_and_missing_repo() -> None:
    client = next(_client())
    try:
        assert client.get("/api/v1/repositories/1/architecture").status_code == 401
        headers = _add_user_and_token()
        assert client.get(
            "/api/v1/repositories/999/architecture",
            headers=headers,
        ).status_code == 404

        _add_user_and_token(user_id=2)
        foreign = _add_repository(user_id=2)
        _add_analysis(foreign, _parse_summary())
        response = client.get(
            f"/api/v1/repositories/{foreign.id}/architecture",
            headers=headers,
        )
        assert response.status_code == 404
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)


def test_architecture_endpoint_reports_unscanned_and_unparsed_repositories() -> None:
    client = next(_client())
    try:
        headers = _add_user_and_token()
        empty_repository = _add_repository()
        empty = client.get(
            f"/api/v1/repositories/{empty_repository.id}/architecture",
            headers=headers,
        )
        assert empty.status_code == 200
        assert empty.json()["status"] == "unavailable"
        assert empty.json()["total_source_files"] is None
        assert empty.json()["metrics_availability"]["source_metrics"]["status"] == "unavailable"

        scan_only_repository = _add_repository()
        _add_analysis(scan_only_repository, _scan_summary())
        scan_only = client.get(
            f"/api/v1/repositories/{scan_only_repository.id}/architecture",
            headers=headers,
        )
        assert scan_only.status_code == 200
        assert scan_only.json()["status"] == "partial"
        assert scan_only.json()["total_source_files"] == 4
        assert scan_only.json()["total_functions"] is None
        assert scan_only.json()["metrics_availability"]["parser_metrics"]["status"] == "unavailable"
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)


def test_architecture_endpoint_handles_empty_and_incomplete_parse_data() -> None:
    client = next(_client())
    try:
        headers = _add_user_and_token()
        repository = _add_repository()
        empty_scan = {
            "total_source_files": 0,
            "total_lines": 0,
            "languages": {},
        }
        empty_parse = {
            "total_python_files": 0,
            "complexity_metric": "cyclomatic_complexity_v1",
            "languages": {
                "Python": {
                    "total_files": 0,
                    "successfully_parsed_files": 0,
                    "syntax_error_files": 0,
                    "unreadable_files": 0,
                    "parser_error_files": 0,
                    "total_classes": 0,
                    "total_functions": 0,
                    "total_imports": 0,
                    "files": [],
                }
            },
            "files": [],
        }
        _add_analysis(repository, empty_scan)
        _add_analysis(repository, empty_parse)
        empty = client.get(
            f"/api/v1/repositories/{repository.id}/architecture",
            headers=headers,
        ).json()
        assert empty["status"] == "complete"
        assert empty["total_source_files"] == 0
        assert empty["total_lines_of_code"] == 0
        assert empty["dependencies"]["edges"] == 0
        assert empty["most_complex_python_functions"] == []

        incomplete_repository = _add_repository()
        incomplete_parse = {
            "total_python_files": 1,
            "complexity_metric": "cyclomatic_complexity_v1",
            "languages": {
                "Python": {
                    "total_files": 1,
                    "successfully_parsed_files": 0,
                    "syntax_error_files": 1,
                    "unreadable_files": 0,
                    "parser_error_files": 0,
                    "files": [
                        {"path": "broken.py", "status": "syntax_error"}
                    ],
                }
            },
            "files": [],
        }
        _add_analysis(incomplete_repository, _scan_summary())
        _add_analysis(incomplete_repository, incomplete_parse)
        incomplete = client.get(
            f"/api/v1/repositories/{incomplete_repository.id}/architecture",
            headers=headers,
        ).json()
        assert incomplete["status"] == "partial"
        assert incomplete["metrics_availability"]["parser_metrics"]["status"] == "incomplete"
        assert incomplete["metrics_availability"]["complexity"]["status"] == "incomplete"
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)


def test_architecture_endpoint_handles_legacy_complexity_and_malformed_analyses() -> None:
    client = next(_client())
    try:
        headers = _add_user_and_token()
        legacy_repository = _add_repository()
        _add_analysis(legacy_repository, _scan_summary())
        legacy_parse = _parse_summary()
        legacy_parse.pop("complexity_metric")
        for language in legacy_parse["languages"].values():
            for file_entry in language["files"]:
                for function in file_entry.get("functions", []):
                    function.pop("cyclomatic_complexity", None)
        _add_analysis(legacy_repository, legacy_parse)
        legacy = client.get(
            f"/api/v1/repositories/{legacy_repository.id}/architecture",
            headers=headers,
        ).json()
        assert legacy["status"] == "partial"
        assert legacy["most_complex_python_functions"] == []
        assert legacy["metrics_availability"]["complexity"]["status"] == "incomplete"
        assert "parse the repository again" in legacy["metrics_availability"]["complexity"]["detail"]

        malformed_repository = _add_repository()
        _add_analysis(malformed_repository, "{malformed")
        malformed = client.get(
            f"/api/v1/repositories/{malformed_repository.id}/architecture",
            headers=headers,
        ).json()
        assert malformed["status"] == "unavailable"
        assert malformed["scan_analysis_id"] is None
        assert malformed["parse_analysis_id"] is None
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
