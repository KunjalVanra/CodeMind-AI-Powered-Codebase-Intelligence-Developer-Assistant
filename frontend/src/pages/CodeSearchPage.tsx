import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  AlertCircle,
  Braces,
  Code2,
  FileCode2,
  LoaderCircle,
  Search,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, ApiNetworkError } from '../api/client'
import {
  searchRepository,
  type CodeSearchResponse,
} from '../api/search'
import {
  listRepositories,
  type Repository,
} from '../api/repositories'
import { useAuth } from '../auth/useAuth'

function CodeSearchPage() {
  const { accessToken, logout } = useAuth()
  const [repositories, setRepositories] = useState<Repository[] | null>(null)
  const [selectedRepositoryId, setSelectedRepositoryId] = useState('')
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [isLoadingRepositories, setIsLoadingRepositories] = useState(true)
  const [repositoryError, setRepositoryError] = useState<string | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [response, setResponse] = useState<CodeSearchResponse | null>(null)
  const searchLock = useRef(false)

  const fetchUserRepositories = useCallback(async () => {
    if (!accessToken) throw new ApiError(401, 'Authentication is required.')
    return listRepositories(accessToken)
  }, [accessToken])

  useEffect(() => {
    if (!accessToken) return
    let isActive = true

    void fetchUserRepositories()
      .then((result) => {
        if (isActive) setRepositories(result)
      })
      .catch((error: unknown) => {
        if (!isActive) return
        if (error instanceof ApiError && error.status === 401) {
          logout()
          setRepositoryError('Your session has expired. Please sign in again.')
        } else {
          setRepositoryError(getSearchErrorMessage(error))
        }
      })
      .finally(() => {
        if (isActive) setIsLoadingRepositories(false)
      })

    return () => {
      isActive = false
    }
  }, [accessToken, fetchUserRepositories, logout])

  async function loadUserRepositories() {
    if (isLoadingRepositories) return
    setIsLoadingRepositories(true)
    setRepositoryError(null)
    try {
      setRepositories(await fetchUserRepositories())
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        logout()
        setRepositoryError('Your session has expired. Please sign in again.')
      } else {
        setRepositoryError(getSearchErrorMessage(error))
      }
    } finally {
      setIsLoadingRepositories(false)
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (searchLock.current || isLoadingRepositories) return

    if (!accessToken) {
      logout()
      setSearchError('Your session has expired. Please sign in again.')
      return
    }

    const repositoryId = Number(selectedRepositoryId)
    const normalizedQuery = query.trim()
    if (!Number.isInteger(repositoryId) || repositoryId < 1) {
      setSearchError('Select a repository before searching.')
      return
    }
    if (!normalizedQuery || normalizedQuery.length > 2000) {
      setSearchError('Enter a search query between 1 and 2000 characters.')
      return
    }

    searchLock.current = true
    setIsSearching(true)
    setSearchError(null)
    setResponse(null)

    try {
      const result = await searchRepository(
        repositoryId,
        { query: normalizedQuery, top_k: topK },
        accessToken,
      )
      setResponse(result)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        logout()
        setSearchError('Your session has expired. Please sign in again.')
      } else if (error instanceof ApiError && error.status === 403) {
        setSearchError(
          `You do not have permission to search this repository. ${error.message}`,
        )
      } else if (error instanceof ApiError && error.status === 409) {
        setSearchError(
          `${error.message}. Index the repository before searching its code.`,
        )
      } else {
        setSearchError(getSearchErrorMessage(error))
      }
    } finally {
      searchLock.current = false
      setIsSearching(false)
    }
  }

  function handleRepositoryChange(repositoryId: string) {
    setSelectedRepositoryId(repositoryId)
    setSearchError(null)
    setResponse(null)
  }

  return (
    <section className="code-search-page page-enter">
      <header className="code-search-heading">
        <div>
          <span className="eyebrow"><span className="eyebrow-line" />Explore</span>
          <h1>Code Search</h1>
          <p>Find relevant code in your repositories with natural-language queries.</p>
        </div>
      </header>

      <section className="code-search-form-panel" aria-label="Search indexed code">
        <form className="code-search-form" onSubmit={(event) => void handleSearch(event)}>
          <label className="form-field" htmlFor="search-repository">
            <span>Repository</span>
            <select
              id="search-repository"
              value={selectedRepositoryId}
              onChange={(event) => handleRepositoryChange(event.target.value)}
              disabled={isLoadingRepositories || !repositories?.length || isSearching}
            >
              <option value="">
                {isLoadingRepositories ? 'Loading repositories…' : 'Select a repository'}
              </option>
              {repositories?.map((repository) => (
                <option key={repository.id} value={repository.id}>
                  {repository.owner_name}/{repository.name}
                  {repository.status === 'cloned' ? '' : ' (not cloned)'}
                </option>
              ))}
            </select>
          </label>

          <label className="form-field" htmlFor="code-search-query">
            <span>What are you looking for?</span>
            <textarea
              id="code-search-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  event.currentTarget.form?.requestSubmit()
                }
              }}
              placeholder="For example: where is the user access token validated?"
              maxLength={2000}
              rows={3}
              disabled={isSearching}
              required
            />
            <span className="code-search-query-hint">
              Press Enter to search · Shift+Enter for a new line · {query.length}/2000
            </span>
          </label>

          <div className="code-search-form-actions">
            <label className="code-search-top-k" htmlFor="code-search-top-k">
              <span>Results</span>
              <select
                id="code-search-top-k"
                value={topK}
                onChange={(event) => setTopK(Number(event.target.value))}
                disabled={isSearching}
              >
                {Array.from({ length: 10 }, (_, index) => index + 1).map((count) => (
                  <option key={count} value={count}>{count}</option>
                ))}
              </select>
            </label>
            <button
              className="repository-button repository-button-primary code-search-submit"
              type="submit"
              disabled={
                isLoadingRepositories ||
                isSearching ||
                !selectedRepositoryId ||
                !query.trim() ||
                !accessToken
              }
            >
              {isSearching ? (
                <>
                  <LoaderCircle size={15} className="spin-icon" />
                  Searching…
                </>
              ) : (
                <>
                  <Search size={15} />
                  Search code
                </>
              )}
            </button>
          </div>
        </form>

        {repositoryError && (
          <div className="code-search-message code-search-error" role="alert">
            <AlertCircle size={16} />
            <span>{repositoryError}</span>
            <button
              className="repository-button repository-button-quiet"
              type="button"
              onClick={() => {
                setRepositoryError(null)
                setIsLoadingRepositories(true)
                void loadUserRepositories()
              }}
              disabled={isLoadingRepositories}
            >
              Retry
            </button>
          </div>
        )}

        {!isLoadingRepositories && !repositoryError && repositories?.length === 0 && (
          <div className="code-search-empty-repositories">
            <FileCode2 size={17} />
            <span>No repositories are connected yet.</span>
            <Link to="/repositories">Manage repositories</Link>
          </div>
        )}

        {searchError && (
          <div className="code-search-message code-search-error" role="alert">
            <AlertCircle size={16} />
            <span>{searchError}</span>
          </div>
        )}
      </section>

      {isSearching && (
        <div className="code-search-loading" role="status" aria-live="polite">
          <LoaderCircle size={20} className="spin-icon" />
          <span>Searching indexed code…</span>
        </div>
      )}

      {response && !isSearching && (
        <section className="code-search-results" aria-live="polite">
          <div className="code-search-results-heading">
            <div>
              <span className="eyebrow"><span className="eyebrow-line" />Results</span>
              <h2>
                {response.total_results === 1
                  ? '1 matching code chunk'
                  : `${response.total_results.toLocaleString()} matching code chunks`}
              </h2>
              <p>For “{response.query}”</p>
            </div>
          </div>

          {response.results.length === 0 ? (
            <div className="code-search-no-results">
              <span className="code-search-no-results-icon"><Search size={19} /></span>
              <h3>No matching code found</h3>
              <p>Try a different query or select another indexed repository.</p>
            </div>
          ) : (
            <div className="code-search-result-list">
              {response.results.map((result, index) => (
                <article
                  className="code-search-result-card"
                  key={`${result.file_path}:${result.start_line}:${index}`}
                >
                  <div className="code-search-result-header">
                    <div className="code-search-file">
                      <FileCode2 size={16} />
                      <code title={result.file_path}>{result.file_path}</code>
                    </div>
                    <span className="code-search-score">
                      Similarity {result.similarity.toFixed(3)}
                    </span>
                  </div>

                  <div className="code-search-result-meta">
                    <span><Braces size={13} />{result.language}</span>
                    <span><Code2 size={13} />{result.chunk_type}</span>
                    {result.symbol && <span>Symbol: {result.symbol}</span>}
                    {result.parent_type && <span>Parent: {result.parent_type}</span>}
                    <span>Lines {result.start_line}–{result.end_line}</span>
                  </div>

                  <pre className="code-search-snippet">
                    <code>{result.snippet}</code>
                  </pre>
                </article>
              ))}
            </div>
          )}
        </section>
      )}
    </section>
  )
}

function getSearchErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Your session has expired. Please sign in again.'
    if (error.status === 403) return `Access was denied. ${error.message}`
    if (error.status === 404) return 'The selected repository was not found or is no longer available.'
    return error.message
  }
  if (error instanceof ApiNetworkError) return error.message
  return 'Search could not be completed. Please try again.'
}

export default CodeSearchPage
