from collections.abc import Generator
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import repositories as repository_api
from app.api.deps import get_db
from app.core.config import settings
from app.core.database import Base
from app.core.security import create_access_token
from app.main import app
from app.models import Analysis, Repository, User
from app.services import security_analysis


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
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


def _create_user(user_id: int = 1) -> dict[str, str]:
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


def _create_repository(user_id: int = 1, status: str = "cloned") -> Repository:
    with Session(test_engine) as db:
        repository = Repository(
            user_id=user_id,
            github_url=f"https://github.com/user/repo-{user_id}",
            name=f"repo-{user_id}",
            owner_name="user",
            default_branch="main",
            status=status,
        )
        db.add(repository)
        db.commit()
        db.refresh(repository)
        db.expunge(repository)
        return repository


def _sample_result() -> dict:
    return {
        "scanner": "Semgrep",
        "scanned_files": 2,
        "skipped_files": 1,
        "total_findings": 1,
        "summary": {
            "critical": 0,
            "high": 1,
            "medium": 0,
            "low": 0,
            "informational": 0,
        },
        "findings": [
            {
                "rule_id": "python.security.test-rule",
                "severity": "high",
                "title": "Unsafe shell invocation",
                "message": "Avoid passing untrusted data to a shell.",
                "file_path": "app.py",
                "start_line": 8,
                "end_line": 8,
                "code_snippet": "subprocess.run(command, shell=True)",
                "remediation": "Invoke the executable with an argument list.",
            },
        ],
    }


def test_security_scan_endpoint_persists_findings(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _create_user()
    repository = _create_repository()
    monkeypatch.setattr(
        repository_api,
        "scan_repository_security",
        lambda user_id, repository_id: _sample_result(),
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/security-scan",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository_id"] == repository.id
    assert body["status"] == "completed"
    assert body["scanner"] == "Semgrep"
    assert body["summary"]["high"] == 1
    assert body["findings"][0]["rule_id"] == "python.security.test-rule"
    assert body["findings"][0]["file_path"] == "app.py"
    assert body["findings"][0]["remediation"]

    with Session(test_engine) as db:
        analysis = db.get(Analysis, body["analysis_id"])
        stored = json.loads(analysis.summary)
        assert stored["analysis_type"] == "security_scan"
        assert stored["findings"] == body["findings"]
        assert analysis.total_files == 2


def test_security_scan_endpoint_handles_auth_owner_and_clone_requirements(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert client.post("/api/v1/repositories/1/security-scan").status_code == 401
    headers = _create_user()
    assert client.post(
        "/api/v1/repositories/999/security-scan",
        headers=headers,
    ).status_code == 404

    other_repository = _create_repository(user_id=2)
    assert client.post(
        f"/api/v1/repositories/{other_repository.id}/security-scan",
        headers=headers,
    ).status_code == 404

    connected_repository = _create_repository(status="connected")
    response = client.post(
        f"/api/v1/repositories/{connected_repository.id}/security-scan",
        headers=headers,
    )
    assert response.status_code == 409


def test_security_scan_endpoint_reports_scanner_unavailable_without_saving(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _create_user()
    repository = _create_repository()

    def unavailable(user_id: int, repository_id: int) -> dict:
        raise security_analysis.SecurityScannerUnavailable

    monkeypatch.setattr(
        repository_api,
        "scan_repository_security",
        unavailable,
    )
    response = client.post(
        f"/api/v1/repositories/{repository.id}/security-scan",
        headers=headers,
    )

    assert response.status_code == 503
    assert "Semgrep is not installed" in response.json()["detail"]
    with Session(test_engine) as db:
        assert db.query(Analysis).count() == 0


def test_security_scan_endpoint_persists_empty_results(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = _create_user()
    repository = _create_repository()
    empty_result = {
        **_sample_result(),
        "total_findings": 0,
        "findings": [],
        "summary": {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "informational": 0,
        },
    }
    monkeypatch.setattr(
        repository_api,
        "scan_repository_security",
        lambda user_id, repository_id: empty_result,
    )

    response = client.post(
        f"/api/v1/repositories/{repository.id}/security-scan",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["total_findings"] == 0
    assert response.json()["findings"] == []


def test_security_service_stages_safe_files_and_normalizes_semgrep_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "1" / "2"
    (repository_root / ".git").mkdir(parents=True)
    (repository_root / "src").mkdir()
    (repository_root / "src" / "main.py").write_text(
        "subprocess.run(command, shell=True)\n",
        encoding="utf-8",
    )
    (repository_root / "binary.dat").write_bytes(b"\x00binary")
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(security_analysis.shutil, "which", lambda _: "semgrep")
    scanner_output = {
        "results": [
            {
                "check_id": "python.security.test-rule",
                "path": "src/main.py",
                "start": {"line": 1},
                "end": {"line": 1},
                "extra": {
                    "severity": "WARNING",
                    "message": "Avoid passing untrusted data to a shell.",
                    "lines": "subprocess.run(command, shell=True)",
                    "metadata": {
                        "shortDescription": "Unsafe shell invocation",
                        "remediation": "Use an argument list.",
                    },
                },
            },
        ],
        "errors": [],
    }
    called = {}

    def run_scanner(args, **kwargs):
        called["args"] = args
        called["cwd"] = kwargs["cwd"]
        staged_file = Path(kwargs["cwd"]) / "src" / "main.py"
        assert staged_file.is_file()
        assert (Path(kwargs["cwd"]) / "binary.dat").exists() is False
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(scanner_output),
            stderr="",
        )

    monkeypatch.setattr(security_analysis.subprocess, "run", run_scanner)

    result = security_analysis.scan_repository_security(1, 2)

    assert result["scanned_files"] == 1
    assert result["skipped_files"] == 1
    assert result["summary"]["medium"] == 1
    assert result["findings"][0]["title"] == "Unsafe shell invocation"
    assert result["findings"][0]["file_path"] == "src/main.py"
    assert result["findings"][0]["remediation"] == "Use an argument list."
    assert str(repository_root) not in str(result)
    assert called["args"][1:3] == ["scan", "--config"]
    assert Path(called["cwd"]) != repository_root


def test_security_service_gracefully_reports_missing_semgrep(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "1" / "2"
    (repository_root / ".git").mkdir(parents=True)
    monkeypatch.setattr(settings, "CODEMIND_STORAGE_DIR", tmp_path)
    monkeypatch.setattr(security_analysis.shutil, "which", lambda _: None)

    with pytest.raises(security_analysis.SecurityScannerUnavailable):
        security_analysis.scan_repository_security(1, 2)
