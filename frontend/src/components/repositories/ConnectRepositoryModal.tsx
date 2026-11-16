import { useState, type FormEvent } from 'react'
import { AlertCircle, GitBranch, X } from 'lucide-react'

type ConnectRepositoryModalProps = {
  isConnecting: boolean
  error: string | null
  onClose: () => void
  onConnect: (githubUrl: string) => void
}

function isValidGitHubUrl(value: string): boolean {
  try {
    const url = new URL(value)
    const segments = url.pathname.split('/').filter(Boolean)
    return (
      url.protocol === 'https:' &&
      ['github.com', 'www.github.com'].includes(url.hostname.toLowerCase()) &&
      segments.length === 2 &&
      !url.search &&
      !url.hash
    )
  } catch {
    return false
  }
}

function ConnectRepositoryModal({
  isConnecting,
  error,
  onClose,
  onConnect,
}: ConnectRepositoryModalProps) {
  const [githubUrl, setGithubUrl] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmedUrl = githubUrl.trim()
    if (!isValidGitHubUrl(trimmedUrl)) {
      setValidationError(
        'Enter a public repository URL like https://github.com/owner/repository.',
      )
      return
    }
    setValidationError(null)
    onConnect(trimmedUrl)
  }

  return (
    <div
      className="repository-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isConnecting) onClose()
      }}
    >
      <section
        className="repository-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-repository-title"
      >
        <div className="repository-modal-heading">
          <span className="repository-modal-icon"><GitBranch size={19} /></span>
          <button
            className="repository-modal-close"
            type="button"
            aria-label="Close dialog"
            onClick={onClose}
            disabled={isConnecting}
          >
            <X size={18} />
          </button>
          <div>
            <h2 id="connect-repository-title">Connect a repository</h2>
            <p>Add a public GitHub repository to your workspace.</p>
          </div>
        </div>

        <form className="repository-modal-form" onSubmit={handleSubmit}>
          <label className="form-field" htmlFor="github-repository-url">
            <span>GitHub repository URL</span>
            <input
              id="github-repository-url"
              name="github_url"
              type="url"
              autoComplete="url"
              placeholder="https://github.com/owner/repository"
              value={githubUrl}
              onChange={(event) => {
                setGithubUrl(event.target.value)
                setValidationError(null)
              }}
              required
              disabled={isConnecting}
            />
          </label>

          {(validationError || error) && (
            <div className="repository-form-error" role="alert">
              <AlertCircle size={15} />
              <span>{validationError ?? error}</span>
            </div>
          )}

          <div className="repository-modal-actions">
            <button
              className="repository-button repository-button-quiet"
              type="button"
              onClick={onClose}
              disabled={isConnecting}
            >
              Cancel
            </button>
            <button
              className="repository-button repository-button-primary"
              type="submit"
              disabled={isConnecting}
            >
              {isConnecting ? (
                <>
                  <span className="button-spinner" />
                  Connecting…
                </>
              ) : (
                'Connect repository'
              )}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}

export default ConnectRepositoryModal
