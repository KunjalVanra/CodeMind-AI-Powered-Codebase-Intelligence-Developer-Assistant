from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


DocumentationType = Literal["readme", "module", "function", "class", "api"]


class DocumentationRequest(BaseModel):
    documentation_type: DocumentationType
    file_path: str | None = Field(default=None, max_length=4096)

    @field_validator("file_path")
    @classmethod
    def strip_file_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("file_path must not be empty")
        return normalized

    @model_validator(mode="after")
    def require_module_path(self) -> "DocumentationRequest":
        if self.documentation_type == "module" and self.file_path is None:
            raise ValueError("file_path is required for module documentation")
        return self


class DocumentationResponse(BaseModel):
    analysis_id: int
    repository_id: int
    documentation_type: DocumentationType
    file_path: str | None
    status: str
    documentation: str
    sufficient_information: bool
    notice: str | None
    limitations: list[str]
    source_file_count: int
    model: str | None
    created_at: datetime
