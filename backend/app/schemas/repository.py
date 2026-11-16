from datetime import datetime

from pydantic import BaseModel, ConfigDict, HttpUrl


class RepositoryCreate(BaseModel):
    github_url: HttpUrl


class RepositoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    github_url: HttpUrl
    name: str
    owner_name: str
    default_branch: str | None
    status: str | None
    created_at: datetime
