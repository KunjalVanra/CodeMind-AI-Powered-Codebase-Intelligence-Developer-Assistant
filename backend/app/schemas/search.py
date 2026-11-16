from pydantic import BaseModel, Field, field_validator


class CodeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Query must not be empty")
        return normalized


class CodeSearchResult(BaseModel):
    file_path: str
    language: str
    chunk_type: str
    symbol: str | None
    parent_type: str | None
    start_line: int
    end_line: int
    similarity: float
    snippet: str


class CodeSearchResponse(BaseModel):
    repository_id: int
    query: str
    total_results: int
    results: list[CodeSearchResult]
