import { useCallback, useRef, useState } from 'react'
import {
  AlertCircle,
  Check,
  CheckCircle2,
  Circle,
  Code2,
  FileCode2,
  Files,
  Layers,
  LoaderCircle,
  RotateCcw,
  ScanSearch,
} from 'lucide-react'
import { ApiError, ApiNetworkError } from '../../api/client'
import {
  getRepositoryDependencies,
  type DependencyGraphResponse,
} from '../../api/dependencies'
import {
  indexRepository,
  parseRepository,
  scanRepository,
  type ParseLanguageStatistics,
  type RepositoryIndexingResponse,
  type RepositoryParseResponse,
  type RepositoryScanResponse,
} from '../../api/analyses'
import RepositoryDependencyGraph from './RepositoryDependencyGraph'
import RepositoryArchitectureAnalytics from './RepositoryArchitectureAnalytics'
import RepositoryDocumentation from './RepositoryDocumentation'
import RepositorySecurityAnalysis from './RepositorySecurityAnalysis'
import RepositoryTestGeneration from './RepositoryTestGeneration'

type AnalysisStep = 'scan' | 'parse' | 'index'

type RepositoryAnalysisPanelProps = {
  repositoryId: number
  accessToken: string | null
  isOpen: boolean
  onBusyChange: (isBusy: boolean) => void
  onUnauthorized: () => void
}

type StepError = {
  step: AnalysisStep
  message: string
}

const stepLabels: Record<AnalysisStep, string> = {
  scan: 'Scan',
  parse: 'Parse',
  index: 'Index',
}

const runningLabels: Record<AnalysisStep, string> = {
  scan: 'Scanning',
  parse: 'Parsing',
  index: 'Indexing',
}

const steps: AnalysisStep[] = ['scan', 'parse', 'index']

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Your session has expired. Please sign in again.'
    if (error.status === 404) {
      return 'Repository was not found or you no longer have access to it.'
    }
    return error.message
  }
  if (error instanceof ApiNetworkError) return error.message
  return 'Analysis could not be completed. Please try again.'
}

function sumLanguageStatistic(
  languages: Record<string, ParseLanguageStatistics>,
  key: keyof ParseLanguageStatistics,
): number {
  return Object.values(languages).reduce(
    (total, language) => total + (language[key] ?? 0),
    0,
  )
}

function parseTotals(result: RepositoryParseResponse) {
  const hasLanguageStats = Object.keys(result.languages).length > 0

  return {
    totalFiles: hasLanguageStats
      ? sumLanguageStatistic(result.languages, 'total_files')
      : result.total_python_files,
    parsedFiles: hasLanguageStats
      ? sumLanguageStatistic(result.languages, 'successfully_parsed_files')
      : result.successfully_parsed_files,
    syntaxErrors: hasLanguageStats
      ? sumLanguageStatistic(result.languages, 'syntax_error_files')
      : result.syntax_error_files,
    classes: hasLanguageStats
      ? sumLanguageStatistic(result.languages, 'total_classes')
      : result.total_classes,
    interfaces: sumLanguageStatistic(result.languages, 'total_interfaces'),
    functions: hasLanguageStats
      ? sumLanguageStatistic(result.languages, 'total_functions')
      : result.total_functions,
    imports: hasLanguageStats
      ? sumLanguageStatistic(result.languages, 'total_imports')
      : result.total_imports,
  }
}

function Metric({
  label,
  value,
  icon,
}: {
  label: string
  value: number
  icon: typeof Files
}) {
  const Icon = icon
  return (
    <div className="analysis-metric">
      <span className="analysis-metric-icon"><Icon size={15} /></span>
      <span className="analysis-metric-label">{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  )
}

function RepositoryAnalysisPanel({
  repositoryId,
  accessToken,
  isOpen,
  onBusyChange,
  onUnauthorized,
}: RepositoryAnalysisPanelProps) {
  const [nextStep, setNextStep] = useState<AnalysisStep | null>('scan')
  const [runningStep, setRunningStep] = useState<AnalysisStep | null>(null)
  const [error, setError] = useState<StepError | null>(null)
  const [scanResult, setScanResult] = useState<RepositoryScanResponse | null>(null)
  const [parseResult, setParseResult] = useState<RepositoryParseResponse | null>(null)
  const [indexResult, setIndexResult] = useState<RepositoryIndexingResponse | null>(null)
  const [dependencyGraph, setDependencyGraph] =
    useState<DependencyGraphResponse | null>(null)
  const [dependencyGraphLoading, setDependencyGraphLoading] = useState(false)
  const [dependencyGraphError, setDependencyGraphError] = useState<string | null>(null)
  const requestLock = useRef(false)
  const dependencyRequestLock = useRef(false)
  const dependencyRequestVersion = useRef(0)

  const loadDependencyGraph = useCallback(async () => {
    if (dependencyRequestLock.current) return
    if (!accessToken) {
      onUnauthorized()
      setDependencyGraphError('Your session has expired. Please sign in again.')
      return
    }

    dependencyRequestLock.current = true
    const requestVersion = ++dependencyRequestVersion.current
    setDependencyGraphLoading(true)
    setDependencyGraphError(null)
    try {
      const result = await getRepositoryDependencies(repositoryId, accessToken)
      if (dependencyRequestVersion.current !== requestVersion) return
      setDependencyGraph(result)
    } catch (requestError) {
      if (dependencyRequestVersion.current !== requestVersion) return
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized()
      }
      setDependencyGraphError(getErrorMessage(requestError))
    } finally {
      if (dependencyRequestVersion.current === requestVersion) {
        dependencyRequestLock.current = false
        setDependencyGraphLoading(false)
      }
    }
  }, [accessToken, onUnauthorized, repositoryId])

  if (!isOpen) return null

  const completedSteps: Record<AnalysisStep, boolean> = {
    scan: scanResult !== null,
    parse: parseResult !== null,
    index: indexResult?.status === 'indexed' && indexResult.failed_chunks === 0,
  }
  const currentStatus = runningStep
    ? `${stepLabels[runningStep]} in progress`
    : error
      ? `${stepLabels[error.step]} needs attention`
      : nextStep
        ? `${stepLabels[nextStep]} ready`
        : 'Analysis complete'

  async function runCurrentStep(step: AnalysisStep) {
    if (requestLock.current || nextStep !== step) return
    if (!accessToken) {
      onUnauthorized()
      setError({ step, message: 'Your session has expired. Please sign in again.' })
      return
    }

    requestLock.current = true
    setRunningStep(step)
    setError(null)
    onBusyChange(true)

    try {
      if (step === 'scan') {
        const result = await scanRepository(repositoryId, accessToken)
        setScanResult(result)
        if (result.status === 'completed') {
          setNextStep('parse')
        } else {
          setError({
            step: 'scan',
            message: 'Scan did not complete successfully. Retry the scan step.',
          })
        }
      } else if (step === 'parse') {
        const result = await parseRepository(repositoryId, accessToken)
        setParseResult(result)
        if (result.status === 'completed') {
          setNextStep('index')
          void loadDependencyGraph()
        } else {
          setError({
            step: 'parse',
            message: 'Parsing did not complete successfully. Retry the parse step.',
          })
        }
      } else {
        const result = await indexRepository(repositoryId, accessToken)
        setIndexResult(result)
        if (result.status === 'indexed' && result.failed_chunks === 0) {
          setNextStep(null)
        } else {
          setNextStep('index')
          setError({
            step: 'index',
            message:
              result.failed_chunks > 0
                ? `Indexing completed with ${result.failed_chunks.toLocaleString()} failed chunk${result.failed_chunks === 1 ? '' : 's'}. Retry indexing to try again.`
                : 'Indexing did not complete successfully. Retry the indexing step.',
          })
        }
      }
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        onUnauthorized()
      }
      setError({ step, message: getErrorMessage(requestError) })
    } finally {
      requestLock.current = false
      setRunningStep(null)
      onBusyChange(false)
    }
  }

  function restartAnalysis() {
    if (requestLock.current) return
    dependencyRequestVersion.current += 1
    dependencyRequestLock.current = false
    setNextStep('scan')
    setError(null)
    setScanResult(null)
    setParseResult(null)
    setIndexResult(null)
    setDependencyGraph(null)
    setDependencyGraphLoading(false)
    setDependencyGraphError(null)
  }

  const parsingTotals = parseResult ? parseTotals(parseResult) : null
  const hasIndexingResult = indexResult !== null

  return (
    <section className="repository-analysis-panel" aria-label="Repository analysis">
      <div className="analysis-panel-heading">
        <div>
          <div className="analysis-panel-title">
            <ScanSearch size={16} />
            <h3>Repository analysis</h3>
          </div>
          <p>Scan the repository, parse its source, then index code chunks.</p>
        </div>
        <div className="analysis-current-status" role="status" aria-live="polite">
          {runningStep ? (
            <LoaderCircle size={14} className="spin-icon" />
          ) : nextStep === null ? (
            <CheckCircle2 size={14} />
          ) : (
            <Circle size={12} />
          )}
          {currentStatus}
        </div>
      </div>

      <div className="analysis-workflow">
        {steps.map((step, index) => {
          const isCurrent = nextStep === step
          const isRunning = runningStep === step
          const isFailed = error?.step === step
          const isComplete = completedSteps[step]
          const isWaiting = !isComplete && !isCurrent

          return (
            <div
              className={`analysis-workflow-step${isComplete ? ' is-complete' : ''}${isCurrent ? ' is-current' : ''}${isFailed ? ' is-failed' : ''}`}
              key={step}
            >
              <div className="analysis-step-copy">
                <span className="analysis-step-icon">
                  {isRunning ? (
                    <LoaderCircle size={15} className="spin-icon" />
                  ) : isComplete ? (
                    <Check size={15} />
                  ) : (
                    <span>{index + 1}</span>
                  )}
                </span>
                <div>
                  <strong>{stepLabels[step]}</strong>
                  <span>
                    {isComplete
                      ? 'Completed'
                      : isRunning
                        ? 'Working…'
                        : isFailed
                          ? 'Needs retry'
                          : isWaiting
                            ? 'Waiting for previous step'
                            : 'Ready to run'}
                  </span>
                </div>
              </div>
              {isCurrent && (
                <button
                  className="repository-button repository-button-quiet analysis-run-button"
                  type="button"
                  onClick={() => void runCurrentStep(step)}
                  disabled={runningStep !== null}
                >
                  {isRunning ? (
                    <>
                      <LoaderCircle size={14} className="spin-icon" />
                      {runningLabels[step]}…
                    </>
                  ) : isFailed ? (
                    <>
                      <RotateCcw size={13} />
                      Retry {step.toLowerCase()}
                    </>
                  ) : (
                    `Run ${step.toLowerCase()}`
                  )}
                </button>
              )}
            </div>
          )
        })}
      </div>

      {error && (
        <div className="analysis-error" role="alert">
          <AlertCircle size={16} />
          <span>{error.message}</span>
        </div>
      )}

      {scanResult && (
        <section className="analysis-result-section" aria-labelledby="scan-results-title">
          <div className="analysis-result-heading">
            <h4 id="scan-results-title">Scan summary</h4>
            <span>{scanResult.status}</span>
          </div>
          <div className="analysis-metrics">
            <Metric label="Total files" value={scanResult.total_files} icon={Files} />
            <Metric label="Source files" value={scanResult.total_source_files} icon={FileCode2} />
            <Metric label="Lines of code" value={scanResult.total_lines} icon={Code2} />
          </div>
          <div className="analysis-detail-grid">
            <div className="analysis-detail-card">
              <h5>Languages</h5>
              {Object.entries(scanResult.languages).length > 0 ? (
                <ul className="analysis-language-list">
                  {Object.entries(scanResult.languages)
                    .sort(([, first], [, second]) => second.files - first.files)
                    .map(([language, statistics]) => (
                      <li key={language}>
                        <strong>{language}</strong>
                        <span>
                          {statistics.files.toLocaleString()} files · {statistics.lines.toLocaleString()} lines
                        </span>
                      </li>
                    ))}
                </ul>
              ) : (
                <p className="analysis-empty-detail">No language statistics were returned.</p>
              )}
            </div>
            <div className="analysis-detail-card">
              <h5>Important files</h5>
              {scanResult.important_files.length > 0 ? (
                <ul className="analysis-important-files">
                  {scanResult.important_files.slice(0, 6).map((file) => (
                    <li key={file}><code>{file}</code></li>
                  ))}
                </ul>
              ) : (
                <p className="analysis-empty-detail">No important files were identified.</p>
              )}
              {scanResult.important_files.length > 6 && (
                <p className="analysis-more-files">
                  And {(scanResult.important_files.length - 6).toLocaleString()} more.
                </p>
              )}
            </div>
          </div>
        </section>
      )}

      {parseResult && parsingTotals && (
        <section className="analysis-result-section" aria-labelledby="parse-results-title">
          <div className="analysis-result-heading">
            <h4 id="parse-results-title">Parse summary</h4>
            <span>{parseResult.status}</span>
          </div>
          <div className="analysis-metrics analysis-parse-metrics">
            <Metric label="Total files" value={parsingTotals.totalFiles} icon={Files} />
            <Metric label="Parsed files" value={parsingTotals.parsedFiles} icon={FileCode2} />
            <Metric label="Classes" value={parsingTotals.classes} icon={Code2} />
            <Metric label="Functions" value={parsingTotals.functions} icon={Code2} />
            <Metric label="Interfaces" value={parsingTotals.interfaces} icon={Code2} />
            <Metric label="Imports" value={parsingTotals.imports} icon={Layers} />
            <Metric label="Syntax errors" value={parsingTotals.syntaxErrors} icon={AlertCircle} />
            <Metric label="Code chunks" value={parseResult.chunk_count} icon={Layers} />
          </div>
          <div className="analysis-detail-card">
            <h5>Parsed languages</h5>
            {Object.entries(parseResult.languages).length > 0 ? (
              <ul className="analysis-language-list">
                {Object.entries(parseResult.languages)
                  .sort(([first], [second]) => first.localeCompare(second))
                  .map(([language, statistics]) => (
                    <li key={language}>
                      <strong>{language}</strong>
                      <span>
                        {(statistics.successfully_parsed_files ?? 0).toLocaleString()} / {(statistics.total_files ?? 0).toLocaleString()} files · {(statistics.total_classes ?? 0).toLocaleString()} classes · {(statistics.total_functions ?? 0).toLocaleString()} functions
                      </span>
                    </li>
                  ))}
              </ul>
            ) : (
              <p className="analysis-empty-detail">No language parse statistics were returned.</p>
            )}
          </div>
        </section>
      )}

      {parseResult && (
        <RepositoryDependencyGraph
          graph={dependencyGraph}
          isLoading={dependencyGraphLoading}
          error={dependencyGraphError}
          onRetry={() => void loadDependencyGraph()}
        />
      )}

      {parseResult && (
        <RepositoryArchitectureAnalytics
          repositoryId={repositoryId}
          accessToken={accessToken}
          onUnauthorized={onUnauthorized}
        />
      )}

      {hasIndexingResult && (
        <section className="analysis-result-section" aria-labelledby="index-results-title">
          <div className="analysis-result-heading">
            <h4 id="index-results-title">Index summary</h4>
            <span className={indexResult.status === 'indexed' ? 'analysis-result-good' : 'analysis-result-warning'}>
              {indexResult.status.replaceAll('_', ' ')}
            </span>
          </div>
          <div className="analysis-metrics">
            <Metric label="Total chunks" value={indexResult.total_chunks} icon={Layers} />
            <Metric label="Indexed" value={indexResult.indexed_chunks} icon={CheckCircle2} />
            <Metric label="Failed" value={indexResult.failed_chunks} icon={AlertCircle} />
          </div>
        </section>
      )}

      <RepositorySecurityAnalysis
        repositoryId={repositoryId}
        accessToken={accessToken}
        onUnauthorized={onUnauthorized}
      />

      <RepositoryDocumentation
        initialRepositoryId={repositoryId}
        accessToken={accessToken}
        onUnauthorized={onUnauthorized}
      />

      <RepositoryTestGeneration
        initialRepositoryId={repositoryId}
        accessToken={accessToken}
        onUnauthorized={onUnauthorized}
      />

      {nextStep === null && (
        <button
          className="repository-button repository-button-quiet analysis-restart-button"
          type="button"
          onClick={restartAnalysis}
        >
          <RotateCcw size={13} />
          Run analysis again
        </button>
      )}
    </section>
  )
}

export default RepositoryAnalysisPanel
