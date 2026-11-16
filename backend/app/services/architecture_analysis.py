from collections import Counter
from typing import Any

from app.schemas.architecture import (
    ArchitectureAnalysisResponse,
    ArchitectureLanguageStatistics,
    ComplexPythonFunction,
    FileDependencyStatistics,
    FileImportStatistics,
    MetricAvailability,
)
from app.services.dependency_graph import build_dependency_graph


HIGH_DEPENDENCY_THRESHOLD = 10
HIGH_IMPORT_THRESHOLD = 10
MAX_RANKED_FILES = 10
MAX_COMPLEX_FUNCTIONS = 10
COMPLEXITY_METRIC = "cyclomatic_complexity_v1"


def _is_count(value: object) -> bool:
    return type(value) is int and value >= 0


def _safe_file_path(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 4096:
        return None
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if (
        normalized.startswith("/")
        or ":" in parts[0]
        or any(part in {"", ".", ".."} for part in parts)
    ):
        return None
    return normalized


def _language_statistics(
    scan_summary: dict[str, Any] | None,
) -> tuple[
    int | None,
    int | None,
    dict[str, ArchitectureLanguageStatistics],
    MetricAvailability,
]:
    if scan_summary is None:
        return (
            None,
            None,
            {},
            MetricAvailability(
                status="unavailable",
                detail="No completed source scan is available.",
            ),
        )
    total_files = scan_summary.get("total_source_files")
    total_lines = scan_summary.get("total_lines")
    languages_data = scan_summary.get("languages")
    if (
        not _is_count(total_files)
        or not _is_count(total_lines)
        or not isinstance(languages_data, dict)
    ):
        return (
            total_files if _is_count(total_files) else None,
            total_lines if _is_count(total_lines) else None,
            {},
            MetricAvailability(
                status="incomplete",
                detail="Persisted scan summary is missing valid file, line, or language metrics.",
            ),
        )

    languages = {}
    incomplete = False
    for language, data in languages_data.items():
        if not isinstance(language, str) or not isinstance(data, dict):
            incomplete = True
            continue
        files = data.get("files")
        lines = data.get("lines")
        if not _is_count(files) or not _is_count(lines):
            incomplete = True
            continue
        languages[language] = ArchitectureLanguageStatistics(
            files=files,
            lines=lines,
        )
    return (
        total_files,
        total_lines,
        languages,
        MetricAvailability(
            status="incomplete" if incomplete else "available",
            detail=(
                "Some persisted language statistics were malformed."
                if incomplete
                else None
            ),
        ),
    )


def _parse_statistics(
    parse_summary: dict[str, Any] | None,
) -> tuple[
    int | None,
    int | None,
    int | None,
    list[dict[str, Any]],
    MetricAvailability,
]:
    if parse_summary is None:
        return (
            None,
            None,
            None,
            [],
            MetricAvailability(
                status="unavailable",
                detail="No completed parse analysis is available.",
            ),
        )

    languages_data = parse_summary.get("languages")
    if not isinstance(languages_data, dict):
        return (
            None,
            None,
            None,
            [],
            MetricAvailability(
                status="incomplete",
                detail="Persisted parse summary has no valid language data.",
            ),
        )

    classes = 0
    functions = 0
    imports = 0
    incomplete = False
    all_files: list[dict[str, Any]] = []
    for language, data in languages_data.items():
        if not isinstance(language, str) or not isinstance(data, dict):
            incomplete = True
            continue
        file_entries = data.get("files")
        if not isinstance(file_entries, list):
            incomplete = True
            file_entries = []
        language_files = 0
        language_functions = 0
        language_classes = 0
        language_imports = 0
        for file_entry in file_entries:
            if not isinstance(file_entry, dict):
                incomplete = True
                continue
            all_files.append({"language": language, **file_entry})
            if file_entry.get("status", "parsed") != "parsed":
                incomplete = True
                continue
            file_functions = file_entry.get("functions")
            file_classes = file_entry.get("classes")
            file_interfaces = file_entry.get("interfaces", [])
            file_imports = file_entry.get("imports")
            if not isinstance(file_functions, list):
                incomplete = True
                file_functions = []
            if not isinstance(file_classes, list):
                incomplete = True
                file_classes = []
            if not isinstance(file_interfaces, list):
                incomplete = True
                file_interfaces = []
            if not isinstance(file_imports, list):
                incomplete = True
                file_imports = []
            language_files += 1
            language_functions += len(file_functions)
            language_classes += len(file_classes) + len(file_interfaces)
            language_imports += len(file_imports)

        for metric, derived in (
            ("total_functions", language_functions),
            ("total_classes", language_classes),
            ("total_imports", language_imports),
        ):
            stored = data.get(metric)
            if stored is not None and not _is_count(stored):
                incomplete = True
            if metric == "total_functions":
                functions += derived
            elif metric == "total_classes":
                classes += derived
            else:
                imports += derived

        for metric in (
            "total_files",
            "successfully_parsed_files",
            "syntax_error_files",
            "unreadable_files",
            "parser_error_files",
        ):
            if metric in data and not _is_count(data[metric]):
                incomplete = True
        if (
            _is_count(data.get("total_files"))
            and _is_count(data.get("successfully_parsed_files"))
            and data["successfully_parsed_files"] < data["total_files"]
        ):
            incomplete = True

    legacy_files = parse_summary.get("files")
    if isinstance(legacy_files, list):
        existing_paths = {
            entry.get("path")
            for entry in all_files
            if isinstance(entry.get("path"), str)
        }
        for entry in legacy_files:
            if (
                isinstance(entry, dict)
                and isinstance(entry.get("path"), str)
                and entry["path"] not in existing_paths
            ):
                all_files.append({"language": "Python", **entry})
                existing_paths.add(entry["path"])

    return (
        classes,
        functions,
        imports,
        all_files,
        MetricAvailability(
            status="incomplete" if incomplete else "available",
            detail=(
                "Some source files failed parsing or persisted parser data was incomplete."
                if incomplete
                else None
            ),
        ),
    )


def _dependency_statistics(
    parse_summary: dict[str, Any] | None,
    parsed_files: list[dict[str, Any]],
    parse_availability: MetricAvailability,
) -> tuple[
    dict[str, int] | None,
    list[FileDependencyStatistics],
    list[FileDependencyStatistics],
    list[FileImportStatistics],
    MetricAvailability,
]:
    if parse_summary is None:
        return (
            None,
            [],
            [],
            [],
            MetricAvailability(
                status="unavailable",
                detail="Dependency metrics require a completed parse analysis.",
            ),
        )
    try:
        graph = build_dependency_graph(parse_summary)
        summary = graph["summary"]
        edges = graph["edges"]
        nodes = graph["nodes"]
    except (AttributeError, KeyError, TypeError, ValueError):
        return (
            None,
            [],
            [],
            [],
            MetricAvailability(
                status="incomplete",
                detail="Persisted parser data could not be used to build dependency metrics.",
            ),
        )

    counts: dict[str, Counter[str] | int] = {}
    node_paths = set()
    for node in nodes:
        path = _safe_file_path(node.get("file_path"))
        if path is not None:
            node_paths.add(path)
            counts[path] = Counter()
    for edge in edges:
        source = _safe_file_path(edge.get("source"))
        dependency_type = edge.get("dependency_type")
        if source not in counts or dependency_type not in {
            "internal",
            "external",
            "unresolved",
        }:
            continue
        current = counts[source]
        if isinstance(current, Counter):
            current[dependency_type] += 1

    ranked = []
    for path in sorted(node_paths):
        current = counts[path]
        if not isinstance(current, Counter):
            continue
        ranked.append(
            FileDependencyStatistics(
                file_path=path,
                dependency_count=sum(current.values()),
                internal_dependencies=current["internal"],
                external_dependencies=current["external"],
                unresolved_imports=current["unresolved"],
            )
        )
    ranked.sort(key=lambda item: (-item.dependency_count, item.file_path))
    high = [
        item
        for item in ranked
        if item.dependency_count >= HIGH_DEPENDENCY_THRESHOLD
    ]
    import_counts = []
    for file_entry in parsed_files:
        path = _safe_file_path(file_entry.get("path"))
        raw_imports = file_entry.get("imports")
        if (
            path is None
            or file_entry.get("status", "parsed") != "parsed"
            or not isinstance(raw_imports, list)
        ):
            continue
        import_counts.append(
            FileImportStatistics(file_path=path, import_count=len(raw_imports))
        )
    import_counts.sort(key=lambda item: (-item.import_count, item.file_path))
    high_imports = [
        item
        for item in import_counts
        if item.import_count >= HIGH_IMPORT_THRESHOLD
    ]
    availability = MetricAvailability(
        status=(
            "incomplete"
            if parse_availability.status != "available"
            else "available"
        ),
        detail=(
            "Dependency counts may omit files that failed parsing."
            if parse_availability.status != "available"
            else None
        ),
    )
    return (
        summary,
        ranked[:MAX_RANKED_FILES],
        high,
        high_imports,
        availability,
    )


def _complexity_metrics(
    parse_summary: dict[str, Any] | None,
    parsed_files: list[dict[str, Any]],
) -> tuple[str | None, list[ComplexPythonFunction], MetricAvailability]:
    if parse_summary is None:
        return (
            None,
            [],
            MetricAvailability(
                status="unavailable",
                detail="Complexity metrics require a completed parse analysis.",
            ),
        )
    if parse_summary.get("complexity_metric") != COMPLEXITY_METRIC:
        return (
            None,
            [],
            MetricAvailability(
                status="incomplete",
                detail=(
                    "This parse predates stored cyclomatic complexity metrics; "
                    "parse the repository again to calculate them."
                ),
            ),
        )

    functions = []
    incomplete = False
    for file_entry in parsed_files:
        if file_entry.get("language") != "Python":
            continue
        path = _safe_file_path(file_entry.get("path"))
        if file_entry.get("status") != "parsed":
            incomplete = True
            continue
        file_functions = file_entry.get("functions")
        if not isinstance(file_functions, list):
            incomplete = True
            continue
        for function in file_functions:
            if not isinstance(function, dict):
                incomplete = True
                continue
            complexity = function.get("cyclomatic_complexity")
            name = function.get("name")
            start_line = function.get("start_line")
            end_line = function.get("end_line")
            if (
                path is None
                or not isinstance(name, str)
                or not _is_count(complexity)
                or complexity < 1
                or not _is_count(start_line)
                or start_line < 1
                or not _is_count(end_line)
                or end_line < start_line
            ):
                incomplete = True
                continue
            functions.append(
                ComplexPythonFunction(
                    file_path=path,
                    function_name=name,
                    start_line=start_line,
                    end_line=end_line,
                    cyclomatic_complexity=complexity,
                )
            )
    functions.sort(
        key=lambda item: (
            -item.cyclomatic_complexity,
            item.file_path,
            item.start_line,
            item.function_name,
        )
    )
    return (
        COMPLEXITY_METRIC,
        functions[:MAX_COMPLEX_FUNCTIONS],
        MetricAvailability(
            status="incomplete" if incomplete else "available",
            detail=(
                "Some Python function complexity values were missing or malformed."
                if incomplete
                else None
            ),
        ),
    )


def build_architecture_analysis(
    *,
    repository_id: int,
    scan_analysis_id: int | None,
    scan_summary: dict[str, Any] | None,
    parse_analysis_id: int | None,
    parse_summary: dict[str, Any] | None,
) -> ArchitectureAnalysisResponse:
    source_files, lines, languages, scan_availability = _language_statistics(
        scan_summary
    )
    classes, functions, imports, parsed_files, parse_availability = (
        _parse_statistics(parse_summary)
    )
    dependency_data, top_files, high_files, import_files, dependency_availability = (
        _dependency_statistics(parse_summary, parsed_files, parse_availability)
    )
    complexity_metric, complex_functions, complexity_availability = (
        _complexity_metrics(parse_summary, parsed_files)
    )
    availability = {
        "source_metrics": scan_availability,
        "parser_metrics": parse_availability,
        "dependencies": dependency_availability,
        "complexity": complexity_availability,
    }
    all_available = all(
        item.status == "available" for item in availability.values()
    )
    no_analyses = scan_summary is None and parse_summary is None

    architecture_summary = []
    if source_files is not None and lines is not None:
        architecture_summary.append(
            f"The scanner found {source_files} source files and {lines} total lines."
        )
    if languages:
        dominant_language, dominant_statistics = min(
            languages.items(),
            key=lambda item: (-item[1].files, item[0]),
        )
        architecture_summary.append(
            f"{dominant_language} is the largest scanned language by file count "
            f"({dominant_statistics.files} files)."
        )
    if classes is not None and functions is not None:
        architecture_summary.append(
            f"The parser identified {classes} classes or interfaces and "
            f"{functions} functions."
        )
    if dependency_data is not None:
        architecture_summary.append(
            f"The dependency graph contains {dependency_data['internal_dependencies']} "
            f"internal file dependencies, {dependency_data['external_dependencies']} "
            f"external imports, and {dependency_data['unresolved_imports']} unresolved imports."
        )

    return ArchitectureAnalysisResponse(
        repository_id=repository_id,
        status=(
            "unavailable"
            if no_analyses
            else "complete"
            if all_available
            else "partial"
        ),
        scan_analysis_id=scan_analysis_id,
        parse_analysis_id=parse_analysis_id,
        total_source_files=source_files,
        total_lines_of_code=lines,
        languages=languages,
        total_classes=classes,
        total_functions=functions,
        total_imports=imports,
        dependencies=dependency_data,
        high_dependency_threshold=HIGH_DEPENDENCY_THRESHOLD,
        high_import_threshold=HIGH_IMPORT_THRESHOLD,
        files_with_high_dependency_counts=high_files,
        files_with_high_import_counts=import_files,
        top_dependency_files=top_files,
        complexity_metric=complexity_metric,
        most_complex_python_functions=complex_functions,
        metrics_availability=availability,
        architecture_summary=architecture_summary,
    )
