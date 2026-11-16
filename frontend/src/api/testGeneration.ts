import { apiRequest } from './client'

export type TestFramework = 'unittest' | 'pytest'

export interface TestGenerationRequest {
  file_path: string
  framework?: TestFramework
}

export interface TestGenerationResponse {
  analysis_id: number
  repository_id: number
  status: string
  source_file_path: string
  language: string
  test_framework: TestFramework
  generated_test_code: string
  explanation: string
  sufficient_source_information: boolean
  verified: false
  verification_status: 'not_executed'
  limitations: string[]
  model: string | null
  created_at: string
}

export function generateRepositoryTests(
  repositoryId: number,
  request: TestGenerationRequest,
  token: string,
): Promise<TestGenerationResponse> {
  return apiRequest<TestGenerationResponse>(
    `/api/v1/repositories/${repositoryId}/generate-tests`,
    {
      method: 'POST',
      body: request,
      token,
    },
  )
}
