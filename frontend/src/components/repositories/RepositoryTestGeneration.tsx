import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  AlertCircle,
  Check,
  Clipboard,
  ClipboardCheck,
  FlaskConical,
  LoaderCircle,
  RotateCcw,
  Sparkles,
} from 'lucide-react'
import { ApiError, ApiNetworkError } from '../../api/client'
import {
  generateRepositoryTests,
  type TestFramework,
  type TestGenerationResponse,
} from '../../api/testGeneration'
import { listRepositories, type Repository } from '../../api/repositories'

type RepositoryTestGenerationProps = {
  initialRepositoryId: number
  accessToken: string | null
  onUnauthorized: () => void
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiNetworkError) return error.message
  if (!(error instanceof ApiError)) {
    return 'Tests could not be generated. Please try again.'
  }
  switch (error.status) {
    case 401:
      return 'Your session has expired. Please sign in again.'
    case 403:
      return 'You do not have permission to access this repository.'
    case 404:
      return error.message || 'Repository or parsed source file was not found.'
    case 409:
      return 'Clone and parse the repository before generating tests.'
    case 422:
      return error.message
    case 429:
      return 'The AI service is rate limited. Please wait and try again.'
    case 503:
      return 'AI test generation is unavailable. Check the backend Groq configuration or try again later.'
    default:
      return error.message
  }
}

function getFilePathError(value: string): string | null {
  const path = value.trim().replace(/\\/g, '/')
  if (!path) return 'Enter a source file path.'
  if (path.startsWith('/') || /^[a-zA-Z]:/.test(path)) {
    return 'Use a repository-relative file path.'
  }
  if (path.split('/').some((part) => part === '..')) {
    return 'Parent-directory paths are not allowed.'
  }
  if (!path.toLowerCase().endsWith('.py')) {
    return 'The backend currently supports Python (.py) files only.'
  }
  return null
}

function RepositoryTestGeneration({
  initialRepositoryId,
  accessToken,
  onUnauthorized,
}: RepositoryTestGenerationProps) {
  const [repositories, setRepositories] = useState<Repository[] | null>(null)
  const [repositoryError, setRepositoryError] = useState<string | null>(null)
  const [loadedToken, setLoadedToken] = useState<string | null>(null)
  const [completedLoadAttempt, setCompletedLoadAttempt] = useState(-1)
  const [selectedRepositoryId, setSelectedRepositoryId] =
    useState<number | ''>(initialRepositoryId)
  const [filePath, setFilePath] = useState('')
  const [framework, setFramework] = useState<TestFramework>('unittest')
  const [result, setResult] = useState<TestGenerationResponse | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [copyMessage, setCopyMessage] = useState<string | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const requestLock = useRef(false)
  const isLoadingRepositories =
    Boolean(accessToken) &&
    (loadedToken !== accessToken || completedLoadAttempt !== loadAttempt)
  const visibleRepositoryError = accessToken
    ? repositoryError
    : 'Your session has expired. Please sign in again.'

  useEffect(() => {
    let active = true
    if (!accessToken) {
      onUnauthorized()
      return () => {
        active = false
      }
    }

    void listRepositories(accessToken)
      .then((items) => {
        if (!active) return
        setRepositories(items)
        setRepositoryError(null)
        const selected = items.find(
          (repository) => repository.id === initialRepositoryId,
        )
        const fallback =
          items.find((repository) => repository.status === 'cloned') ?? items[0]
        setSelectedRepositoryId((selected ?? fallback)?.id ?? '')
        setLoadedToken(accessToken)
        setCompletedLoadAttempt(loadAttempt)
      })
      .catch((error: unknown) => {
        if (!active) return
        if (error instanceof ApiError && error.status === 401) onUnauthorized()
        setRepositoryError(getErrorMessage(error))
        setLoadedToken(accessToken)
        setCompletedLoadAttempt(loadAttempt)
      })

    return () => {
      active = false
    }
  }, [accessToken, initialRepositoryId, loadAttempt, onUnauthorized])

  const selectedRepository = repositories?.find(
    (repository) => repository.id === selectedRepositoryId,
  )
  const filePathError = getFilePathError(filePath)

  function clearResult() {
    setResult(null)
    setGenerationError(null)
    setCopyMessage(null)
  }

  async function handleGenerate(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault()
    if (requestLock.current || isGenerating) return
    if (!accessToken) {
      onUnauthorized()
      setGenerationError('Your session has expired. Please sign in again.')
      return
    }
    if (!selectedRepository) {
      setGenerationError('Select a repository before generating tests.')
      return
    }
    if (selectedRepository.status !== 'cloned') {
      setGenerationError('Clone the repository before generating tests.')
      return
    }
    if (filePathError) {
      setGenerationError(filePathError)
      return
    }

    requestLock.current = true
    setIsGenerating(true)
    setGenerationError(null)
    setCopyMessage(null)
    setResult(null)
    try {
      const response = await generateRepositoryTests(
        selectedRepository.id,
        { file_path: filePath.trim(), framework },
        accessToken,
      )
      if (response.status !== 'completed') {
        setGenerationError('Test generation did not complete successfully. Please retry.')
        return
      }
      setResult(response)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUnauthorized()
      setGenerationError(getErrorMessage(error))
    } finally {
      requestLock.current = false
      setIsGenerating(false)
    }
  }

  async function copyGeneratedCode() {
    if (!result?.generated_test_code) return
    try {
      await navigator.clipboard.writeText(result.generated_test_code)
      setCopyMessage('Generated code copied.')
    } catch {
      setCopyMessage('Clipboard access is unavailable in this browser.')
    }
  }

  return (
    <section
      className="analysis-result-section test-generation-section"
      aria-labelledby="test-generation-title"
    >
      <div className="analysis-result-heading">
        <div className="test-generation-title">
          <FlaskConical size={14} />
          <h4 id="test-generation-title">AI test generation</h4>
        </div>
        <span>Python only</span>
      </div>
      <p className="test-generation-intro">
        Generate test code from a parsed Python source file. Generated tests are
        AI-written and will not be executed or verified.
      </p>

      {isLoadingRepositories && (
        <div className="test-generation-state" role="status" aria-live="polite">
          <LoaderCircle size={14} className="spin-icon" />
          Loading your repositories…
        </div>
      )}

      {visibleRepositoryError && (
        <div className="test-generation-error" role="alert">
          <AlertCircle size={14} aria-hidden="true" />
          <span>{visibleRepositoryError}</span>
          {accessToken && (
            <button
              className="repository-button repository-button-quiet"
              type="button"
              onClick={() => {
                setRepositoryError(null)
                setLoadAttempt((attempt) => attempt + 1)
              }}
              disabled={isLoadingRepositories}
            >
              <RotateCcw size={12} />
              Retry
            </button>
          )}
        </div>
      )}

      {!isLoadingRepositories &&
        !visibleRepositoryError &&
        repositories?.length === 0 && (
          <div className="test-generation-empty" role="status">
            No repositories are available. Connect a repository to get started.
          </div>
        )}

      {!isLoadingRepositories &&
        !visibleRepositoryError &&
        repositories &&
        repositories.length > 0 && (
          <form
            className="test-generation-form"
            onSubmit={(event) => void handleGenerate(event)}
          >
            <label className="test-generation-field">
              <span>Repository</span>
              <select
                value={selectedRepositoryId}
                onChange={(event) => {
                  const value = Number(event.target.value)
                  setSelectedRepositoryId(Number.isInteger(value) ? value : '')
                  clearResult()
                }}
                disabled={isGenerating}
              >
                {repositories.map((repository) => (
                  <option key={repository.id} value={repository.id}>
                    {repository.owner_name}/{repository.name}
                    {repository.status === 'cloned' ? '' : ' — clone required'}
                  </option>
                ))}
              </select>
            </label>

            <label className="test-generation-field">
              <span>Source file path</span>
              <input
                type="text"
                value={filePath}
                onChange={(event) => {
                  setFilePath(event.target.value)
                  clearResult()
                }}
                placeholder="src/module.py"
                aria-invalid={Boolean(filePathError)}
                aria-describedby="test-generation-path-help"
                disabled={isGenerating}
              />
              <small id="test-generation-path-help">
                Enter a parsed, repository-relative Python file.
              </small>
              {filePathError && (
                <span className="test-generation-field-error" role="alert">
                  {filePathError}
                </span>
              )}
            </label>

            <label className="test-generation-field">
              <span>Test framework</span>
              <select
                value={framework}
                onChange={(event) => {
                  const value = event.target.value
                  if (value === 'unittest' || value === 'pytest') {
                    setFramework(value)
                    clearResult()
                  }
                }}
                disabled={isGenerating}
              >
                <option value="unittest">unittest (default)</option>
                <option value="pytest">pytest</option>
              </select>
            </label>

            {selectedRepository?.status !== 'cloned' && (
              <p className="test-generation-prerequisite" role="status">
                Clone this repository and complete parsing before generating tests.
              </p>
            )}

            <button
              className="repository-button repository-button-quiet test-generation-submit"
              type="submit"
              disabled={
                isGenerating ||
                !selectedRepository ||
                selectedRepository.status !== 'cloned' ||
                Boolean(filePathError)
              }
            >
              {isGenerating ? (
                <>
                  <LoaderCircle size={14} className="spin-icon" />
                  Generating…
                </>
              ) : (
                <>
                  <Sparkles size={14} />
                  Generate tests
                </>
              )}
            </button>
          </form>
        )}

      {isGenerating && (
        <div className="test-generation-state" role="status" aria-live="polite">
          <LoaderCircle size={14} className="spin-icon" />
          Generating tests from parsed source…
        </div>
      )}

      {generationError && (
        <div className="test-generation-error" role="alert">
          <AlertCircle size={14} aria-hidden="true" />
          <span>{generationError}</span>
          <button
            className="repository-button repository-button-quiet"
            type="button"
            onClick={() => void handleGenerate()}
            disabled={isGenerating || !selectedRepository || Boolean(filePathError)}
          >
            <RotateCcw size={12} />
            Retry
          </button>
        </div>
      )}

      {result && (
        <section className="test-generation-result" aria-label="Generated tests">
          <div className="test-generation-result-header">
            <div className="test-generation-metadata">
              <strong>AI-generated tests · Not verified</strong>
              <code>{result.source_file_path}</code>
              <span>
                {result.language} · {result.test_framework}
                {result.model ? ` · ${result.model}` : ''}
              </span>
            </div>
            <button
              className="repository-button repository-button-quiet test-generation-copy"
              type="button"
              onClick={() => void copyGeneratedCode()}
              disabled={!result.generated_test_code.trim()}
            >
              {copyMessage === 'Generated code copied.' ? (
                <ClipboardCheck size={13} />
              ) : copyMessage ? (
                <Clipboard size={13} />
              ) : (
                <Clipboard size={13} />
              )}
              {copyMessage === 'Generated code copied.' ? 'Copied' : 'Copy code'}
            </button>
          </div>

          <div
            className="test-generation-verification"
            role="status"
            aria-live="polite"
          >
            <AlertCircle size={13} />
            <span>
              {result.verified === false &&
              result.verification_status === 'not_executed'
                ? 'These tests were generated by AI and were not executed or verified.'
                : 'Verification status was not recognized; treat this output as unverified.'}
            </span>
          </div>

          <p className="test-generation-explanation">{result.explanation}</p>

          {result.limitations.length > 0 && (
            <div className="test-generation-limitations">
              <strong>Limitations</strong>
              <ul>
                {result.limitations.map((limitation, index) => (
                  <li key={`${limitation}-${index}`}>{limitation}</li>
                ))}
              </ul>
            </div>
          )}

          {copyMessage && copyMessage !== 'Generated code copied.' && (
            <p className="test-generation-copy-message" role="status">
              {copyMessage}
            </p>
          )}

          {result.generated_test_code.trim() ? (
            <pre className="test-generation-code">
              <code>{result.generated_test_code}</code>
            </pre>
          ) : (
            <div className="test-generation-empty" role="status">
              <Check size={14} aria-hidden="true" />
              No test code was generated. {result.explanation}
            </div>
          )}
        </section>
      )}
    </section>
  )
}

export default RepositoryTestGeneration
