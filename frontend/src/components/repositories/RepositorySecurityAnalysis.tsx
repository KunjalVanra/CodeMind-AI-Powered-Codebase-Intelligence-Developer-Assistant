import { useRef, useState } from 'react'
import {
  AlertCircle,
  LoaderCircle,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react'
import { ApiError, ApiNetworkError } from '../../api/client'
import {
  runRepositorySecurityScan,
  type SecurityFinding,
  type SecurityScanResponse,
  type SecuritySeverity,
} from '../../api/security'

type RepositorySecurityAnalysisProps = {
  repositoryId: number
  accessToken: string | null
  onUnauthorized: () => void
}

type SeverityFilter = 'all' | SecuritySeverity

const severities: SecuritySeverity[] = [
  'critical',
  'high',
  'medium',
  'low',
  'informational',
]

const severityLabels: Record<SecuritySeverity, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  informational: 'Informational',
}

function isSecuritySeverity(value: string): value is SecuritySeverity {
  return severities.some((severity) => severity === value)
}

function getSecurityErrorMessage(error: unknown): string {
  if (error instanceof ApiNetworkError) return error.message
  if (!(error instanceof ApiError)) {
    return 'The security scan could not be completed. Please try again.'
  }

  switch (error.status) {
    case 401:
      return 'Your session has expired. Please sign in again.'
    case 403:
      return `You do not have permission to scan this repository. ${error.message}`
    case 404:
      return 'Repository was not found or you no longer have access to it.'
    case 409:
      return `Clone the repository before running a security scan. ${error.message}`
    case 503:
      return 'Security scanning is unavailable because Semgrep is not installed on the backend. Install Semgrep on the backend before running real scans.'
    default:
      return error.message
  }
}

function FindingCard({ finding }: { finding: SecurityFinding }) {
  return (
    <article className={`security-finding security-finding-${finding.severity}`}>
      <div className="security-finding-header">
        <div className="security-finding-tags">
          <span className={`security-severity security-severity-${finding.severity}`}>
            {severityLabels[finding.severity]}
          </span>
          <code>{finding.rule_id}</code>
        </div>
        <span className="security-finding-lines">
          Lines {finding.start_line}–{finding.end_line}
        </span>
      </div>
      <h5>{finding.title}</h5>
      <p className="security-finding-message">{finding.message}</p>
      <code className="security-finding-path">{finding.file_path}</code>
      {finding.code_snippet && (
        <div className="security-finding-code">
          <strong>Relevant code</strong>
          <pre><code>{finding.code_snippet}</code></pre>
        </div>
      )}
      {finding.remediation && (
        <div className="security-finding-remediation">
          <strong>Remediation</strong>
          <p>{finding.remediation}</p>
        </div>
      )}
    </article>
  )
}

function RepositorySecurityAnalysis({
  repositoryId,
  accessToken,
  onUnauthorized,
}: RepositorySecurityAnalysisProps) {
  const [result, setResult] = useState<SecurityScanResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<SeverityFilter>('all')
  const requestLock = useRef(false)

  async function runScan() {
    if (requestLock.current || isLoading) return
    if (!accessToken) {
      onUnauthorized()
      setError('Your session has expired. Please sign in again.')
      return
    }

    requestLock.current = true
    setIsLoading(true)
    setError(null)
    setResult(null)
    setFilter('all')
    try {
      const scanResult = await runRepositorySecurityScan(repositoryId, accessToken)
      if (scanResult.status !== 'completed') {
        setError('The security scan did not complete successfully. Please retry.')
        return
      }
      setResult(scanResult)
    } catch (scanError) {
      if (scanError instanceof ApiError && scanError.status === 401) {
        onUnauthorized()
      }
      setError(getSecurityErrorMessage(scanError))
    } finally {
      requestLock.current = false
      setIsLoading(false)
    }
  }

  const filteredFindings =
    result?.findings.filter(
      (finding) => filter === 'all' || finding.severity === filter,
    ) ?? []

  return (
    <section className="analysis-result-section security-analysis-section" aria-labelledby="security-analysis-title">
      <div className="analysis-result-heading">
        <div className="security-section-title">
          <ShieldAlert size={14} />
          <h4 id="security-analysis-title">Security analysis</h4>
        </div>
        <span>Static scan</span>
      </div>

      <p className="security-scan-intro">
        Run Semgrep to check this repository for security findings. Semgrep must
        be installed on the backend for real scans to run.
      </p>

      <button
        className="repository-button repository-button-quiet security-scan-button"
        type="button"
        onClick={() => void runScan()}
        disabled={isLoading}
      >
        {isLoading ? (
          <>
            <LoaderCircle size={14} className="spin-icon" />
            Scanning…
          </>
        ) : result ? (
          <>
            <RotateCcw size={13} />
            Run Security Scan Again
          </>
        ) : (
          <>
            <ShieldAlert size={14} />
            Run Security Scan
          </>
        )}
      </button>

      {isLoading && (
        <div className="security-scan-status" role="status" aria-live="polite">
          <LoaderCircle size={15} className="spin-icon" />
          Running static security analysis…
        </div>
      )}

      {error && (
        <div className="security-scan-error" role="alert">
          <AlertCircle size={15} aria-hidden="true" />
          <span>{error}</span>
          <button
            className="repository-button repository-button-quiet"
            type="button"
            onClick={() => void runScan()}
            disabled={isLoading}
          >
            <RotateCcw size={12} />
            Retry
          </button>
        </div>
      )}

      {result && (
        <>
          <div className="security-scan-meta" role="status">
            <ShieldCheck size={14} />
            <span>
              {result.scanner} scanned {result.scanned_files.toLocaleString()} files
              {result.skipped_files > 0 &&
                ` · ${result.skipped_files.toLocaleString()} skipped`}
            </span>
          </div>

          <div className="security-severity-summary" aria-label="Findings by severity">
            {severities.map((severity) => (
              <div
                className={`security-summary-card security-summary-${severity}`}
                key={severity}
              >
                <span>{severityLabels[severity]}</span>
                <strong>{result.summary[severity].toLocaleString()}</strong>
              </div>
            ))}
          </div>

          {result.total_findings === 0 ? (
            <div className="security-empty-state" role="status">
              <ShieldCheck size={17} />
              <div>
                <strong>No findings returned</strong>
                <p>Semgrep returned no findings for this scan.</p>
              </div>
            </div>
          ) : (
            <>
              <div className="security-findings-toolbar">
                <h5>
                  Findings <span>{filteredFindings.length.toLocaleString()}</span>
                </h5>
                <label>
                  <span>Severity</span>
                  <select
                    aria-label="Filter security findings by severity"
                    value={filter}
                    onChange={(event) => {
                      const value = event.target.value
                      setFilter(value === 'all' || isSecuritySeverity(value) ? value : 'all')
                    }}
                  >
                    <option value="all">All severities</option>
                    {severities.map((severity) => (
                      <option key={severity} value={severity}>
                        {severityLabels[severity]}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              {filteredFindings.length > 0 ? (
                <div className="security-findings-list">
                  {filteredFindings.map((finding, index) => (
                    <FindingCard
                      key={`${finding.rule_id}:${finding.file_path}:${finding.start_line}:${index}`}
                      finding={finding}
                    />
                  ))}
                </div>
              ) : (
                <div className="security-empty-state" role="status">
                  No findings match the selected severity filter.
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  )
}

export default RepositorySecurityAnalysis
