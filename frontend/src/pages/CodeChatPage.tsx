import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  AlertCircle,
  Bot,
  FileCode2,
  LoaderCircle,
  MessageSquare,
  RotateCcw,
  Send,
  Trash2,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { ApiError, ApiNetworkError } from '../api/client'
import {
  askRepository,
  type CodeCitation,
} from '../api/assistant'
import {
  listRepositories,
  type Repository,
} from '../api/repositories'
import { useAuth } from '../auth/useAuth'

type ChatTurn = {
  id: string
  question: string
  repositoryId: number
  repositoryLabel: string
  answer: string | null
  citations: CodeCitation[]
  model: string | null
  error: string | null
}

const QUESTION_MAX_LENGTH = 2000
const DEFAULT_TOP_K = 5

function assistantErrorMessage(error: unknown): string {
  if (error instanceof ApiNetworkError) return error.message
  if (!(error instanceof ApiError)) {
    return 'The assistant could not answer. Please try again.'
  }

  switch (error.status) {
    case 401:
      return 'Your session has expired. Please sign in again.'
    case 403:
      return `You do not have permission to ask about this repository. ${error.message}`
    case 404:
      return 'This repository was not found or is no longer available.'
    case 409:
      return `${error.message}. Check that the repository is indexed, then try again.`
    case 422:
      return error.message || 'The question could not be accepted. Check its length and try again.'
    case 429:
      return 'The assistant is receiving too many requests. Wait a moment and try again.'
    case 503:
      return error.message || 'The assistant is temporarily unavailable. Please try again later.'
    default:
      return error.message
  }
}

function repositoryLoadErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return 'Your session has expired. Please sign in again.'
  }
  if (error instanceof ApiError && error.status === 403) {
    return `Repository access was denied. ${error.message}`
  }
  if (error instanceof ApiError && error.status === 404) {
    return 'The repository list is no longer available.'
  }
  if (error instanceof ApiNetworkError) return error.message
  if (error instanceof ApiError) return error.message
  return 'Repositories could not be loaded. Please try again.'
}

function CodeChatPage() {
  const { accessToken, logout } = useAuth()
  const [repositories, setRepositories] = useState<Repository[] | null>(null)
  const [selectedRepositoryId, setSelectedRepositoryId] = useState('')
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<ChatTurn[]>([])
  const [isLoadingRepositories, setIsLoadingRepositories] = useState(true)
  const [repositoryError, setRepositoryError] = useState<string | null>(null)
  const [composerError, setComposerError] = useState<string | null>(null)
  const [pendingTurnId, setPendingTurnId] = useState<string | null>(null)
  const requestLock = useRef(false)
  const turnCounter = useRef(0)
  const conversationRef = useRef<HTMLDivElement>(null)

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
        if (error instanceof ApiError && error.status === 401) logout()
        setRepositoryError(repositoryLoadErrorMessage(error))
      })
      .finally(() => {
        if (isActive) setIsLoadingRepositories(false)
      })

    return () => {
      isActive = false
    }
  }, [accessToken, fetchUserRepositories, logout])

  useEffect(() => {
    const conversation = conversationRef.current
    if (conversation) {
      conversation.scrollTo({
        top: conversation.scrollHeight,
        behavior: 'smooth',
      })
    }
  }, [messages, pendingTurnId])

  const selectedRepository = repositories?.find(
    (repository) => String(repository.id) === selectedRepositoryId,
  )

  async function reloadRepositories() {
    if (isLoadingRepositories) return
    setRepositoryError(null)
    setIsLoadingRepositories(true)
    try {
      setRepositories(await fetchUserRepositories())
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) logout()
      setRepositoryError(repositoryLoadErrorMessage(error))
    } finally {
      setIsLoadingRepositories(false)
    }
  }

  async function requestAnswer(turn: ChatTurn) {
    if (requestLock.current) return
    if (!accessToken) {
      logout()
      setMessages((current) =>
        current.map((item) =>
          item.id === turn.id
            ? { ...item, error: 'Your session has expired. Please sign in again.' }
            : item,
        ),
      )
      return
    }

    requestLock.current = true
    setPendingTurnId(turn.id)
    setComposerError(null)
    setMessages((current) =>
      current.map((item) =>
        item.id === turn.id
          ? { ...item, answer: null, citations: [], model: null, error: null }
          : item,
      ),
    )

    try {
      const response = await askRepository(
        turn.repositoryId,
        { question: turn.question, top_k: DEFAULT_TOP_K },
        accessToken,
      )
      const answer = response.answer.trim()
      setMessages((current) =>
        current.map((item) =>
          item.id === turn.id
            ? answer
              ? {
                  ...item,
                  answer,
                  citations: response.citations,
                  model: response.model,
                  error: null,
                }
              : {
                  ...item,
                  error: 'The assistant returned an empty answer. Please try again.',
                }
            : item,
        ),
      )
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) logout()
      setMessages((current) =>
        current.map((item) =>
          item.id === turn.id
            ? { ...item, error: assistantErrorMessage(error) }
            : item,
        ),
      )
    } finally {
      requestLock.current = false
      setPendingTurnId(null)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (requestLock.current || isLoadingRepositories) return
    if (!selectedRepository) {
      setComposerError('Select a repository before asking a question.')
      return
    }

    const normalizedQuestion = question.trim()
    if (
      !normalizedQuestion ||
      normalizedQuestion.length > QUESTION_MAX_LENGTH
    ) {
      setComposerError('Enter a question between 1 and 2000 characters.')
      return
    }

    const turn: ChatTurn = {
      id: `${Date.now()}-${turnCounter.current++}`,
      question: normalizedQuestion,
      repositoryId: selectedRepository.id,
      repositoryLabel: `${selectedRepository.owner_name}/${selectedRepository.name}`,
      answer: null,
      citations: [],
      model: null,
      error: null,
    }
    setMessages((current) => [...current, turn])
    setQuestion('')
    setComposerError(null)
    await requestAnswer(turn)
  }

  function clearConversation() {
    if (requestLock.current) return
    setMessages([])
    setComposerError(null)
  }

  return (
    <section className="code-chat-page page-enter">
      <header className="code-chat-heading">
        <div>
          <span className="eyebrow"><span className="eyebrow-line" />Codebase intelligence</span>
          <h1>AI Assistant</h1>
          <p>Ask questions about your repository and inspect the code citations behind each answer.</p>
        </div>
        {messages.length > 0 && (
          <button
            className="repository-button repository-button-quiet code-chat-clear"
            type="button"
            onClick={clearConversation}
            disabled={pendingTurnId !== null}
          >
            <Trash2 size={14} />
            Clear conversation
          </button>
        )}
      </header>

      <section className="code-chat-workspace" aria-label="Repository assistant">
        <div className="code-chat-repository-bar">
          <label className="form-field" htmlFor="assistant-repository">
            <span>Repository</span>
            <select
              id="assistant-repository"
              value={selectedRepositoryId}
              onChange={(event) => {
                setSelectedRepositoryId(event.target.value)
                setComposerError(null)
              }}
              disabled={isLoadingRepositories || !repositories?.length || pendingTurnId !== null}
            >
              <option value="">
                {isLoadingRepositories ? 'Loading repositories…' : 'Select a repository'}
              </option>
              {repositories?.map((repository) => (
                <option key={repository.id} value={repository.id}>
                  {repository.owner_name}/{repository.name}
                </option>
              ))}
            </select>
          </label>

          <div className="code-chat-selected-repository" role="status">
            <span className="code-chat-selected-dot" />
            <span>
              {selectedRepository
                ? `Selected: ${selectedRepository.owner_name}/${selectedRepository.name}`
                : 'No repository selected'}
            </span>
          </div>
        </div>

        {repositoryError && (
          <div className="code-chat-alert" role="alert">
            <AlertCircle size={16} />
            <span>{repositoryError}</span>
            <button
              className="repository-button repository-button-quiet"
              type="button"
              onClick={() => void reloadRepositories()}
              disabled={isLoadingRepositories}
            >
              Retry
            </button>
          </div>
        )}

        {!isLoadingRepositories && !repositoryError && repositories?.length === 0 && (
          <div className="code-chat-empty-repositories">
            <FileCode2 size={18} />
            <div>
              <strong>No repositories connected</strong>
              <p>Connect a repository before asking codebase questions.</p>
            </div>
            <Link to="/repositories">Manage repositories</Link>
          </div>
        )}

        <div
          className="code-chat-conversation"
          ref={conversationRef}
          aria-live="polite"
          aria-label="Conversation"
        >
          {messages.length === 0 ? (
            <div className="code-chat-welcome">
              <span className="code-chat-welcome-icon"><MessageSquare size={20} /></span>
              <h2>Ask about your codebase</h2>
              <p>
                Choose an indexed repository, then ask a question. Answers and
                citations are based on retrieved code context.
              </p>
            </div>
          ) : (
            <div className="code-chat-message-list">
              {messages.map((turn) => (
                <article className="code-chat-turn" key={turn.id}>
                  <div className="code-chat-user-message">
                    <span className="code-chat-message-label">You</span>
                    <p>{turn.question}</p>
                    <span className="code-chat-turn-repository">{turn.repositoryLabel}</span>
                  </div>

                  <div className="code-chat-assistant-message">
                    <div className="code-chat-assistant-label">
                      <span className="code-chat-assistant-icon"><Bot size={14} /></span>
                      <span>CodeMind</span>
                      {turn.model && <span className="code-chat-model">{turn.model}</span>}
                    </div>

                    {turn.error ? (
                      <div className="code-chat-answer-error" role="alert">
                        <AlertCircle size={15} />
                        <span>{turn.error}</span>
                        <button
                          className="code-chat-retry"
                          type="button"
                          onClick={() => void requestAnswer(turn)}
                          disabled={pendingTurnId !== null}
                        >
                          <RotateCcw size={13} />
                          Retry
                        </button>
                      </div>
                    ) : pendingTurnId === turn.id ? (
                      <div className="code-chat-thinking" role="status">
                        <LoaderCircle size={15} className="spin-icon" />
                        <span>Waiting for the assistant…</span>
                      </div>
                    ) : turn.answer ? (
                      <>
                        <div className="code-chat-answer">{turn.answer}</div>
                        {turn.citations.length > 0 ? (
                          <div className="code-chat-citations">
                            <h3>Citations</h3>
                            <ul>
                              {turn.citations.map((citation) => (
                                <li key={citation.reference_id}>
                                  <span className="code-chat-citation-reference">
                                    {citation.reference_id}
                                  </span>
                                  <div className="code-chat-citation-content">
                                    <code className="code-chat-citation-path">
                                      {citation.file_path}
                                    </code>
                                    <div className="code-chat-citation-meta">
                                      <span>{citation.language}</span>
                                      {citation.symbol && <span>{citation.symbol}</span>}
                                      <span>Lines {citation.start_line}–{citation.end_line}</span>
                                    </div>
                                  </div>
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : (
                          <p className="code-chat-no-citations">
                            No citations were returned for this answer.
                          </p>
                        )}
                      </>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        <form className="code-chat-composer" onSubmit={(event) => void handleSubmit(event)}>
          {selectedRepository && (
            <div className="code-chat-composer-context">
              Asking about <strong>{selectedRepository.owner_name}/{selectedRepository.name}</strong>
            </div>
          )}
          {composerError && (
            <div className="code-chat-composer-error" role="alert">
              <AlertCircle size={14} />
              {composerError}
            </div>
          )}
          <label className="visually-hidden" htmlFor="assistant-question">
            Ask a question about the selected repository
          </label>
          <textarea
            id="assistant-question"
            value={question}
            onChange={(event) => {
              setQuestion(event.target.value)
              setComposerError(null)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            placeholder={
              selectedRepository
                ? 'Ask a question about this codebase…'
                : 'Select a repository to start asking…'
            }
            maxLength={QUESTION_MAX_LENGTH}
            rows={2}
            disabled={
              !selectedRepository ||
              isLoadingRepositories ||
              repositoryError !== null ||
              pendingTurnId !== null
            }
            required
          />
          <div className="code-chat-composer-footer">
            <span>
              Enter to send · Shift+Enter for a new line · {question.length}/{QUESTION_MAX_LENGTH}
            </span>
            <button
              className="repository-button repository-button-primary"
              type="submit"
              disabled={
                !selectedRepository ||
                isLoadingRepositories ||
                repositoryError !== null ||
                pendingTurnId !== null ||
                !question.trim() ||
                !accessToken
              }
            >
              {pendingTurnId !== null ? (
                <>
                  <LoaderCircle size={14} className="spin-icon" />
                  Thinking…
                </>
              ) : (
                <>
                  <Send size={14} />
                  Send
                </>
              )}
            </button>
          </div>
        </form>

        <p className="code-chat-history-note">
          This conversation is kept only while this page is open; it is not saved as persistent history.
        </p>
      </section>
    </section>
  )
}

export default CodeChatPage
