import { apiRequest } from './client'

export interface Repository {
  id: number
  user_id: number
  github_url: string
  name: string
  owner_name: string
  default_branch: string | null
  status: string | null
  created_at: string
}

export function listRepositories(token: string): Promise<Repository[]> {
  return apiRequest<Repository[]>('/api/v1/repositories', { token })
}

export function connectRepository(
  githubUrl: string,
  token: string,
): Promise<Repository> {
  return apiRequest<Repository>('/api/v1/repositories', {
    method: 'POST',
    body: { github_url: githubUrl },
    token,
  })
}

export function getRepository(
  repositoryId: number,
  token: string,
): Promise<Repository> {
  return apiRequest<Repository>(`/api/v1/repositories/${repositoryId}`, { token })
}

export function deleteRepository(
  repositoryId: number,
  token: string,
): Promise<void> {
  return apiRequest<void>(`/api/v1/repositories/${repositoryId}`, {
    method: 'DELETE',
    token,
  })
}

export function cloneRepository(
  repositoryId: number,
  token: string,
): Promise<Repository> {
  return apiRequest<Repository>(
    `/api/v1/repositories/${repositoryId}/clone`,
    {
      method: 'POST',
      token,
    },
  )
}
