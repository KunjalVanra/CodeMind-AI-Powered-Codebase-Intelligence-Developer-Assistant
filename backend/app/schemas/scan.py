from datetime import datetime

from pydantic import BaseModel


class LanguageStatistics(BaseModel):
    files: int
    lines: int


class ScanResponse(BaseModel):
    analysis_id: int
    repository_id: int
    status: str
    total_files: int
    total_source_files: int
    total_lines: int
    languages: dict[str, LanguageStatistics]
    directories: list[str]
    important_files: list[str]
    created_at: datetime
