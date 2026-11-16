import { createContext } from 'react'
import type { Credentials, RegistrationDetails, User } from '../api/auth'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export type AuthContextValue = {
  user: User | null
  accessToken: string | null
  status: AuthStatus
  sessionError: string | null
  login: (credentials: Credentials) => Promise<void>
  register: (details: RegistrationDetails) => Promise<User>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
