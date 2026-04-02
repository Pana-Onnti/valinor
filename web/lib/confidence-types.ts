/**
 * confidence-types.ts
 * TypeScript interfaces mirroring the backend AnalysisConfidenceMetadata schema (VAL-97).
 */

export type ConfidenceLevel = 'verified' | 'estimated' | 'low_confidence'

export interface FindingConfidence {
  level: ConfidenceLevel
  source_tables: string[]
  source_columns: string[]
  record_count: number
  null_rate: number       // 0.0–1.0
  dq_score: number        // 0.0–10.0
  verification_method: string
  sql_query: string
  degradation_applied?: boolean
  degradation_reason?: string | null
}

export interface TrustScoreBreakdown {
  overall: number                    // 0-100
  dq_component: number               // 0-30
  verification_component: number     // 0-25
  null_density_component: number     // 0-15
  schema_coverage_component: number  // 0-15
  reconciliation_component: number   // 0-15
}

export interface AnalysisConfidenceMetadata {
  trust_score: TrustScoreBreakdown
  findings_confidence: Record<string, FindingConfidence>   // keyed by finding ID
  kpi_confidence: Record<string, FindingConfidence>        // keyed by KPI label
  analysis_timestamp: string                               // ISO datetime
  total_queries_executed: number
  total_records_processed: number
  pipeline_duration_seconds: number
}
