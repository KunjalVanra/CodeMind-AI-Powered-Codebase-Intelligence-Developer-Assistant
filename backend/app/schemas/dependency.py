from typing import Literal

from pydantic import BaseModel


class DependencyGraphSummary(BaseModel):
    total_files: int
    nodes: int
    edges: int
    internal_dependencies: int
    external_dependencies: int
    unresolved_imports: int


class DependencyNode(BaseModel):
    id: str
    file_path: str
    language: str
    status: str


class DependencyEdge(BaseModel):
    source: str
    target: str | None
    dependency: str
    dependency_type: Literal["internal", "external", "unresolved"]
    relationship: str
    line: int | None


class DependencyGraphResponse(BaseModel):
    repository_id: int
    analysis_id: int
    status: str
    summary: DependencyGraphSummary
    nodes: list[DependencyNode]
    edges: list[DependencyEdge]
    unsupported_languages: list[str]
