import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { ApiError } from '../api/client'
import {
  fetchCurrentUser,
  loginUser,
  registerUser,
  type Credentials,
  type RegistrationDetails,
  type User,
} from '../api/auth'
import {
  clearAccessToken,
  readAccessToken,
  storeAccessToken,
} from './tokenStorage'
import { AuthContext, type AuthStatus } from './AuthContext'

const pendingUserRequests = new Map<string, Promise<User>>()

function fetchCurrentUserOnce(token: string): Promise<User> {
  const existingRequest = pendingUserRequests.get(token)
  if (existingRequest) return existingRequest

  const request = fetchCurrentUser(token).finally(() => {
    if (pendingUserRequests.get(token) === request) {
      pendingUserRequests.delete(token)
    }
  })
  pendingUserRequests.set(token, request)
  return request
}

type AuthProviderProps = {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [token, setToken] = useState<string | null>(readAccessToken)
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthStatus>(() =>
    readAccessToken() ? 'loading' : 'unauthenticated',
  )
  const [sessionError, setSessionError] = useState<string | null>(null)
  const validatedToken = useRef<string | null>(null)
  const sessionRequestVersion = useRef(0)

  useEffect(() => {
    const requestVersion = ++sessionRequestVersion.current
    if (token && validatedToken.current !== token) {
      void fetchCurrentUserOnce(token)
        .then((currentUser) => {
          if (sessionRequestVersion.current !== requestVersion) return
          validatedToken.current = token
          setUser(currentUser)
          setStatus('authenticated')
        })
        .catch((error: unknown) => {
          if (sessionRequestVersion.current !== requestVersion) return
          if (error instanceof ApiError && error.status === 401) {
            const cleared = clearAccessToken()
            validatedToken.current = null
            setToken(null)
            setUser(null)
            setStatus('unauthenticated')
            if (!cleared) {
              setSessionError(
                'The expired session could not be cleared from this browser.',
              )
            }
            return
          }
          setUser(null)
          setStatus('unauthenticated')
          setSessionError(
            'Your saved session could not be verified. Please sign in again.',
          )
        })
    }

    return () => {
      if (sessionRequestVersion.current === requestVersion) {
        sessionRequestVersion.current += 1
      }
    }
  }, [token])

  const login = useCallback(async (credentials: Credentials) => {
    const result = await loginUser(credentials)
    if (result.token_type.toLowerCase() !== 'bearer') {
      throw new Error('The server returned an unsupported sign-in token.')
    }
    storeAccessToken(result.access_token)
    validatedToken.current = result.access_token
    setToken(result.access_token)
    setUser(result.user)
    setSessionError(null)
    setStatus('authenticated')
  }, [])

  const register = useCallback(
    (details: RegistrationDetails) => registerUser(details),
    [],
  )

  const logout = useCallback(() => {
    const cleared = clearAccessToken()
    sessionRequestVersion.current += 1
    validatedToken.current = null
    setToken(null)
    setUser(null)
    setSessionError(
      cleared
        ? null
        : 'Signed out for this tab, but the browser could not clear the saved session.',
    )
    setStatus('unauthenticated')
  }, [])

  const value = useMemo(
    () => ({ user, accessToken: token, status, sessionError, login, register, logout }),
    [user, token, status, sessionError, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
