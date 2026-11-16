import { apiRequest } from './client'

export interface CodeAskRequest {
  question: string
  top_k: number
}

export interface CodeCitation {
  reference_id: string
  file_path: string
  language: string
  symbol: string | null
  start_line: number
  end_line: number
}

export interface CodeAskResponse {
  repository_id: number
  question: string
  answer: string
  citations: CodeCitation[]
  model: string | null
}

export function askRepository(
  repositoryId: number,
  request: CodeAskRequest,
  token: string,
): Promise<CodeAskResponse> {
  return apiRequest<CodeAskResponse>(
    `/api/v1/repositories/${repositoryId}/ask`,
    {
      method: 'POST',
      body: request,
      token,
    },
  )
}
