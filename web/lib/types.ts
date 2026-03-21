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
