import { useState, type FormEvent } from 'react'
import { ArrowRight, Eye, EyeOff, Sparkles } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/useAuth'

type LoginLocationState = {
  from?: { pathname?: string }
  registered?: boolean
}

function LoginPage() {
  const { login, sessionError } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const locationState = location.state as LoginLocationState | null
  const destination = locationState?.from?.pathname ?? '/'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login({ email: email.trim(), password })
      navigate(destination, { replace: true })
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Unable to sign in. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-orb auth-orb-one" />
      <div className="auth-orb auth-orb-two" />
      <Link className="auth-brand" to="/" aria-label="CodeMind">
        <span className="brand-mark"><Sparkles size={20} /></span>
        <span><strong>CodeMind</strong><small>Codebase Intelligence</small></span>
      </Link>

      <section className="auth-card">
        <div className="auth-card-heading">
          <span className="auth-kicker">Welcome back</span>
          <h1>Sign in to CodeMind</h1>
          <p>Continue exploring your codebase with confidence.</p>
        </div>

        {locationState?.registered && (
          <div className="form-message form-success" role="status">
            Account created. Sign in to continue.
          </div>
        )}
        {sessionError && (
          <div className="form-message form-error" role="alert">{sessionError}</div>
        )}
        {error && <div className="form-message form-error" role="alert">{error}</div>}

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span>Email address</span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              placeholder="you@company.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>

          <label className="form-field">
            <span>Password</span>
            <span className="password-input-wrap">
              <input
                type={showPassword ? 'text' : 'password'}
                name="password"
                autoComplete="current-password"
                placeholder="Enter your password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                minLength={8}
              />
              <button
                className="password-toggle"
                type="button"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                onClick={() => setShowPassword((visible) => !visible)}
              >
                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
              </button>
            </span>
          </label>

          <button className="auth-submit" type="submit" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
            {!submitting && <ArrowRight size={16} />}
          </button>
        </form>

        <p className="auth-switch">
          New to CodeMind? <Link to="/register">Create an account</Link>
        </p>
      </section>
      <p className="auth-footer">Built for developers who want to understand more.</p>
    </main>
  )
}

export default LoginPage
