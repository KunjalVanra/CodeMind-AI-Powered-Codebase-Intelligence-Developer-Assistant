const ACCESS_TOKEN_KEY = 'codemind.accessToken'

export function readAccessToken(): string | null {
  try {
    return sessionStorage.getItem(ACCESS_TOKEN_KEY)
  } catch {
    return null
  }
}

export function storeAccessToken(token: string): void {
  try {
    sessionStorage.setItem(ACCESS_TOKEN_KEY, token)
  } catch {
    throw new Error('Unable to save this sign-in session in this browser.')
  }
}

export function clearAccessToken(): boolean {
  try {
    sessionStorage.removeItem(ACCESS_TOKEN_KEY)
    return true
  } catch {
    return false
  }
}
