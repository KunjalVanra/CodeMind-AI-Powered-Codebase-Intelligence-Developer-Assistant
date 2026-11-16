import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  AlertCircle,
  BookOpenText,
  Check,
  Clipboard,
  LoaderCircle,
  RotateCcw,
  Sparkles,
} from 'lucide-react'
import { ApiError, ApiNetworkError } from '../../api/client'
import {
  generateRepositoryDocumentation,
  type DocumentationResponse,
  type DocumentationType,
} from '../../api/documentation'
import {
  listRepositories,
  type Repository,
} from '../../api/repositories'

type RepositoryDocumentationProps = {
  initialRepositoryId: number
  accessToken: string | null
  onUnauthorized: () => void
}

const documentationTypes: Array<{
  value: DocumentationType
  label: string
}> = [
  { value: 'readme', label: 'Repository README' },
  { value: 'module', label: 'Module / file' },
  { value: 'function', label: 'Functions' },
  { value: 'class', label: 'Classes' },
  { value: 'api', label: 'API' },
]

function isDocumentationType(value: string): value is DocumentationType {
  return documentationTypes.some((type) => type.value === value)
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiNetworkError) return error.message
  if (!(error instanceof ApiError)) {
    return 'Documentation could not be generated. Please try again.'
  }

  switch (error.status) {
    case 401:
      return 'Your session has expired. Please sign in again.'
    case 403:
      return 'You do not have permission to access this repository.'
    case 404:
      return 'Repository was not found or you no longer have access to it.'
    case 409:
      return 'Clone and parse the repository before generating documentation.'
    case 422:
      return error.message
    case 429:
      return 'The documentation service is rate limited. Please wait and try again.'
    case 503:
      return 'The service is temporarily unavailable. Please try again.'
    default:
      return error.message
  }
}

function getPathError(value: string, documentationType: DocumentationType): string | null {
  const path = value.trim().replace(/\\/g, '/')
  if (documentationType === 'module' && !path) {
    return 'Enter a file path for module documentation.'
  }
  if (!path) return null
  if (path.startsWith('/') || /^[a-zA-Z]:/.test(path)) {
    return 'Use a repository-relative file path.'
  }
  if (path.split('/').some((part) => part === '..')) {
    return 'Parent-directory paths are not allowed.'
  }
  return null
}

function renderInline(text: string, keyPrefix: string) {
  const tokens = text.split(/(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)/g)
  return tokens.map((token, index) => {
    const key = `${keyPrefix}-${index}`
    if (token.startsWith('`') && token.endsWith('`')) {
      return <code key={key}>{token.slice(1, -1)}</code>
    }
    if (
      (token.startsWith('**') && token.endsWith('**')) ||
      (token.startsWith('__') && token.endsWith('__'))
    ) {
      return <strong key={key}>{token.slice(2, -2)}</strong>
    }
    if (
      (token.startsWith('*') && token.endsWith('*')) ||
      (token.startsWith('_') && token.endsWith('_'))
    ) {
      return <em key={key}>{token.slice(1, -1)}</em>
    }
    return token
  })
}

function MarkdownPreview({ markdown }: { markdown: string }) {
  const lines = markdown.split(/\r?\n/)
  const blocks = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    if (line.trimStart().startsWith('```')) {
      const codeLines = []
      index += 1
      while (index < lines.length && !lines[index].trimStart().startsWith('```')) {
        codeLines.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push(
        <pre className="documentation-code-block" key={`code-${blocks.length}`}>
          <code>{codeLines.join('\n')}</code>
        </pre>,
      )
      continue
    }

    const heading = /^(#{1,6})\s+(.+)$/.exec(line)
    if (heading) {
      blocks.push(
        <h3
          className="documentation-markdown-heading"
          data-level={heading[1].length}
          key={`heading-${blocks.length}`}
        >
          {renderInline(heading[2], `heading-${blocks.length}`)}
        </h3>,
      )
      index += 1
      continue
    }

    if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) {
      blocks.push(<hr key={`rule-${blocks.length}`} />)
      index += 1
      continue
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items = []
      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ''))
        index += 1
      }
      blocks.push(
        <ul key={`list-${blocks.length}`}>
          {items.map((item, itemIndex) => (
            <li key={`item-${itemIndex}`}>
              {renderInline(item, `list-${blocks.length}-${itemIndex}`)}
            </li>
          ))}
        </ul>,
      )
      continue
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items = []
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ''))
        index += 1
      }
      blocks.push(
        <ol key={`ordered-${blocks.length}`}>
          {items.map((item, itemIndex) => (
            <li key={`item-${itemIndex}`}>
              {renderInline(item, `ordered-${blocks.length}-${itemIndex}`)}
            </li>
          ))}
        </ol>,
      )
      continue
    }

    if (/^\s*&gt;\s?/.test(line) || /^\s*>\s?/.test(line)) {
      const quote = []
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^\s*>\s?/, ''))
        index += 1
      }
      blocks.push(
        <blockquote key={`quote-${blocks.length}`}>
          {quote.map((text, quoteIndex) => (
            <p key={`quote-line-${quoteIndex}`}>
              {renderInline(text, `quote-${blocks.length}-${quoteIndex}`)}
            </p>
          ))}
        </blockquote>,
      )
      continue
    }

    const paragraph = [line]
    index += 1
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,6})\s+/.test(lines[index]) &&
      !lines[index].trimStart().startsWith('```') &&
      !/^\s*[-*+]\s+/.test(lines[index]) &&
      !/^\s*\d+\.\s+/.test(lines[index]) &&
      !/^\s*>\s?/.test(lines[index]) &&
      !/^\s*(---+|\*\*\*+|___+)\s*$/.test(lines[index])
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(
      <p key={`paragraph-${blocks.length}`}>
        {renderInline(paragraph.join(' '), `paragraph-${blocks.length}`)}
      </p>,
    )
  }

  return <div className="documentation-markdown">{blocks}</div>
}

function RepositoryDocumentation({
  initialRepositoryId,
  accessToken,
  onUnauthorized,
}: RepositoryDocumentationProps) {
  const [repositories, setRepositories] = useState<Repository[] | null>(null)
  const [repositoryError, setRepositoryError] = useState<string | null>(null)
  const [loadedToken, setLoadedToken] = useState<string | null>(null)
  const [completedLoadAttempt, setCompletedLoadAttempt] = useState(-1)
  const [selectedRepositoryId, setSelectedRepositoryId] =
    useState<number | ''>(initialRepositoryId)
  const [documentationType, setDocumentationType] =
    useState<DocumentationType>('readme')
  const [filePath, setFilePath] = useState('')
  const [result, setResult] = useState<DocumentationResponse | null>(null)
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
        const selected = items.find((repository) => repository.id === initialRepositoryId)
        const fallback = items.find((repository) => repository.status === 'cloned') ?? items[0]
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
  const pathError = getPathError(filePath, documentationType)

  function clearGeneratedResult() {
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
      setGenerationError('Select a repository before generating documentation.')
      return
    }
    if (selectedRepository.status !== 'cloned') {
      setGenerationError('Clone and parse this repository before generating documentation.')
      return
    }
    if (pathError) {
      setGenerationError(pathError)
      return
    }

    requestLock.current = true
    setIsGenerating(true)
    setGenerationError(null)
    setCopyMessage(null)
    setResult(null)
    try {
      const response = await generateRepositoryDocumentation(
        selectedRepository.id,
        {
          documentation_type: documentationType,
          ...(filePath.trim() ? { file_path: filePath.trim() } : {}),
        },
        accessToken,
      )
      if (response.status !== 'completed') {
        setGenerationError('Documentation generation did not complete successfully. Please retry.')
        return
      }
      setResult(response)
      if (!response.documentation.trim()) {
        setGenerationError('The backend returned no documentation text. Please retry.')
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) onUnauthorized()
      setGenerationError(
        error instanceof ApiError && error.status === 503
          ? 'AI documentation is unavailable. Check the backend Groq configuration or try again later.'
          : getErrorMessage(error),
      )
    } finally {
      requestLock.current = false
      setIsGenerating(false)
    }
  }

  async function copyDocumentation() {
    if (!result?.documentation) return
    try {
      await navigator.clipboard.writeText(result.documentation)
      setCopyMessage('Markdown copied.')
    } catch {
      setCopyMessage('Clipboard access is unavailable in this browser.')
    }
  }

  return (
    <section
      className="analysis-result-section documentation-section"
      aria-labelledby="repository-documentation-title"
    >
      <div className="analysis-result-heading">
        <div className="documentation-title">
          <BookOpenText size={14} />
          <h4 id="repository-documentation-title">AI documentation</h4>
        </div>
        <span>Groq</span>
      </div>
      <p className="documentation-intro">
        Generate source-grounded documentation from the repository’s completed parse analysis.
      </p>

      {isLoadingRepositories && (
        <div className="documentation-state" role="status" aria-live="polite">
          <LoaderCircle size={14} className="spin-icon" />
          Loading your repositories…
        </div>
      )}

      {visibleRepositoryError && (
        <div className="documentation-error" role="alert">
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

      {!isLoadingRepositories && !visibleRepositoryError && repositories?.length === 0 && (
        <div className="documentation-empty" role="status">
          No repositories are available. Connect a repository to get started.
        </div>
      )}

      {!isLoadingRepositories &&
        !visibleRepositoryError &&
        repositories &&
        repositories.length > 0 && (
        <form className="documentation-form"         onSubmit={(event) => void handleGenerate(event)}>
          <label className="documentation-field">
            <span>Repository</span>
            <select
              value={selectedRepositoryId}
              onChange={(event) => {
                const value = Number(event.target.value)
                setSelectedRepositoryId(Number.isInteger(value) ? value : '')
                clearGeneratedResult()
              }}
              disabled={isLoadingRepositories || isGenerating}
            >
              {repositories.map((repository) => (
                <option key={repository.id} value={repository.id}>
                  {repository.owner_name}/{repository.name}
                  {repository.status === 'cloned' ? '' : ' — clone required'}
                </option>
              ))}
            </select>
          </label>

          <label className="documentation-field">
            <span>Documentation type</span>
            <select
              value={documentationType}
              onChange={(event) => {
                const value = event.target.value
                if (isDocumentationType(value)) {
                  setDocumentationType(value)
                  clearGeneratedResult()
                }
              }}
              disabled={isGenerating}
            >
              {documentationTypes.map((type) => (
                <option key={type.value} value={type.value}>{type.label}</option>
              ))}
            </select>
          </label>

          <label className="documentation-field">
            <span>
              File path
              {documentationType === 'module' ? ' (required)' : ' (optional)'}
            </span>
            <input
              type="text"
              value={filePath}
              onChange={(event) => {
                setFilePath(event.target.value)
                clearGeneratedResult()
              }}
              placeholder={
                documentationType === 'module'
                  ? 'src/module.py'
                  : 'Optional, e.g. src/module.py'
              }
              aria-invalid={Boolean(pathError)}
              aria-describedby="documentation-path-help"
              disabled={isGenerating}
            />
            <small id="documentation-path-help">
              {documentationType === 'module'
                ? 'Enter a parsed, repository-relative source file.'
                : 'Optionally scope the documentation to a parsed source file.'}
            </small>
            {pathError && (
              <span className="documentation-field-error" role="alert">
                {pathError}
              </span>
            )}
          </label>

          {selectedRepository?.status !== 'cloned' && (
            <p className="documentation-prerequisite" role="status">
              Clone this repository and complete parsing before generating documentation.
            </p>
          )}

          <button
            className="repository-button repository-button-quiet documentation-submit"
            type="submit"
            disabled={
              isGenerating ||
              isLoadingRepositories ||
              !selectedRepository ||
              selectedRepository.status !== 'cloned' ||
              Boolean(pathError)
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
                Generate documentation
              </>
            )}
          </button>
        </form>
      )}

      {generationError && (
        <div className="documentation-error" role="alert">
          <AlertCircle size={14} aria-hidden="true" />
          <span>{generationError}</span>
          <button
            className="repository-button repository-button-quiet"
            type="button"
            onClick={() => void handleGenerate()}
            disabled={isGenerating || !selectedRepository}
          >
            <RotateCcw size={12} />
            Retry
          </button>
        </div>
      )}

      {isGenerating && (
        <div className="documentation-state" role="status" aria-live="polite">
          <LoaderCircle size={14} className="spin-icon" />
          Generating documentation from parsed repository data…
        </div>
      )}

      {result && (
        <section className="documentation-result" aria-label="Generated documentation">
          <div className="documentation-result-heading">
            <div>
              <strong>
                {documentationTypes.find((type) => type.value === result.documentation_type)?.label}
              </strong>
              {result.file_path && <code>{result.file_path}</code>}
              <small>
                {result.sufficient_information
                  ? `Generated from ${result.source_file_count.toLocaleString()} parsed file${result.source_file_count === 1 ? '' : 's'}`
                  : 'Source information was insufficient'}
                {result.model ? ` · ${result.model}` : ''}
              </small>
            </div>
            <button
              className="repository-button repository-button-quiet documentation-copy"
              type="button"
              onClick={() => void copyDocumentation()}
              disabled={!result.documentation.trim()}
            >
              {copyMessage === 'Markdown copied.' ? <Check size={13} /> : <Clipboard size={13} />}
              {copyMessage === 'Markdown copied.' ? 'Copied' : 'Copy Markdown'}
            </button>
          </div>

          {result.notice && (
            <div className="documentation-notice" role="status">
              <AlertCircle size={13} />
              <span>{result.notice}</span>
            </div>
          )}

          {result.limitations.length > 0 && (
            <div className="documentation-limitations">
              <strong>Limitations</strong>
              <ul>
                {result.limitations.map((limitation, index) => (
                  <li key={`${limitation}-${index}`}>{limitation}</li>
                ))}
              </ul>
            </div>
          )}

          {copyMessage && copyMessage !== 'Markdown copied.' && (
            <p className="documentation-copy-message" role="status">{copyMessage}</p>
          )}

          {result.documentation.trim() ? (
            <MarkdownPreview markdown={result.documentation} />
          ) : (
            <div className="documentation-empty" role="status">
              No documentation text was returned. Try generating it again.
            </div>
          )}
        </section>
      )}
    </section>
  )
}

export default RepositoryDocumentation
