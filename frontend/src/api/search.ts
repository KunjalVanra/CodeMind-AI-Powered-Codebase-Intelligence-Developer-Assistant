import { apiRequest } from './client'

export interface CodeSearchRequest {
  query: string
  top_k: number
}

export interface CodeSearchResult {
  file_path: string
  language: string
  chunk_type: string
  symbol: string | null
  parent_type: string | null
  start_line: number
  end_line: number
  similarity: number
  snippet: string
}

export interface CodeSearchResponse {
  repository_id: number
  query: string
  total_results: number
  results: CodeSearchResult[]
}

export function searchRepository(
  repositoryId: number,
  request: CodeSearchRequest,
  token: string,
): Promise<CodeSearchResponse> {
  return apiRequest<CodeSearchResponse>(
    `/api/v1/repositories/${repositoryId}/search`,
    {
      method: 'POST',
      body: request,
      token,
    },
  )
}
