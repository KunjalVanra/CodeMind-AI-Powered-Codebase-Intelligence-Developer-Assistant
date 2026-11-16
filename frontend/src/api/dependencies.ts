import { apiRequest } from './client'

export type DependencyType = 'internal' | 'external' | 'unresolved'

export interface DependencyGraphSummary {
  total_files: number
  nodes: number
  edges: number
  internal_dependencies: number
  external_dependencies: number
  unresolved_imports: number
}

export interface DependencyNode {
  id: string
  file_path: string
  language: string
  status: string
}

export interface DependencyEdge {
  source: string
  target: string | null
  dependency: string
  dependency_type: DependencyType
  relationship: string
  line: number | null
}

export interface DependencyGraphResponse {
  repository_id: number
  analysis_id: number
  status: string
  summary: DependencyGraphSummary
  nodes: DependencyNode[]
  edges: DependencyEdge[]
  unsupported_languages: string[]
}

export function getRepositoryDependencies(
  repositoryId: number,
  token: string,
): Promise<DependencyGraphResponse> {
  return apiRequest<DependencyGraphResponse>(
    `/api/v1/repositories/${repositoryId}/dependencies`,
    { token },
  )
}
