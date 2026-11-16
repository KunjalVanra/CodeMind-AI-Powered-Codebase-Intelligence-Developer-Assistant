from datetime import datetime
from typing import Literal

from pydantic import BaseModel


SecuritySeverity = Literal[
    "critical",
    "high",
    "medium",
    "low",
    "informational",
]


class SecurityFinding(BaseModel):
    rule_id: str
    severity: SecuritySeverity
    title: str
    message: str
    file_path: str
    start_line: int
    end_line: int
    code_snippet: str | None = None
    remediation: str | None = None


class SecuritySeveritySummary(BaseModel):
    critical: int
    high: int
    medium: int
    low: int
    informational: int


class SecurityScanResponse(BaseModel):
    analysis_id: int
    repository_id: int
    status: str
    scanner: str
    scanned_files: int
    skipped_files: int
    total_findings: int
    summary: SecuritySeveritySummary
    findings: list[SecurityFinding]
    created_at: datetime
