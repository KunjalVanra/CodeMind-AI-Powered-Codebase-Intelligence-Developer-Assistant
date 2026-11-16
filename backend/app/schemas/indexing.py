from pydantic import BaseModel


class IndexingResponse(BaseModel):
    status: str
    analysis_id: int
    repository_id: int
    total_chunks: int
    indexed_chunks: int
    failed_chunks: int
    collection_name: str
