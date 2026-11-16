import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  GitBranch,
  LoaderCircle,
  Plus,
  RefreshCw,
} from 'lucide-react'
import {
  ApiError,
  ApiNetworkError,
} from '../api/client'
import {
  cloneRepository,
  connectRepository,
  deleteRepository,
  listRepositories,
  type Repository,
} from '../api/repositories'
import { useAuth } from '../auth/useAuth'
import ConfirmDeleteModal from '../components/repositories/ConfirmDeleteModal'
import ConnectRepositoryModal from '../components/repositories/ConnectRepositoryModal'
import RepositoryCard from '../components/repositories/RepositoryCard'

type Feedback = {
  kind: 'success' | 'error'
  message: string
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof ApiNetworkError) {
    return error.message
  }
  return 'Something went wrong. Please try again.'
}

function RepositoriesPage() {
  const { accessToken } = useAuth()
  const [repositories, setRepositories] = useState<Repository[] | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isConnectOpen, setIsConnectOpen] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [cloningIds, setCloningIds] = useState<Set<number>>(() => new Set())
  const [deleteCandidate, setDeleteCandidate] = useState<Repository | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const cloneRequests = useRef(new Set<number>())
  const initialLoadToken = useRef<string | null>(null)

  const loadRepositories = useCallback(async () => {
    if (!accessToken) return
    setIsLoading(true)
    setLoadError(null)
    try {
      const result = await listRepositories(accessToken)
      setRepositories(result)
    } catch (error) {
      setLoadError(errorMessage(error))
    } finally {
      setIsLoading(false)
    }
  }, [accessToken])

  useEffect(() => {
    if (!accessToken || initialLoadToken.current === accessToken) return
    initialLoadToken.current = accessToken
    void loadRepositories()
  }, [accessToken, loadRepositories])

  async function handleConnect(githubUrl: string) {
    if (!accessToken || isConnecting) return
    setIsConnecting(true)
    setConnectError(null)
    setFeedback(null)
    try {
      const repository = await connectRepository(githubUrl, accessToken)
      setIsConnectOpen(false)
      setFeedback({
        kind: 'success',
        message: `${repository.owner_name}/${repository.name} connected.`,
      })
      await loadRepositories()
    } catch (error) {
      setConnectError(
        error instanceof ApiError && error.status === 409
          ? error.message
          : errorMessage(error),
      )
    } finally {
      setIsConnecting(false)
    }
  }

  async function handleClone(repository: Repository) {
    if (!accessToken || cloneRequests.current.has(repository.id)) return
    cloneRequests.current.add(repository.id)
    setCloningIds((current) => new Set(current).add(repository.id))
    setFeedback(null)
    try {
      const updatedRepository = await cloneRepository(repository.id, accessToken)
      setRepositories((current) =>
        (current ?? []).map((item) =>
          item.id === updatedRepository.id ? updatedRepository : item,
        ),
      )
      setFeedback({
        kind: 'success',
        message:
          updatedRepository.status === 'cloned'
            ? `${updatedRepository.name} is ready for analysis.`
            : `${updatedRepository.name} status updated to ${updatedRepository.status ?? 'unknown'}.`,
      })
    } catch (error) {
      setFeedback({ kind: 'error', message: errorMessage(error) })
    } finally {
      cloneRequests.current.delete(repository.id)
      setCloningIds((current) => {
        const next = new Set(current)
        next.delete(repository.id)
        return next
      })
    }
  }

  async function handleDelete() {
    if (!accessToken || !deleteCandidate || deletingId !== null) return
    const repository = deleteCandidate
    setDeletingId(repository.id)
    setDeleteError(null)
    try {
      await deleteRepository(repository.id, accessToken)
      setRepositories((current) =>
        (current ?? []).filter((item) => item.id !== repository.id),
      )
      setDeleteCandidate(null)
      setFeedback({
        kind: 'success',
        message: `${repository.name} was removed from your repositories.`,
      })
    } catch (error) {
      setDeleteError(errorMessage(error))
    } finally {
      setDeletingId(null)
    }
  }

  function openConnectDialog() {
    setConnectError(null)
    setIsConnectOpen(true)
  }

  return (
    <div className="repositories-page page-enter">
      <section className="repositories-heading">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" />Workspace</div>
          <h1>Repositories</h1>
          <p>Connect and manage the public GitHub codebases you want to explore.</p>
        </div>
        <button
          className="repository-button repository-button-primary connect-repository-button"
          type="button"
          onClick={openConnectDialog}
        >
          <Plus size={16} />
          Connect repository
        </button>
      </section>

      <div className="repository-list-toolbar">
        <div className="repository-list-title">
          <h2>Your repositories</h2>
          {!isLoading && repositories && (
            <span className="repository-count">{repositories.length}</span>
          )}
        </div>
        <button
          className="repository-refresh-button"
          type="button"
          onClick={() => void loadRepositories()}
          disabled={isLoading}
        >
          <RefreshCw size={14} className={isLoading ? 'spin-icon' : ''} />
          Refresh
        </button>
      </div>

      {feedback && (
        <div
          className={`repository-feedback repository-feedback-${feedback.kind}`}
          role={feedback.kind === 'error' ? 'alert' : 'status'}
        >
          <AlertCircle size={16} />
          <span>{feedback.message}</span>
          <button
            type="button"
            className="feedback-dismiss"
            aria-label="Dismiss message"
            onClick={() => setFeedback(null)}
          >
            ×
          </button>
        </div>
      )}

      {loadError && (
        <div className="repository-load-error" role="alert">
          <AlertCircle size={18} />
          <div>
            <strong>Could not load repositories</strong>
            <p>{loadError}</p>
          </div>
          <button
            className="repository-button repository-button-quiet"
            type="button"
            onClick={() => void loadRepositories()}
            disabled={isLoading}
          >
            Retry
          </button>
        </div>
      )}

      {isLoading && repositories === null ? (
        <div className="repository-loading" role="status" aria-live="polite">
          <LoaderCircle size={21} className="spin-icon" />
          <span>Loading your repositories…</span>
        </div>
      ) : !loadError && repositories?.length === 0 ? (
        <div className="repository-empty-state">
          <span className="repository-empty-icon"><GitBranch size={23} /></span>
          <h2>No repositories yet</h2>
          <p>Connect a public GitHub repository to start exploring its codebase.</p>
          <button
            className="repository-button repository-button-primary"
            type="button"
            onClick={openConnectDialog}
          >
            <Plus size={15} />
            Connect your first repository
          </button>
        </div>
      ) : repositories && repositories.length > 0 ? (
        <div className="repository-grid">
          {repositories.map((repository) => (
            <RepositoryCard
              key={repository.id}
              repository={repository}
              isCloning={cloningIds.has(repository.id)}
              onClone={handleClone}
              onDelete={(candidate) => {
                setDeleteError(null)
                setDeleteCandidate(candidate)
              }}
            />
          ))}
        </div>
      ) : null}

      {isConnectOpen && (
        <ConnectRepositoryModal
          isConnecting={isConnecting}
          error={connectError}
          onClose={() => {
            if (!isConnecting) setIsConnectOpen(false)
          }}
          onConnect={handleConnect}
        />
      )}

      {deleteCandidate && (
        <ConfirmDeleteModal
          repository={deleteCandidate}
          isDeleting={deletingId === deleteCandidate.id}
          error={deleteError}
          onCancel={() => {
            if (deletingId === null) {
              setDeleteCandidate(null)
              setDeleteError(null)
            }
          }}
          onConfirm={() => void handleDelete()}
        />
      )}
    </div>
  )
}

export default RepositoriesPage
