import { apiRequest } from './client'

export interface ScanLanguageStatistics {
  files: number
  lines: number
}

export interface RepositoryScanResponse {
  analysis_id: number
  repository_id: number
  status: string
  total_files: number
  total_source_files: number
  total_lines: number
  languages: Record<string, ScanLanguageStatistics>
  directories: string[]
  important_files: string[]
  created_at: string
}

export interface ParseLanguageStatistics {
  total_files?: number
  successfully_parsed_files?: number
  syntax_error_files?: number
  unreadable_files?: number
  parser_error_files?: number
  total_classes?: number
  total_interfaces?: number
  total_functions?: number
  total_imports?: number
}

export interface RepositoryParseResponse {
  analysis_id: number
  repository_id: number
  status: string
  total_python_files: number
  successfully_parsed_files: number
  syntax_error_files: number
  unreadable_files: number
  total_classes: number
  total_functions: number
  total_imports: number
  files: Array<Record<string, unknown>>
  created_at: string
  languages: Record<string, ParseLanguageStatistics>
  chunk_count: number
  chunk_file_statuses: Record<string, number>
}

export interface RepositoryIndexingResponse {
  status: string
  analysis_id: number
  repository_id: number
  total_chunks: number
  indexed_chunks: number
  failed_chunks: number
  collection_name: string
}

export function scanRepository(
  repositoryId: number,
  token: string,
): Promise<RepositoryScanResponse> {
  return apiRequest<RepositoryScanResponse>(
    `/api/v1/repositories/${repositoryId}/scan`,
    { method: 'POST', token },
  )
}

export function parseRepository(
  repositoryId: number,
  token: string,
): Promise<RepositoryParseResponse> {
  return apiRequest<RepositoryParseResponse>(
    `/api/v1/repositories/${repositoryId}/parse`,
    { method: 'POST', token },
  )
}

export function indexRepository(
  repositoryId: number,
  token: string,
): Promise<RepositoryIndexingResponse> {
  return apiRequest<RepositoryIndexingResponse>(
    `/api/v1/repositories/${repositoryId}/index`,
    { method: 'POST', token },
  )
}
