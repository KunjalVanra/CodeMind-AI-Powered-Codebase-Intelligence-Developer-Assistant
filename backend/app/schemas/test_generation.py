from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


__test__ = False


TestFramework = Literal["pytest", "unittest"]


class TestGenerationRequest(BaseModel):
    file_path: str = Field(min_length=1, max_length=4096)
    framework: TestFramework | None = None

    @field_validator("file_path")
    @classmethod
    def strip_file_path(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("file_path must not be empty")
        return normalized


class TestGenerationResponse(BaseModel):
    analysis_id: int
    repository_id: int
    status: str
    source_file_path: str
    language: str
    test_framework: TestFramework
    generated_test_code: str
    explanation: str
    sufficient_source_information: bool
    verified: Literal[False]
    verification_status: Literal["not_executed"]
    limitations: list[str]
    model: str | None
    created_at: datetime
