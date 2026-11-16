from datetime import datetime

from pydantic import BaseModel, Field


class ParseResponse(BaseModel):
    analysis_id: int
    repository_id: int
    status: str
    total_python_files: int
    successfully_parsed_files: int
    syntax_error_files: int
    unreadable_files: int
    total_classes: int
    total_functions: int
    total_imports: int
    files: list[dict]
    created_at: datetime
    languages: dict[str, dict] = Field(default_factory=dict)
    chunk_count: int = 0
    chunk_file_statuses: dict[str, int] = Field(default_factory=dict)
