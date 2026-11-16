from pydantic import BaseModel, Field, field_validator


class CodeAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be empty")
        return normalized


class CodeCitation(BaseModel):
    reference_id: str
    file_path: str
    language: str
    symbol: str | None
    start_line: int
    end_line: int


class CodeAskResponse(BaseModel):
    repository_id: int
    question: str
    answer: str
    citations: list[CodeCitation]
    model: str | None
