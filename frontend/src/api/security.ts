import { apiRequest } from './client'

export type SecuritySeverity =
  | 'critical'
  | 'high'
  | 'medium'
  | 'low'
  | 'informational'

export interface SecurityFinding {
  rule_id: string
  severity: SecuritySeverity
  title: string
  message: string
  file_path: string
  start_line: number
  end_line: number
  code_snippet: string | null
  remediation: string | null
}

export interface SecuritySeveritySummary {
  critical: number
  high: number
  medium: number
  low: number
  informational: number
}

export interface SecurityScanResponse {
  analysis_id: number
  repository_id: number
  status: string
  scanner: string
  scanned_files: number
  skipped_files: number
  total_findings: number
  summary: SecuritySeveritySummary
  findings: SecurityFinding[]
  created_at: string
}

export function runRepositorySecurityScan(
  repositoryId: number,
  token: string,
): Promise<SecurityScanResponse> {
  return apiRequest<SecurityScanResponse>(
    `/api/v1/repositories/${repositoryId}/security-scan`,
    { method: 'POST', token },
  )
}
