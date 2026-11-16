import { useState } from 'react'
import {
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  GitBranch,
  LoaderCircle,
  ScanSearch,
  Trash2,
} from 'lucide-react'
import type { Repository } from '../../api/repositories'
import { useAuth } from '../../auth/useAuth'
import RepositoryAnalysisPanel from './RepositoryAnalysisPanel'

type RepositoryCardProps = {
  repository: Repository
  isCloning: boolean
  onClone: (repository: Repository) => void
  onDelete: (repository: Repository) => void
}

const statusLabels: Record<string, string> = {
  connected: 'Connected',
  cloning: 'Cloning',
  cloned: 'Cloned',
  clone_failed: 'Clone failed',
}

function formatCreatedDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? 'Date unavailable'
    : date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
      })
}

function RepositoryCard({
  repository,
  isCloning,
  onClone,
  onDelete,
}: RepositoryCardProps) {
  const { accessToken, logout } = useAuth()
  const [isAnalysisOpen, setIsAnalysisOpen] = useState(false)
  const [isAnalysisRunning, setIsAnalysisRunning] = useState(false)
  const status = repository.status ?? 'unknown'
  const canClone = status !== 'cloned' && status !== 'cloning'
  const canAnalyze = status === 'cloned'
  const statusClass =
    status === 'cloned'
      ? 'repository-status-cloned'
      : status === 'clone_failed'
        ? 'repository-status-failed'
        : status === 'cloning'
          ? 'repository-status-cloning'
          : 'repository-status-connected'

  return (
    <article className="repository-card">
      <div className="repository-card-top">
        <div className="repository-card-mark"><GitBranch size={19} /></div>
        <span className={`repository-status ${statusClass}`}>
          <span />
          {statusLabels[status] ?? status.replaceAll('_', ' ')}
        </span>
      </div>

      <div className="repository-card-title">
        <h2>{repository.name}</h2>
        <span>{repository.owner_name}</span>
      </div>

      <a
        className="repository-github-link"
        href={repository.github_url}
        target="_blank"
        rel="noopener noreferrer"
      >
        <span>{repository.github_url.replace(/^https:\/\/(www\.)?/, '')}</span>
        <ArrowUpRight size={14} />
      </a>

      <div className="repository-meta">
        <span>
          <GitBranch size={14} />
          {repository.default_branch || 'Branch unavailable'}
        </span>
        <span>Added {formatCreatedDate(repository.created_at)}</span>
      </div>

      <div className="repository-card-actions">
        <div className="repository-card-primary-actions">
          {canClone ? (
            <button
              className="repository-button repository-button-primary"
              type="button"
              onClick={() => onClone(repository)}
              disabled={isCloning}
            >
              {isCloning ? (
                <>
                  <LoaderCircle className="spin-icon" size={15} />
                  Cloning…
                </>
              ) : status === 'clone_failed' ? (
                'Retry clone'
              ) : (
                'Clone repository'
              )}
            </button>
          ) : status === 'cloning' ? (
            <button className="repository-button repository-button-primary" type="button" disabled>
              <LoaderCircle className="spin-icon" size={15} />
              Cloning…
            </button>
          ) : (
            <button
              className="repository-button repository-button-primary"
              type="button"
              aria-expanded={isAnalysisOpen}
              onClick={() => setIsAnalysisOpen((open) => !open)}
              disabled={isAnalysisRunning}
            >
              <ScanSearch size={15} />
              {isAnalysisOpen ? 'Hide analysis' : 'Analyze repository'}
              {isAnalysisOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          )}
          {!canAnalyze && (
            <span className="repository-analysis-prerequisite">
              {status === 'cloning'
                ? 'Analysis will be available after cloning.'
                : 'Clone this repository before analysis.'}
            </span>
          )}
        </div>
        <button
          className="repository-icon-action repository-delete-action"
          type="button"
          aria-label={`Delete ${repository.name}`}
          title="Delete repository"
          onClick={() => onDelete(repository)}
        >
          <Trash2 size={16} />
        </button>
      </div>
      {canAnalyze && (
        <RepositoryAnalysisPanel
          repositoryId={repository.id}
          accessToken={accessToken}
          isOpen={isAnalysisOpen}
          onBusyChange={setIsAnalysisRunning}
          onUnauthorized={logout}
        />
      )}
    </article>
  )
}

export default RepositoryCard
