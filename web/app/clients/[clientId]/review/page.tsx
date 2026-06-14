'use client'

import { useEffect, useState, useMemo } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useClientProfile } from '@/lib/hooks'
import { T, SEV_COLOR, SEV_LABEL } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Types — mirror the N4 PendingRefinement / PendingFindingEscalation records ──

interface PendingRefinement {
  proposal_id: string
  refinement: {
    table_weights?: Record<string, number>
    query_hints?: string[]
    focus_areas?: string[]
    suppress_ids?: string[]
    context_block?: string
    generated_at?: string
  }
  run_id: string
  client_tag: string
  generated_at: string
  source_findings_ids: string[]
  confidence: number | null
  confidence_label: string
  status: string
  reviewed_at?: string | null
  reviewed_by?: string | null
  review_reason?: string
}

interface PendingEscalation {
  proposal_id: string
  finding_id: string
  from_severity: string
  to_severity: string
  runs_open: number
  run_id: string
  client_tag: string
  generated_at: string
  confidence: number | null
  confidence_label: string
  status: string
  reviewed_at?: string | null
  reviewed_by?: string | null
  review_reason?: string
}

type ViewMode = 'pending' | 'all'

const CONF_COLOR: Record<string, string> = {
  CONFIRMED: T.accent.teal,
  PROVISIONAL: T.accent.yellow,
  UNVERIFIED: T.accent.orange,
  BLOCKED: T.accent.red,
}

const STATUS_COLOR: Record<string, string> = {
  pending: T.accent.blue,
  approved: T.accent.teal,
  rejected: T.text.tertiary,
}

function formatDate(iso: string) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function shortId(id: string) {
  return id && id.length > 10 ? id.slice(0, 10) : id
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function ConfidenceBadge({ value, label }: { value: number | null; label: string }) {
  const color = CONF_COLOR[label] ?? T.text.tertiary
  const pct = value != null ? `${Math.round(value * 100)}%` : '—'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '2px 8px', borderRadius: '9999px', fontSize: 11, fontWeight: 600,
      fontFamily: T.font.mono,
      backgroundColor: color + '15', border: `1px solid ${color}40`, color,
    }}>
      <span style={{ fontVariantNumeric: 'tabular-nums' }}>{pct}</span>
      <span style={{ opacity: 0.7 }}>{label || 'SIN LABEL'}</span>
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLOR[status] ?? T.text.tertiary
  const label = { pending: 'Pendiente', approved: 'Aprobado', rejected: 'Rechazado' }[status] ?? status
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', padding: '2px 8px',
      borderRadius: '9999px', fontSize: 10, fontWeight: 600, fontFamily: T.font.mono,
      backgroundColor: color + '15', border: `1px solid ${color}40`, color,
    }}>
      {label}
    </span>
  )
}

function ProvenanceRow({ runId, sourceCount, generatedAt }: {
  runId: string; sourceCount?: number; generatedAt: string
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: T.space.lg, flexWrap: 'wrap',
      marginTop: T.space.md, paddingTop: T.space.md, borderTop: T.border.subtle,
      fontSize: 10, fontFamily: T.font.mono, color: T.text.tertiary,
    }}>
      <span>run: <span style={{ color: T.text.secondary, userSelect: 'all' }}>{shortId(runId) || '—'}</span></span>
      {sourceCount != null && (
        <span>findings fuente: <span style={{ color: T.text.secondary }}>{sourceCount}</span></span>
      )}
      <span>generado: <span style={{ color: T.text.secondary }}>{formatDate(generatedAt)}</span></span>
    </div>
  )
}

interface ActionsProps {
  proposalId: string
  busy: boolean
  onApprove: () => void
  onReject: (reason: string) => void
}

function ReviewActions({ proposalId, busy, onApprove, onReject }: ActionsProps) {
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')

  if (rejecting) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm, minWidth: 240 }}>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Motivo del rechazo (opcional)…"
          rows={2}
          style={{
            width: '100%', resize: 'vertical', fontSize: 12, fontFamily: T.font.display,
            padding: '8px 10px', borderRadius: T.radius.sm, color: T.text.primary,
            backgroundColor: T.bg.elevated, border: T.border.card, outline: 'none',
          }}
        />
        <div style={{ display: 'flex', gap: T.space.sm }}>
          <button
            onClick={() => onReject(reason)}
            disabled={busy}
            style={{
              flex: 1, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer',
              color: T.accent.red, backgroundColor: T.accent.red + '15',
              border: `1px solid ${T.accent.red}40`, borderRadius: T.radius.sm, opacity: busy ? 0.5 : 1,
            }}
          >
            Confirmar rechazo
          </button>
          <button
            onClick={() => { setRejecting(false); setReason('') }}
            disabled={busy}
            style={{
              padding: '6px 12px', fontSize: 12, fontWeight: 500, cursor: 'pointer',
              color: T.text.tertiary, backgroundColor: 'transparent', border: T.border.card, borderRadius: T.radius.sm,
            }}
          >
            Cancelar
          </button>
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', gap: T.space.sm, flexShrink: 0 }}>
      <button
        onClick={onApprove}
        disabled={busy}
        style={{
          padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: busy ? 'not-allowed' : 'pointer',
          color: T.text.inverse, backgroundColor: T.accent.teal, border: 'none',
          borderRadius: T.radius.sm, opacity: busy ? 0.5 : 1, whiteSpace: 'nowrap',
        }}
      >
        {busy ? 'Guardando…' : 'Aprobar'}
      </button>
      <button
        onClick={() => setRejecting(true)}
        disabled={busy}
        style={{
          padding: '6px 14px', fontSize: 12, fontWeight: 500, cursor: busy ? 'not-allowed' : 'pointer',
          color: T.text.tertiary, backgroundColor: 'transparent', border: T.border.card,
          borderRadius: T.radius.sm, whiteSpace: 'nowrap',
        }}
      >
        Rechazar
      </button>
    </div>
  )
}

function ReviewedNote({ item }: { item: PendingRefinement | PendingEscalation }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: T.space.md, flexShrink: 0, fontSize: 11, fontFamily: T.font.mono, color: T.text.tertiary }}>
      <StatusBadge status={item.status} />
      <span>{item.reviewed_by ?? '—'} · {formatDate(item.reviewed_at ?? '')}</span>
    </div>
  )
}

// ── Refinement card ───────────────────────────────────────────────────────────

function RefinementCard({ item, busy, onApprove, onReject }: {
  item: PendingRefinement; busy: boolean
  onApprove: () => void; onReject: (reason: string) => void
}) {
  const r = item.refinement ?? {}
  const weights = Object.entries(r.table_weights ?? {})
  const isPending = item.status === 'pending'
  return (
    <div style={{
      backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card,
      borderLeft: `3px solid ${T.accent.purple}`, padding: `${T.space.lg} ${T.space.xl}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: T.space.lg }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, flexWrap: 'wrap', marginBottom: T.space.sm }}>
            <span style={{ fontSize: 11, fontWeight: 700, fontFamily: T.font.mono, color: T.accent.purple }}>REFINAMIENTO</span>
            <ConfidenceBadge value={item.confidence} label={item.confidence_label} />
            {!isPending && <StatusBadge status={item.status} />}
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: T.space.lg, fontSize: 12, color: T.text.secondary }}>
            {weights.length > 0 && (
              <span><span style={{ color: T.text.tertiary }}>pesos de tabla:</span>{' '}
                <span style={{ fontFamily: T.font.mono }}>{weights.length}</span></span>
            )}
            {(r.query_hints?.length ?? 0) > 0 && (
              <span><span style={{ color: T.text.tertiary }}>query hints:</span>{' '}
                <span style={{ fontFamily: T.font.mono }}>{r.query_hints!.length}</span></span>
            )}
            {(r.focus_areas?.length ?? 0) > 0 && (
              <span><span style={{ color: T.text.tertiary }}>focus areas:</span>{' '}
                <span style={{ fontFamily: T.font.mono }}>{r.focus_areas!.length}</span></span>
            )}
            {(r.suppress_ids?.length ?? 0) > 0 && (
              <span><span style={{ color: T.text.tertiary }}>suprimidos:</span>{' '}
                <span style={{ fontFamily: T.font.mono }}>{r.suppress_ids!.length}</span></span>
            )}
          </div>

          {weights.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: T.space.sm }}>
              {weights.slice(0, 6).map(([tbl, w]) => (
                <span key={tbl} style={{
                  fontSize: 11, fontFamily: T.font.mono, padding: '2px 8px', borderRadius: '9999px',
                  backgroundColor: T.bg.elevated, color: T.text.secondary,
                }}>
                  {tbl} <span style={{ color: T.accent.teal }}>{Number(w).toFixed(2)}</span>
                </span>
              ))}
            </div>
          )}

          <ProvenanceRow runId={item.run_id} sourceCount={item.source_findings_ids?.length} generatedAt={item.generated_at} />
        </div>

        {isPending ? (
          <ReviewActions proposalId={item.proposal_id} busy={busy} onApprove={onApprove} onReject={onReject} />
        ) : (
          <ReviewedNote item={item} />
        )}
      </div>
    </div>
  )
}

// ── Escalation card ───────────────────────────────────────────────────────────

function EscalationCard({ item, busy, onApprove, onReject }: {
  item: PendingEscalation; busy: boolean
  onApprove: () => void; onReject: (reason: string) => void
}) {
  const fromColor = SEV_COLOR[item.from_severity] ?? T.text.tertiary
  const toColor = SEV_COLOR[item.to_severity] ?? T.text.tertiary
  const isPending = item.status === 'pending'
  return (
    <div style={{
      backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card,
      borderLeft: `3px solid ${toColor}`, padding: `${T.space.lg} ${T.space.xl}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: T.space.lg }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, flexWrap: 'wrap', marginBottom: T.space.sm }}>
            <span style={{ fontSize: 11, fontWeight: 700, fontFamily: T.font.mono, color: T.accent.yellow }}>ESCALACIÓN</span>
            <ConfidenceBadge value={item.confidence} label={item.confidence_label} />
            {!isPending && <StatusBadge status={item.status} />}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, marginBottom: T.space.sm }}>
            <span style={{
              fontSize: 11, fontWeight: 600, fontFamily: T.font.mono, padding: '2px 8px', borderRadius: '9999px',
              backgroundColor: fromColor + '15', border: `1px solid ${fromColor}40`, color: fromColor,
            }}>
              {SEV_LABEL[item.from_severity] ?? item.from_severity}
            </span>
            <span style={{ color: T.text.tertiary }}>→</span>
            <span style={{
              fontSize: 11, fontWeight: 700, fontFamily: T.font.mono, padding: '2px 8px', borderRadius: '9999px',
              backgroundColor: toColor + '20', border: `1px solid ${toColor}60`, color: toColor,
            }}>
              {SEV_LABEL[item.to_severity] ?? item.to_severity}
            </span>
            <span style={{ fontSize: 12, color: T.text.secondary }}>
              por persistir{' '}
              <span style={{ fontFamily: T.font.mono, fontWeight: 700, color: T.accent.red }}>{item.runs_open}</span>{' '}
              runs
            </span>
          </div>

          <p style={{ fontSize: 11, fontFamily: T.font.mono, color: T.text.tertiary, margin: 0 }}>
            finding: <span style={{ color: T.text.secondary, userSelect: 'all' }}>{shortId(item.finding_id)}</span>
          </p>

          <ProvenanceRow runId={item.run_id} generatedAt={item.generated_at} />
        </div>

        {isPending ? (
          <ReviewActions proposalId={item.proposal_id} busy={busy} onApprove={onApprove} onReject={onReject} />
        ) : (
          <ReviewedNote item={item} />
        )}
      </div>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ what }: { what: string }) {
  return (
    <div style={{
      backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card,
      padding: '40px 24px', textAlign: 'center',
    }}>
      <div style={{
        margin: '0 auto 12px', width: 44, height: 44, borderRadius: '50%',
        backgroundColor: T.bg.elevated, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <svg style={{ width: 22, height: 22, color: T.accent.teal }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <p style={{ fontSize: 13, fontWeight: 500, color: T.text.secondary, margin: 0 }}>No hay {what} para revisar.</p>
      <p style={{ fontSize: 12, color: T.text.tertiary, marginTop: 4 }}>
        Las propuestas aparecen acá cuando el pipeline corre con <span style={{ fontFamily: T.font.mono }}>VALINOR_MEMORY_REVIEW=1</span>.
      </p>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ClientReviewPage() {
  const params = useParams()
  const clientId = params.clientId as string
  const { data: profile } = useClientProfile(clientId)

  const [refinements, setRefinements] = useState<PendingRefinement[]>([])
  const [escalations, setEscalations] = useState<PendingEscalation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<ViewMode>('pending')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const base = `${API_URL}/api/clients/${encodeURIComponent(clientId)}`

  const fetchQueues = (mode: ViewMode) => {
    setLoading(true)
    setError(null)
    const qs = mode === 'all' ? '?status=all' : ''
    Promise.all([
      fetch(`${base}/pending-refinements${qs}`).then(r => r.ok ? r.json() : Promise.reject(new Error(`Error ${r.status}`))),
      fetch(`${base}/pending-escalations${qs}`).then(r => r.ok ? r.json() : Promise.reject(new Error(`Error ${r.status}`))),
    ])
      .then(([ref, esc]) => {
        setRefinements(ref?.pending_refinements ?? [])
        setEscalations(esc?.pending_escalations ?? [])
      })
      .catch(err => setError(err.message || 'Error cargando la cola de revisión'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchQueues(view) }, [clientId, view])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3500)
  }

  const act = async (queue: 'pending-refinements' | 'pending-escalations', id: string,
                     action: 'approve' | 'reject', reason?: string) => {
    setBusyId(id)
    try {
      const res = await fetch(`${base}/${queue}/${encodeURIComponent(id)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(action === 'reject' ? { reason: reason ?? '' } : {}),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || `Error ${res.status}`)
      }
      showToast(action === 'approve' ? 'Propuesta aprobada y aplicada.' : 'Propuesta rechazada.')
      fetchQueues(view)
    } catch (err: any) {
      setError(err.message || 'Error al procesar la decisión')
    } finally {
      setBusyId(null)
    }
  }

  const pendingCount = useMemo(
    () => refinements.filter(r => r.status === 'pending').length + escalations.filter(e => e.status === 'pending').length,
    [refinements, escalations]
  )

  const clientName = (profile?.client_name ?? clientId).replace(/_/g, ' ')

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      <header style={{ position: 'sticky', top: 0, zIndex: 10, backgroundColor: T.bg.card, borderBottom: T.border.card }}>
        <div style={{ maxWidth: 896, margin: '0 auto', padding: `${T.space.lg} ${T.space.xl}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg }}>
            <Link href={`/clients/${clientId}`} style={{ color: T.text.tertiary, lineHeight: 0 }}>
              <svg style={{ height: 20, width: 20 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
              </svg>
            </Link>
            <div>
              <h1 style={{ fontSize: 16, fontWeight: 700, color: T.text.primary, display: 'flex', alignItems: 'center', gap: 8, margin: 0 }}>
                <svg style={{ height: 16, width: 16, color: T.accent.teal }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                </svg>
                Revisión de memoria · {clientName}
              </h1>
              <p style={{ fontSize: 11, color: T.text.tertiary, margin: '2px 0 0' }}>
                {pendingCount} propuesta{pendingCount !== 1 ? 's' : ''} pendiente{pendingCount !== 1 ? 's' : ''} de aprobación
              </p>
            </div>
          </div>

          <button onClick={() => fetchQueues(view)} className="d4c-btn-ghost" style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <svg style={{ height: 14, width: 14 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            Actualizar
          </button>
        </div>
      </header>

      <main style={{ maxWidth: 896, margin: '0 auto', padding: `${T.space.xxl} ${T.space.xl}`, display: 'flex', flexDirection: 'column', gap: T.space.xxl }}>

        {toast && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: T.space.sm, padding: `${T.space.md} ${T.space.lg}`,
            backgroundColor: T.accent.teal + '15', border: `1px solid ${T.accent.teal}40`,
            borderRadius: T.radius.lg, color: T.accent.teal, fontSize: 13,
          }}>
            <svg style={{ height: 16, width: 16, flexShrink: 0 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {toast}
          </div>
        )}

        {error && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: T.space.sm, padding: `${T.space.md} ${T.space.lg}`,
            backgroundColor: T.accent.red + '15', border: `1px solid ${T.accent.red}40`,
            borderRadius: T.radius.lg, color: T.accent.red, fontSize: 13,
          }}>
            <svg style={{ height: 16, width: 16, flexShrink: 0 }} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
            {error}
          </div>
        )}

        {/* View toggle */}
        <div style={{ display: 'flex', gap: T.space.sm }}>
          {([['pending', 'Pendientes'], ['all', 'Historial']] as [ViewMode, string][]).map(([v, label]) => {
            const isActive = view === v
            return (
              <button key={v} onClick={() => setView(v)} style={{
                padding: '6px 14px', borderRadius: T.radius.md, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                backgroundColor: isActive ? T.accent.teal + '20' : T.bg.card,
                border: isActive ? `1px solid ${T.accent.teal}60` : T.border.card,
                color: isActive ? T.accent.teal : T.text.tertiary,
              }}>
                {label}
              </button>
            )
          })}
        </div>

        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }} className="animate-pulse">
            {[...Array(3)].map((_, i) => (
              <div key={i} style={{ height: 110, backgroundColor: T.bg.elevated, borderRadius: T.radius.lg }} />
            ))}
          </div>
        ) : (
          <>
            <section>
              <h2 style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.md, display: 'flex', alignItems: 'center', gap: T.space.sm }}>
                Refinamientos
                <span style={{ fontSize: 11, fontWeight: 700, color: T.text.secondary, textTransform: 'none' }}>({refinements.length})</span>
              </h2>
              {refinements.length === 0 ? (
                <EmptyState what="refinamientos" />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}>
                  {refinements.map(item => (
                    <RefinementCard
                      key={item.proposal_id}
                      item={item}
                      busy={busyId === item.proposal_id}
                      onApprove={() => act('pending-refinements', item.proposal_id, 'approve')}
                      onReject={(reason) => act('pending-refinements', item.proposal_id, 'reject', reason)}
                    />
                  ))}
                </div>
              )}
            </section>

            <section>
              <h2 style={{ fontSize: 10, fontWeight: 600, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: T.space.md, display: 'flex', alignItems: 'center', gap: T.space.sm }}>
                Escalaciones de severidad
                <span style={{ fontSize: 11, fontWeight: 700, color: T.text.secondary, textTransform: 'none' }}>({escalations.length})</span>
              </h2>
              {escalations.length === 0 ? (
                <EmptyState what="escalaciones" />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}>
                  {escalations.map(item => (
                    <EscalationCard
                      key={item.proposal_id}
                      item={item}
                      busy={busyId === item.proposal_id}
                      onApprove={() => act('pending-escalations', item.proposal_id, 'approve')}
                      onReject={(reason) => act('pending-escalations', item.proposal_id, 'reject', reason)}
                    />
                  ))}
                </div>
              )}
            </section>
          </>
        )}

        <p style={{ fontSize: 10, fontFamily: T.font.mono, color: T.text.tertiary, textAlign: 'center', marginTop: T.space.lg }}>
          Generado por Valinor · Delta 4C
        </p>
      </main>
    </div>
  )
}
