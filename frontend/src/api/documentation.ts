import { apiRequest } from './client'

export type DocumentationType =
  | 'readme'
  | 'module'
  | 'function'
  | 'class'
  | 'api'

export interface DocumentationRequest {
  documentation_type: DocumentationType
  file_path?: string
}

export interface DocumentationResponse {
  analysis_id: number
  repository_id: number
  documentation_type: DocumentationType
  file_path: string | null
  status: string
  documentation: string
  sufficient_information: boolean
  notice: string | null
  limitations: string[]
  source_file_count: number
  model: string | null
  created_at: string
}

export function generateRepositoryDocumentation(
  repositoryId: number,
  request: DocumentationRequest,
  token: string,
): Promise<DocumentationResponse> {
  return apiRequest<DocumentationResponse>(
    `/api/v1/repositories/${repositoryId}/documentation`,
    {
      method: 'POST',
      body: request,
      token,
    },
  )
}
