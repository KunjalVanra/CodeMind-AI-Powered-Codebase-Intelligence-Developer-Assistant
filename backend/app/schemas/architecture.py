from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.dependency import DependencyGraphSummary


MetricStatus = Literal["available", "incomplete", "unavailable"]


class MetricAvailability(BaseModel):
    status: MetricStatus
    detail: str | None = None


class ArchitectureLanguageStatistics(BaseModel):
    files: int
    lines: int


class FileDependencyStatistics(BaseModel):
    file_path: str
    dependency_count: int
    internal_dependencies: int
    external_dependencies: int
    unresolved_imports: int


class FileImportStatistics(BaseModel):
    file_path: str
    import_count: int


class ComplexPythonFunction(BaseModel):
    file_path: str
    function_name: str
    start_line: int
    end_line: int
    cyclomatic_complexity: int = Field(
        description=(
            "Static cyclomatic complexity: 1 plus if/conditional expressions, "
            "loops, exception handlers, boolean operators beyond the first operand, "
            "comprehension loops and filters, and match cases beyond the first."
        )
    )


class ArchitectureAnalysisResponse(BaseModel):
    repository_id: int
    status: Literal["complete", "partial", "unavailable"]
    scan_analysis_id: int | None
    parse_analysis_id: int | None
    total_source_files: int | None
    total_lines_of_code: int | None
    languages: dict[str, ArchitectureLanguageStatistics]
    total_classes: int | None
    total_functions: int | None
    total_imports: int | None
    dependencies: DependencyGraphSummary | None
    dependency_metric: Literal["unique_import_edges"] = "unique_import_edges"
    high_dependency_threshold: int = Field(
        description="A file is listed as high-dependency at this many unique outgoing import edges."
    )
    high_import_threshold: int = Field(
        description="A file is listed as high-import at this many parsed import statements."
    )
    files_with_high_dependency_counts: list[FileDependencyStatistics]
    files_with_high_import_counts: list[FileImportStatistics]
    top_dependency_files: list[FileDependencyStatistics]
    complexity_metric: str | None
    most_complex_python_functions: list[ComplexPythonFunction]
    metrics_availability: dict[str, MetricAvailability]
    architecture_summary: list[str]
