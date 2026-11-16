import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './useAuth'

function AuthLoading() {
  return (
    <main className="auth-loading" aria-live="polite">
      <span className="loading-spinner" />
      <span>Checking your session…</span>
    </main>
  )
}

export function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') return <AuthLoading />
  if (status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <Outlet />
}

export function PublicOnlyRoute() {
  const { status } = useAuth()

  if (status === 'loading') return <AuthLoading />
  if (status === 'authenticated') return <Navigate to="/" replace />
  return <Outlet />
}
