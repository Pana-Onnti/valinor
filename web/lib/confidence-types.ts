/**
 * confidence-types.ts — Tipos para Trust Score / Confidence Metadata
 * Refleja el schema del backend (VAL-97).
 */

export interface TrustScoreBreakdown {
  overall: number          // 0-100
  dq_component: number     // 0-30
  verification_component: number  // 0-25
  null_density_component: number  // 0-15
  schema_coverage_component: number  // 0-15
  reconciliation_component: number   // 0-15
}

export interface ConfidenceMetadata {
  trust_score: TrustScoreBreakdown
}
