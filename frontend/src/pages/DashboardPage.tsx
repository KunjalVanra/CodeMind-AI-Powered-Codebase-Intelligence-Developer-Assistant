import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowRight,
  CheckCircle2,
  FileCode2,
  GitBranch,
  LoaderCircle,
  RefreshCw,
  Search,
  Sparkles,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, ApiNetworkError } from '../api/client'
import { listRepositories, type Repository } from '../api/repositories'
import { useAuth } from '../auth/useAuth'
import RepositoryArchitectureAnalytics from '../components/repositories/RepositoryArchitectureAnalytics'

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof ApiNetworkError) {
    return error.message
  }
  return 'Repositories could not be loaded. Please try again.'
}

function DashboardPage() {
  const { user, accessToken, logout } = useAuth()
  const [repositories, setRepositories] = useState<Repository[] | null>(null)
  const [selectedRepositoryId, setSelectedRepositoryId] = useState<number | ''>('')
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const initialLoadToken = useRef<string | null>(null)

  const loadRepositories = useCallback(async () => {
    if (!accessToken) return
    setIsLoading(true)
    setLoadError(null)
    try {
      const result = await listRepositories(accessToken)
      setRepositories(result)
      setSelectedRepositoryId((current) =>
        current !== '' && result.some((repository) => repository.id === current)
          ? current
          : result[0]?.id ?? '',
      )
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) logout()
      setLoadError(getErrorMessage(error))
    } finally {
      setIsLoading(false)
    }
  }, [accessToken, logout])

  useEffect(() => {
    if (!accessToken || initialLoadToken.current === accessToken) return
    initialLoadToken.current = accessToken
    void loadRepositories()
  }, [accessToken, loadRepositories])

  const selectedRepository = repositories?.find(
    (repository) => repository.id === selectedRepositoryId,
  )
  const clonedCount = repositories?.filter(
    (repository) => repository.status === 'cloned',
  ).length
  const notClonedCount = repositories
    ? repositories.length - (clonedCount ?? 0)
    : null
  const recentRepositories = [...(repositories ?? [])]
    .sort((first, second) => second.created_at.localeCompare(first.created_at))
    .slice(0, 5)

  return (
    <div className="dashboard-page page-enter">
      <section className="welcome-row">
        <div>
          <div className="eyebrow"><span className="eyebrow-line" />Your workspace</div>
          <h1>Welcome to CodeMind{user ? `, ${user.full_name.split(' ')[0]}` : ''}</h1>
          <p className="welcome-subtitle">
            Understand your codebase. Ask better questions. Build faster.
          </p>
        </div>
        <Link className="repository-button repository-button-quiet" to="/repositories">
          Manage repositories <ArrowRight size={14} />
        </Link>
      </section>

      <section className="stat-grid dashboard-live-stats" aria-label="Repository overview">
        <article className="stat-card">
          <div className="stat-card-top">
            <span className="stat-icon icon-purple"><GitBranch size={18} /></span>
            <span className="stat-note">From your repository list</span>
          </div>
          <div className="stat-value" aria-live="polite">
            {isLoading ? <span className="dashboard-stat-skeleton" /> : (repositories?.length ?? '—')}
          </div>
          <div className="stat-label">Connected repositories</div>
          <div className="stat-trend">Current account total</div>
        </article>
        <article className="stat-card">
          <div className="stat-card-top">
            <span className="stat-icon icon-blue"><CheckCircle2 size={18} /></span>
            <span className="stat-note">Ready to analyze</span>
          </div>
          <div className="stat-value" aria-live="polite">
            {isLoading ? <span className="dashboard-stat-skeleton" /> : (clonedCount ?? '—')}
          </div>
          <div className="stat-label">Cloned repositories</div>
          <div className="stat-trend">Repository status</div>
        </article>
        <article className="stat-card">
          <div className="stat-card-top">
            <span className="stat-icon icon-cyan"><FileCode2 size={18} /></span>
            <span className="stat-note">Clone before analysis</span>
          </div>
          <div className="stat-value" aria-live="polite">
            {isLoading ? <span className="dashboard-stat-skeleton" /> : (notClonedCount ?? '—')}
          </div>
          <div className="stat-label">Not yet cloned</div>
          <div className="stat-trend">Includes pending and failed clones</div>
        </article>
      </section>

      {loadError && (
        <div className="dashboard-load-error" role="alert">
          <span>{loadError}</span>
          <button
            className="repository-button repository-button-quiet"
            type="button"
            onClick={() => void loadRepositories()}
            disabled={isLoading}
          >
            <RefreshCw size={13} />
            Retry
          </button>
        </div>
      )}

      <section className="quick-actions-section">
        <div className="section-heading">
          <div>
            <h2>Quick actions</h2>
            <p>Pick up where your codebase work begins.</p>
          </div>
        </div>
        <div className="quick-action-grid">
          <Link className="quick-action-card" to="/repositories">
            <span className="quick-action-icon icon-purple"><GitBranch size={19} /></span>
            <span className="quick-action-copy">
              <strong>Connect repository</strong>
              <span>Bring a codebase into your workspace</span>
            </span>
            <ArrowRight className="quick-action-arrow" size={17} />
          </Link>
          <Link className="quick-action-card" to="/search">
            <span className="quick-action-icon icon-blue"><Search size={19} /></span>
            <span className="quick-action-copy">
              <strong>Search code</strong>
              <span>Find functions, files, and patterns</span>
            </span>
            <ArrowRight className="quick-action-arrow" size={17} />
          </Link>
          <Link className="quick-action-card" to="/assistant">
            <span className="quick-action-icon icon-cyan"><Sparkles size={19} /></span>
            <span className="quick-action-copy">
              <strong>Ask AI</strong>
              <span>Explore your codebase with citations</span>
            </span>
            <ArrowRight className="quick-action-arrow" size={17} />
          </Link>
        </div>
      </section>

      <section className="panel dashboard-architecture-panel" aria-labelledby="dashboard-architecture-title">
        <div className="panel-heading dashboard-architecture-heading">
          <div>
            <h2 id="dashboard-architecture-title">Architecture analytics</h2>
            <p>Explore measured metrics for one repository at a time.</p>
          </div>
          <div className="dashboard-repository-selector">
            <label htmlFor="dashboard-repository">Repository</label>
            <select
              id="dashboard-repository"
              value={selectedRepositoryId}
              onChange={(event) => setSelectedRepositoryId(
                event.target.value ? Number(event.target.value) : '',
              )}
              disabled={isLoading || !repositories?.length}
            >
              {(repositories ?? []).map((repository) => (
                <option key={repository.id} value={repository.id}>
                  {repository.owner_name}/{repository.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {isLoading ? (
          <div className="dashboard-panel-state" role="status" aria-live="polite">
            <LoaderCircle size={16} className="spin-icon" />
            Loading your repositories…
          </div>
        ) : loadError ? (
          <div className="dashboard-panel-state">
            Architecture analytics will be available after repositories load.
          </div>
        ) : repositories?.length === 0 ? (
          <div className="dashboard-empty-state">
            <GitBranch size={21} />
            <strong>No repositories connected yet</strong>
            <span>Connect a repository to see its architecture analytics here.</span>
            <Link className="repository-button repository-button-primary" to="/repositories">
              Connect repository <ArrowRight size={14} />
            </Link>
          </div>
        ) : selectedRepository && accessToken ? (
          <>
            <div className="dashboard-selected-repository">
              <span>Selected repository</span>
              <strong>{selectedRepository.owner_name}/{selectedRepository.name}</strong>
              <Link className="text-link" to="/repositories">
                Manage and open repository analysis <ArrowRight size={14} />
              </Link>
            </div>
            <RepositoryArchitectureAnalytics
              key={selectedRepository.id}
              repositoryId={selectedRepository.id}
              accessToken={accessToken}
              onUnauthorized={logout}
            />
          </>
        ) : (
          <div className="dashboard-panel-state">Select a repository to view its analytics.</div>
        )}
      </section>

      <section className="panel recent-repositories dashboard-recent-panel">
        <div className="panel-heading">
          <div>
            <h2>Recent repositories</h2>
            <p>Your latest connected codebases.</p>
          </div>
          <Link className="text-link" to="/repositories">
            View all <ArrowRight size={15} />
          </Link>
        </div>
        {isLoading ? (
          <div className="dashboard-panel-state" role="status">
            <LoaderCircle size={15} className="spin-icon" />
            Loading repositories…
          </div>
        ) : recentRepositories.length > 0 ? (
          <div className="repository-list">
            {recentRepositories.map((repository) => (
              <div className="repository-row" key={repository.id}>
                <span className="repo-avatar repo-blue">
                  <GitBranch size={14} />
                </span>
                <div className="repo-main">
                  <strong>{repository.name}</strong>
                  <span>{repository.owner_name}</span>
                </div>
                <span className={`dashboard-repository-status status-${repository.status ?? 'unknown'}`}>
                  {repository.status?.replaceAll('_', ' ') ?? 'unknown'}
                </span>
              </div>
            ))}
          </div>
        ) : loadError ? (
          <div className="dashboard-panel-state">Repository list is unavailable. Use Retry above to reload it.</div>
        ) : (
          <div className="dashboard-panel-state">No repositories connected yet.</div>
        )}
      </section>
    </div>
  )
}

export default DashboardPage
