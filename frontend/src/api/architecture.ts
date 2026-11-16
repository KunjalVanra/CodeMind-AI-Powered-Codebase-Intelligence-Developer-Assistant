import type { DependencyGraphSummary } from './dependencies'
import { apiRequest } from './client'

export type MetricStatus = 'available' | 'incomplete' | 'unavailable'

export interface MetricAvailability {
  status: MetricStatus
  detail: string | null
}

export interface ArchitectureLanguageStatistics {
  files: number
  lines: number
}

export interface FileDependencyStatistics {
  file_path: string
  dependency_count: number
  internal_dependencies: number
  external_dependencies: number
  unresolved_imports: number
}

export interface FileImportStatistics {
  file_path: string
  import_count: number
}

export interface ComplexPythonFunction {
  file_path: string
  function_name: string
  start_line: number
  end_line: number
  cyclomatic_complexity: number
}

export interface ArchitectureAnalysisResponse {
  repository_id: number
  status: 'complete' | 'partial' | 'unavailable'
  scan_analysis_id: number | null
  parse_analysis_id: number | null
  total_source_files: number | null
  total_lines_of_code: number | null
  languages: Record<string, ArchitectureLanguageStatistics>
  total_classes: number | null
  total_functions: number | null
  total_imports: number | null
  dependencies: DependencyGraphSummary | null
  dependency_metric: 'unique_import_edges'
  high_dependency_threshold: number
  high_import_threshold: number
  files_with_high_dependency_counts: FileDependencyStatistics[]
  files_with_high_import_counts: FileImportStatistics[]
  top_dependency_files: FileDependencyStatistics[]
  complexity_metric: string | null
  most_complex_python_functions: ComplexPythonFunction[]
  metrics_availability: Record<string, MetricAvailability>
  architecture_summary: string[]
}

export function getRepositoryArchitecture(
  repositoryId: number,
  token: string,
): Promise<ArchitectureAnalysisResponse> {
  return apiRequest<ArchitectureAnalysisResponse>(
    `/api/v1/repositories/${repositoryId}/architecture`,
    { token },
  )
}
