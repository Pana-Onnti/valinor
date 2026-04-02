/**
 * types.ts
 * Shared TypeScript interfaces for all Valinor SaaS API responses.
 */

export interface Job {
  job_id: string
  status: string
  client_name: string
  period: string
  created_at: string
}

export interface JobStatus extends Job {
  progress: number
  stage: string
  message: string
  error_detail?: string
}

/** API-level Finding (flat structure from analysis results). */
export interface Finding {
  id: string
  title: string
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO"
  description: string
  sql?: string
}

export interface DQCheck {
  check_name: string
  passed: boolean
  severity: string
  score: number
  message?: string
}

export interface DQReport {
  overall_score: number
  gate_decision: "PROCEED" | "WARN" | "HALT"
  checks: DQCheck[]
  data_quality_tag: string
}

export interface DQHistoryEntry {
  date: string
  score: number
  gate_decision: string
  passed_checks: number
  total_checks: number
}

export interface ClientProfile {
  client_name: string
  industry_inferred: string
  run_count: number
  last_run_date: string
  dq_history: DQHistoryEntry[]
}

export interface AlertThreshold {
  metric: string
  condition: string
  threshold_value: number
  severity: string
  description: string
}

export interface Webhook {
  url: string
  events: string[]
  secret?: string
  active: boolean
}

export interface SSHConfig {
  host: string
  username: string
  private_key_path: string
  port?: number
}

export interface DBConfig {
  host: string
  port: number
  name: string
  type: string
  user?: string
  password?: string
}

export interface AnalyzeRequest {
  client_name: string
  ssh_config: SSHConfig
  db_config: DBConfig
  period: string
}

// ── File Upload ──────────────────────────────────────────────────────────────

export interface UploadResult {
  upload_id: string
  filename: string
  size_bytes: number
  file_type: string
  sheets: string[]
  status: string
}

export interface UploadFileState {
  file: File
  upload_id?: string
  progress: number  // 0-100
  status: 'pending' | 'uploading' | 'processing' | 'ready' | 'error'
  error?: string
  result?: UploadResult
}

export interface PreviewData {
  upload_id: string
  sheet?: string
  rows: Record<string, unknown>[]
  total_rows: number
  columns: string[]
}

export interface SchemaData {
  upload_id: string
  columns: Array<{
    name: string
    dtype: string
    nullable: boolean
    sample_values: unknown[]
  }>
}
