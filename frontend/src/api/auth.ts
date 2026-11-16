import { apiRequest } from './client'

export interface User {
  id: number
  full_name: string
  email: string
  is_active: boolean
}

export interface Credentials {
  email: string
  password: string
}

export interface RegistrationDetails extends Credentials {
  full_name: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: User
}

export function registerUser(details: RegistrationDetails): Promise<User> {
  return apiRequest<User>('/api/v1/auth/register', {
    method: 'POST',
    body: details,
  })
}

export function loginUser(credentials: Credentials): Promise<LoginResponse> {
  return apiRequest<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: credentials,
  })
}

export function fetchCurrentUser(token: string): Promise<User> {
  return apiRequest<User>('/api/v1/auth/me', { token })
}
