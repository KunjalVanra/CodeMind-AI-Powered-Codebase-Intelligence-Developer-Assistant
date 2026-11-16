import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  BarChart3,
  Braces,
  Boxes,
  Code2,
  FileCode2,
  GitBranch,
  LoaderCircle,
  Package,
  RotateCcw,
  Unlink,
} from 'lucide-react'
import { ApiError, ApiNetworkError } from '../../api/client'
import {
  getRepositoryArchitecture,
  type ArchitectureAnalysisResponse,
} from '../../api/architecture'

type RepositoryArchitectureAnalyticsProps = {
  repositoryId: number
  accessToken: string | null
  onUnauthorized: () => void
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Your session has expired. Please sign in again.'
    if (error.status === 404) return 'Repository was not found or you no longer have access to it.'
    return error.message
  }
  if (error instanceof ApiNetworkError) return error.message
  return 'Architecture analytics could not be loaded. Please try again.'
}

function formatValue(value: number | null): string {
  return value === null ? '—' : value.toLocaleString()
}

function MetricCard({
  label,
  value,
  icon: Icon,
  detail,
}: {
  label: string
  value: number | null
  icon: typeof FileCode2
  detail?: string
}) {
  return (
    <article className="architecture-metric-card" title={detail}>
      <span className="architecture-metric-icon"><Icon size={16} aria-hidden="true" /></span>
      <span className="architecture-metric-label">{label}</span>
      <strong>{formatValue(value)}</strong>
      {detail && <span className="architecture-metric-detail">{detail}</span>}
    </article>
  )
}

function RepositoryArchitectureAnalytics({
  repositoryId,
  accessToken,
  onUnauthorized,
}: RepositoryArchitectureAnalyticsProps) {
  const [analysis, setAnalysis] = useState<ArchitectureAnalysisResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)
  const requestVersion = useRef(0)

  useEffect(() => {
    const requestId = ++requestVersion.current
    if (!accessToken) {
      onUnauthorized()
      return () => {
        requestVersion.current += 1
      }
    }

    void getRepositoryArchitecture(repositoryId, accessToken)
      .then((result) => {
        if (requestVersion.current === requestId) setAnalysis(result)
      })
      .catch((requestError: unknown) => {
        if (requestVersion.current !== requestId) return
        if (requestError instanceof ApiError && requestError.status === 401) {
          onUnauthorized()
        }
        setError(getErrorMessage(requestError))
      })
      .finally(() => {
        if (requestVersion.current === requestId) setIsLoading(false)
      })

    return () => {
      requestVersion.current += 1
    }
  }, [accessToken, onUnauthorized, repositoryId, retryCount])

  function retryArchitecture() {
    setIsLoading(true)
    setError(null)
    setRetryCount((current) => current + 1)
  }

  if (isLoading && accessToken) {
    return (
      <section className="analysis-result-section architecture-section" aria-labelledby="architecture-title">
        <div className="analysis-result-heading">
          <h4 id="architecture-title">Architecture analytics</h4>
        </div>
        <div className="architecture-state" role="status" aria-live="polite">
          <LoaderCircle size={16} className="spin-icon" />
          Loading repository architecture…
        </div>
      </section>
    )
  }

  if (!accessToken || error || !analysis) {
    return (
      <section className="analysis-result-section architecture-section" aria-labelledby="architecture-title">
        <div className="analysis-result-heading">
          <h4 id="architecture-title">Architecture analytics</h4>
        </div>
        <div className="architecture-error" role="alert">
          <AlertCircle size={15} aria-hidden="true" />
          <span>
            {!accessToken
              ? 'Your session has expired. Please sign in again.'
              : error ?? 'Architecture data is unavailable.'}
          </span>
          <button
            className="repository-button repository-button-quiet"
            type="button"
            onClick={retryArchitecture}
            disabled={isLoading}
          >
            <RotateCcw size={12} />
            Retry
          </button>
        </div>
      </section>
    )
  }

  const dependencyData = analysis.dependencies
  const languageEntries = Object.entries(analysis.languages)
    .sort(([, first], [, second]) => second.files - first.files)
  const largestLanguage = Math.max(0, ...languageEntries.map(([, item]) => item.files))
  const unresolvedFiles = analysis.top_dependency_files.filter(
    (file) => file.unresolved_imports > 0,
  )
  const unavailableMetrics = Object.entries(analysis.metrics_availability)
    .filter(([, metric]) => metric.status !== 'available')
  const isPartial = analysis.status !== 'complete' || unavailableMetrics.length > 0

  return (
    <section className="analysis-result-section architecture-section" aria-labelledby="architecture-title">
      <div className="analysis-result-heading architecture-heading">
        <div>
          <h4 id="architecture-title">Architecture analytics</h4>
          <p>Metrics from the repository’s persisted scan and parse results.</p>
        </div>
        <span className={`architecture-status architecture-status-${analysis.status}`}>
          {analysis.status}
        </span>
      </div>

      {isPartial && (
        <div className="architecture-partial-warning" role="status">
          <AlertCircle size={15} aria-hidden="true" />
          <div>
            <strong>Some metrics are incomplete or unavailable.</strong>
            <ul>
              {unavailableMetrics.map(([name, metric]) => (
                <li key={name}>
                  <span>{name.replaceAll('_', ' ')}</span>
                  {metric.detail && ` — ${metric.detail}`}
                </li>
              ))}
              {unavailableMetrics.length === 0 && (
                <li>One or more analysis stages did not return a complete result.</li>
              )}
            </ul>
          </div>
        </div>
      )}

      {analysis.status === 'unavailable' && (
        <div className="architecture-state architecture-empty" role="status">
          No completed architecture analysis is available yet. Run the repository scan and parse from the analysis workflow.
        </div>
      )}

      <div className="architecture-metrics">
        <MetricCard label="Source files" value={analysis.total_source_files} icon={FileCode2} />
        <MetricCard
          label="Physical source lines"
          value={analysis.total_lines_of_code}
          icon={Code2}
          detail="Scanner line count; includes comments and blank lines."
        />
        <MetricCard label="Classes" value={analysis.total_classes} icon={Boxes} />
        <MetricCard label="Functions" value={analysis.total_functions} icon={Braces} />
        <MetricCard label="Internal dependencies" value={dependencyData?.internal_dependencies ?? null} icon={GitBranch} />
        <MetricCard label="External dependencies" value={dependencyData?.external_dependencies ?? null} icon={Package} />
        <MetricCard label="Unresolved imports" value={dependencyData?.unresolved_imports ?? null} icon={Unlink} />
      </div>

      <div className="architecture-detail-grid">
        <section className="architecture-detail-card" aria-labelledby="architecture-languages-title">
          <h5 id="architecture-languages-title"><BarChart3 size={14} /> Language distribution</h5>
          {languageEntries.length > 0 ? (
            <ul className="architecture-language-list">
              {languageEntries.map(([language, statistics]) => {
                const width = largestLanguage > 0
                  ? Math.max(3, (statistics.files / largestLanguage) * 100)
                  : 0
                return (
                  <li key={language}>
                    <div className="architecture-language-copy">
                      <strong>{language}</strong>
                      <span>
                        {statistics.files.toLocaleString()} files · {statistics.lines.toLocaleString()} lines
                      </span>
                    </div>
                    <span className="architecture-language-track">
                      <span className="architecture-language-bar" style={{ width: `${width}%` }} />
                    </span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="architecture-empty-detail">No language distribution is available.</p>
          )}
        </section>

        <section className="architecture-detail-card" aria-labelledby="architecture-dependencies-title">
          <h5 id="architecture-dependencies-title"><GitBranch size={14} /> Dependency graph</h5>
          {dependencyData ? (
            <dl className="architecture-dependency-summary">
              <div><dt>Files</dt><dd>{dependencyData.total_files.toLocaleString()}</dd></div>
              <div><dt>Nodes</dt><dd>{dependencyData.nodes.toLocaleString()}</dd></div>
              <div><dt>Unique import edges</dt><dd>{dependencyData.edges.toLocaleString()}</dd></div>
              <div><dt>Metric</dt><dd>{analysis.dependency_metric.replaceAll('_', ' ')}</dd></div>
            </dl>
          ) : (
            <p className="architecture-empty-detail">Dependency metrics are unavailable.</p>
          )}
        </section>

        <section className="architecture-detail-card architecture-files-card" aria-labelledby="architecture-files-title">
          <h5 id="architecture-files-title"><FileCode2 size={14} /> Top files by dependency count</h5>
          {analysis.top_dependency_files.length > 0 ? (
            <ul className="architecture-file-list">
              {analysis.top_dependency_files.map((file) => (
                <li key={file.file_path}>
                  <code title={file.file_path}>{file.file_path}</code>
                  <span className="architecture-file-count">{file.dependency_count} dependencies</span>
                  <span className="architecture-file-breakdown">
                    {file.internal_dependencies} internal · {file.external_dependencies} external · {file.unresolved_imports} unresolved
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="architecture-empty-detail">No dependency-bearing files were returned.</p>
          )}
        </section>

        <section className="architecture-detail-card" aria-labelledby="architecture-imports-title">
          <h5 id="architecture-imports-title"><Unlink size={14} /> Unresolved import locations</h5>
          {unresolvedFiles.length > 0 ? (
            <>
              <ul className="architecture-file-list">
                {unresolvedFiles.map((file) => (
                  <li key={file.file_path}>
                    <code title={file.file_path}>{file.file_path}</code>
                    <span className="architecture-file-count">
                      {file.unresolved_imports.toLocaleString()} unresolved
                    </span>
                  </li>
                ))}
              </ul>
              <p className="architecture-footnote">
                File details are limited to the top dependency ranking; the total count above covers all graph edges.
              </p>
            </>
          ) : (
            <p className="architecture-empty-detail">
              {dependencyData?.unresolved_imports
                ? 'Unresolved imports exist, but none appear in the returned top dependency files.'
                : 'No unresolved imports were reported.'}
            </p>
          )}
        </section>

        <section className="architecture-detail-card architecture-files-card" aria-labelledby="architecture-high-count-title">
          <h5 id="architecture-high-count-title">
            High-count files <span>(thresholds: {analysis.high_dependency_threshold} dependencies, {analysis.high_import_threshold} imports)</span>
          </h5>
          <div className="architecture-high-count-grid">
            <div>
              <strong>Dependencies</strong>
              {analysis.files_with_high_dependency_counts.length > 0 ? (
                <ul className="architecture-file-list">
                  {analysis.files_with_high_dependency_counts.map((file) => (
                    <li key={file.file_path}>
                      <code title={file.file_path}>{file.file_path}</code>
                      <span className="architecture-file-count">{file.dependency_count}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="architecture-empty-detail">No files meet this threshold.</p>}
            </div>
            <div>
              <strong>Imports</strong>
              {analysis.files_with_high_import_counts.length > 0 ? (
                <ul className="architecture-file-list">
                  {analysis.files_with_high_import_counts.map((file) => (
                    <li key={file.file_path}>
                      <code title={file.file_path}>{file.file_path}</code>
                      <span className="architecture-file-count">{file.import_count}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="architecture-empty-detail">No files meet this threshold.</p>}
            </div>
          </div>
        </section>

        <section className="architecture-detail-card architecture-files-card" aria-labelledby="architecture-complexity-title">
          <h5 id="architecture-complexity-title">
            Most complex Python functions
            <span
              className="architecture-tooltip"
              title="Cyclomatic complexity is 1 plus decision points from conditions, loops, exceptions, boolean operators, comprehensions, and match cases."
              aria-label="Cyclomatic complexity metric definition"
              tabIndex={0}
            >
              ?
            </span>
          </h5>
          <p className="architecture-metric-caption">
            {analysis.complexity_metric ?? 'Complexity metric unavailable'}
          </p>
          {analysis.most_complex_python_functions.length > 0 ? (
            <ol className="architecture-function-list">
              {analysis.most_complex_python_functions.map((fn, index) => (
                <li key={`${fn.file_path}:${fn.start_line}:${fn.function_name}`}>
                  <span className="architecture-function-rank">{index + 1}</span>
                  <div>
                    <strong>{fn.function_name} · {fn.cyclomatic_complexity}</strong>
                    <code title={fn.file_path}>{fn.file_path}:{fn.start_line}-{fn.end_line}</code>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className="architecture-empty-detail">
              No Python function complexity values were returned. Check the complexity metric availability above.
            </p>
          )}
        </section>
      </div>

      <section className="architecture-summary-card" aria-labelledby="architecture-summary-title">
        <h5 id="architecture-summary-title">Architecture summary</h5>
        {analysis.architecture_summary.length > 0 ? (
          <ul>{analysis.architecture_summary.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}</ul>
        ) : (
          <p className="architecture-empty-detail">No summary could be derived from the available analysis data.</p>
        )}
      </section>

      {Object.keys(analysis.metrics_availability).length > 0 && (
        <section className="architecture-availability" aria-label="Metric availability">
          <h5>Metric availability</h5>
          <ul>
            {Object.entries(analysis.metrics_availability).map(([name, metric]) => (
              <li key={name}>
                <span className={`architecture-availability-status is-${metric.status}`} />
                <strong>{name.replaceAll('_', ' ')}</strong>
                <span className="architecture-availability-label">{metric.status}</span>
                {metric.detail && <small>{metric.detail}</small>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  )
}

export default RepositoryArchitectureAnalytics
