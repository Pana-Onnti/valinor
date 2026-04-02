'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import axios from 'axios'
import {
  CheckCircle, XCircle, Clock, Loader2, Compass, Code,
  BarChart3, Shield, Search, BookOpen, Zap, Package,
} from 'lucide-react'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/* ─── Pipeline stages ─────────────────────────────────────────────────────── */

const PIPELINE_STAGES = [
  'data_quality_gate', 'cartographer', 'query_builder', 'execute_queries',
  'baseline', 'analyst', 'sentinel', 'hunter', 'reconciliation',
  'verification', 'narrators', 'delivery',
] as const

type StageName = (typeof PIPELINE_STAGES)[number]

const STAGE_META: Record<StageName, { label: string; icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }> }> = {
  data_quality_gate: { label: 'Control de Calidad', icon: Shield },
  cartographer:      { label: 'Cartógrafo', icon: Compass },
  query_builder:     { label: 'Constructor de Queries', icon: Code },
  execute_queries:   { label: 'Ejecutando Queries', icon: Zap },
  baseline:          { label: 'Línea Base', icon: BarChart3 },
  analyst:           { label: 'Analista', icon: BarChart3 },
  sentinel:          { label: 'Centinela', icon: Shield },
  hunter:            { label: 'Cazador', icon: Search },
  reconciliation:    { label: 'Reconciliación', icon: Package },
  verification:      { label: 'Verificación', icon: CheckCircle },
  narrators:         { label: 'Narradores', icon: BookOpen },
  delivery:          { label: 'Entrega', icon: Package },
}

/* ─── Types ───────────────────────────────────────────────────────────────── */

type AgentStatus = 'waiting' | 'running' | 'completed' | 'error'

interface AgentState {
  status: AgentStatus
  message?: string
  duration?: number
}

interface AnalysisProgressProps {
  analysisId: string
  onComplete: () => void
}

/** New PipelineEvent format from backend */
interface PipelineEvent {
  job_id: string
  agent: string
  status: 'started' | 'completed' | 'error'
  message: string
  duration_seconds?: number | null
  metadata?: Record<string, unknown> | null
  timestamp?: string
  progress?: number | null
}

/** Legacy ProgressUpdate format (polling fallback) */
interface ProgressUpdate {
  job_id: string
  status: string
  stage: string
  progress: number
  message: string
  dq_score?: number
  dq_label?: string
  final?: boolean
  error?: string
  done?: boolean
}

/* ─── Educational carousel facts ──────────────────────────────────────────── */

const CAROUSEL_FACTS = [
  '\u00bfSab\u00edas que el 73% de las PyMEs LATAM tiene m\u00e1s del 20% de su cartera vencida?',
  'El margen promedio en distribuci\u00f3n LATAM es 14%. \u00bfD\u00f3nde estar\u00e1 el tuyo?',
  'Valinor verifica cada dato con m\u00faltiples fuentes antes de reportarlo.',
  'En promedio, detectamos 4 hallazgos cr\u00edticos por empresa.',
  'El costo promedio de no cobrar a tiempo: 2.3% de tu facturaci\u00f3n anual.',
]

/* ─── Shimmer keyframes (injected once) ───────────────────────────────────── */

const SHIMMER_ID = 'd4c-shimmer-keyframes'
const PULSE_ID = 'd4c-pulse-keyframes'

function injectKeyframes() {
  if (typeof document === 'undefined') return
  if (!document.getElementById(SHIMMER_ID)) {
    const style = document.createElement('style')
    style.id = SHIMMER_ID
    style.textContent = `
      @keyframes d4c-shimmer {
        0% { background-position: -200% 0; }
        100% { background-position: 200% 0; }
      }
      @keyframes d4c-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
      }
    `
    document.head.appendChild(style)
  }
  if (!document.getElementById(PULSE_ID)) {
    const style = document.createElement('style')
    style.id = PULSE_ID
    style.textContent = `
      @keyframes d4c-pulse-glow {
        0%, 100% { box-shadow: 0 0 0 0 var(--color-accent-teal); opacity: 1; }
        50% { box-shadow: 0 0 12px 4px var(--color-accent-teal); opacity: 0.8; }
      }
    `
    document.head.appendChild(style)
  }
}

/* ─── Component ───────────────────────────────────────────────────────────── */

export function AnalysisProgress({ analysisId, onComplete }: AnalysisProgressProps) {
  const [agents, setAgents] = useState<Record<StageName, AgentState>>(() => {
    const init: Partial<Record<StageName, AgentState>> = {}
    for (const s of PIPELINE_STAGES) init[s] = { status: 'waiting' }
    return init as Record<StageName, AgentState>
  })
  const [globalProgress, setGlobalProgress] = useState(0)
  const [status, setStatus] = useState<'running' | 'completed' | 'failed'>('running')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [showCompletion, setShowCompletion] = useState(false)
  const [carouselIdx, setCarouselIdx] = useState(0)

  const startTimeRef = useRef(Date.now())
  const onCompleteRef = useRef(onComplete)
  useEffect(() => { onCompleteRef.current = onComplete }, [onComplete])

  // Inject keyframes on mount
  useEffect(() => { injectKeyframes() }, [])

  // Carousel rotation
  useEffect(() => {
    if (status !== 'running') return
    const iv = setInterval(() => {
      setCarouselIdx((p) => (p + 1) % CAROUSEL_FACTS.length)
    }, 8000)
    return () => clearInterval(iv)
  }, [status])

  // Remaining time estimate
  const completedCount = PIPELINE_STAGES.filter((s) => agents[s].status === 'completed').length
  const elapsedSec = (Date.now() - startTimeRef.current) / 1000
  const estRemainingMin = completedCount > 0
    ? Math.ceil(((elapsedSec / completedCount) * (PIPELINE_STAGES.length - completedCount)) / 60)
    : null

  /* ── applyPipelineEvent — new format ──────────────────────────────────── */
  const applyPipelineEvent = useCallback((evt: PipelineEvent) => {
    const stage = evt.agent as StageName
    if (!PIPELINE_STAGES.includes(stage)) return

    setAgents((prev) => {
      const next = { ...prev }
      if (evt.status === 'started') {
        next[stage] = { status: 'running', message: evt.message }
      } else if (evt.status === 'completed') {
        next[stage] = {
          status: 'completed',
          message: evt.message,
          duration: evt.duration_seconds ?? undefined,
        }
      } else if (evt.status === 'error') {
        next[stage] = { status: 'error', message: evt.message }
      }
      return next
    })

    if (evt.progress != null) {
      setGlobalProgress(Math.max(0, Math.min(100, evt.progress)))
    }
  }, [])

  /* ── applyLegacyUpdate — old polling format ───────────────────────────── */
  const applyLegacyUpdate = useCallback((data: ProgressUpdate) => {
    if (data.error || data.done) return

    const p = data.progress ?? 0
    setGlobalProgress(Math.max(0, p))

    if (data.stage) {
      const completedN = Math.floor((Math.max(0, p) / 100) * PIPELINE_STAGES.length)
      setAgents((prev) => {
        const next = { ...prev }
        PIPELINE_STAGES.forEach((s, i) => {
          if (i < completedN) next[s] = { ...next[s], status: 'completed' }
          else if (i === completedN) next[s] = { ...next[s], status: 'running', message: data.message }
          else next[s] = { ...next[s], status: 'waiting' }
        })
        return next
      })
    }

    if (data.status) {
      setStatus(data.status as 'running' | 'completed' | 'failed')
      if (data.status === 'failed' && data.message) {
        setErrorMessage(data.message.replace(/^Analysis failed:\s*/i, ''))
      }
    }
  }, [])

  /* ── 3-tier connection (WS → SSE → polling) ──────────────────────────── */
  useEffect(() => {
    if (!analysisId) return

    let ws: WebSocket | null = null
    let eventSource: EventSource | null = null
    let pollInterval: ReturnType<typeof setInterval> | null = null
    let completed = false

    const cleanup = () => {
      ws?.close()
      eventSource?.close()
      if (pollInterval) clearInterval(pollInterval)
    }

    const isPipelineEvent = (data: Record<string, unknown>): data is PipelineEvent =>
      'agent' in data && ('status' in data) &&
      ['started', 'completed', 'error'].includes(data.status as string)

    const handleMessage = (raw: string) => {
      try {
        const data = JSON.parse(raw)

        if (isPipelineEvent(data)) {
          applyPipelineEvent(data)
        } else {
          applyLegacyUpdate(data as ProgressUpdate)
        }

        // Check for completion
        if (!completed && (
          data.final || data.status === 'completed' || data.status === 'failed' ||
          data.done
        )) {
          // For PipelineEvent "completed" on delivery stage
          if (isPipelineEvent(data) && data.agent === 'delivery' && data.status === 'completed') {
            completed = true
            setStatus('completed')
            setGlobalProgress(100)
            setAgents((prev) => {
              const next = { ...prev }
              for (const s of PIPELINE_STAGES) {
                if (next[s].status !== 'completed' && next[s].status !== 'error') {
                  next[s] = { ...next[s], status: 'completed' }
                }
              }
              return next
            })
            setTimeout(() => setShowCompletion(true), 1500)
            cleanup()
            return
          }

          // Legacy completion
          if (!isPipelineEvent(data) && (data.final || data.status === 'completed')) {
            completed = true
            setStatus('completed')
            setGlobalProgress(100)
            setAgents((prev) => {
              const next = { ...prev }
              for (const s of PIPELINE_STAGES) next[s] = { ...next[s], status: 'completed' }
              return next
            })
            setTimeout(() => setShowCompletion(true), 1500)
            cleanup()
            return
          }

          if (data.status === 'failed') {
            completed = true
            setStatus('failed')
            if (data.message) setErrorMessage(
              String(data.message).replace(/^Analysis failed:\s*/i, '')
            )
            cleanup()
          }
        }
      } catch {
        // ignore parse errors
      }
    }

    // Tier 3: HTTP polling
    const startPolling = () => {
      const poll = async () => {
        if (completed) return
        try {
          const res = await axios.get(`${API_URL}/api/jobs/${analysisId}/status`)
          handleMessage(JSON.stringify({
            job_id: analysisId,
            status: res.data.status,
            stage: res.data.stage ?? '',
            progress: res.data.progress ?? 0,
            message: res.data.message ?? '',
            final: res.data.final,
            done: res.data.done,
          }))
        } catch {
          // keep polling
        }
      }
      poll()
      pollInterval = setInterval(poll, 3000)
    }

    // Tier 2: SSE
    const trySSE = () => {
      try {
        eventSource = new EventSource(`${API_URL}/api/jobs/${analysisId}/stream`)
        eventSource.onmessage = (event) => handleMessage(event.data)
        eventSource.onerror = () => {
          eventSource?.close()
          eventSource = null
          if (!completed) startPolling()
        }
      } catch {
        startPolling()
      }
    }

    // Tier 1: WebSocket
    const tryWebSocket = () => {
      try {
        const wsUrl = API_URL.replace(/^http/, 'ws')
        ws = new WebSocket(`${wsUrl}/api/jobs/${analysisId}/ws`)

        const wsTimeout = setTimeout(() => {
          if (ws && ws.readyState !== WebSocket.OPEN) {
            ws.close()
            ws = null
            if (!completed) trySSE()
          }
        }, 3000)

        ws.onopen = () => clearTimeout(wsTimeout)
        ws.onmessage = (event) => handleMessage(event.data)
        ws.onerror = () => {
          clearTimeout(wsTimeout)
          ws?.close()
          ws = null
          if (!completed) trySSE()
        }
        ws.onclose = (event) => {
          clearTimeout(wsTimeout)
          if (!completed && event.code !== 1000) trySSE()
        }
      } catch {
        trySSE()
      }
    }

    tryWebSocket()
    return cleanup
  }, [analysisId, applyPipelineEvent, applyLegacyUpdate])

  /* ── Render ───────────────────────────────────────────────────────────── */

  // Completion screen
  if (showCompletion) {
    return (
      <AnimatePresence>
        <motion.div
          key="completion"
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minHeight: 400,
            gap: T.space.lg,
          }}
        >
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.2, type: 'spring', stiffness: 200, damping: 15 }}
          >
            <CheckCircle size={56} style={{ color: T.accent.teal }} />
          </motion.div>
          <h2 style={{
            fontFamily: T.font.display,
            fontSize: 34,
            fontWeight: 600,
            color: T.text.primary,
            textAlign: 'center',
            margin: 0,
          }}>
            Tu diagn&oacute;stico est&aacute; listo
          </h2>
          <motion.button
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            onClick={() => onCompleteRef.current()}
            style={{
              marginTop: T.space.md,
              padding: `${T.space.sm} ${T.space.xl}`,
              backgroundColor: T.accent.teal,
              color: T.text.inverse,
              border: 'none',
              borderRadius: T.radius.md,
              fontSize: 16,
              fontWeight: 600,
              fontFamily: T.font.display,
              cursor: 'pointer',
            }}
          >
            Ver diagn&oacute;stico
          </motion.button>
        </motion.div>
      </AnimatePresence>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      style={{ maxWidth: 700, margin: '0 auto', width: '100%' }}
    >
      {/* ── Global progress bar ─────────────────────────────────────────── */}
      <div style={{ marginBottom: T.space.lg }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: T.space.sm,
        }}>
          <span style={{
            fontSize: 13,
            color: T.text.secondary,
            fontFamily: T.font.display,
          }}>
            Diagn&oacute;stico en progreso
            {estRemainingMin != null && status === 'running'
              ? ` \u00b7 ~${estRemainingMin} min restantes`
              : ''}
          </span>
          <span style={{
            fontSize: 12,
            fontFamily: T.font.mono,
            color: T.text.tertiary,
          }}>
            {globalProgress}%
          </span>
        </div>
        <div style={{
          height: 4,
          backgroundColor: T.bg.elevated,
          borderRadius: 2,
          overflow: 'hidden',
          position: 'relative' as const,
        }}>
          <motion.div
            style={{
              height: '100%',
              borderRadius: 2,
              background: status === 'running'
                ? `linear-gradient(90deg, ${T.accent.teal}, var(--color-accent-blue), ${T.accent.teal})`
                : T.accent.teal,
              backgroundSize: status === 'running' ? '200% 100%' : undefined,
              animation: status === 'running' ? 'd4c-shimmer 2s linear infinite' : undefined,
            }}
            animate={{ width: `${globalProgress}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
      </div>

      {/* ── Agent cards ─────────────────────────────────────────────────── */}
      <div style={{
        backgroundColor: T.bg.card,
        borderRadius: T.radius.lg,
        border: T.border.card,
        padding: T.space.lg,
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.xs,
      }}>
        <AnimatePresence mode="sync">
          {PIPELINE_STAGES.map((stage) => {
            const state = agents[stage]
            const meta = STAGE_META[stage]
            const Icon = meta.icon
            const isWaiting = state.status === 'waiting'
            const isRunning = state.status === 'running'
            const isCompleted = state.status === 'completed'
            const isError = state.status === 'error'

            const accentColor = isCompleted
              ? T.accent.teal
              : isRunning
                ? T.accent.teal
                : isError
                  ? T.accent.red
                  : T.text.tertiary

            return (
              <motion.div
                key={stage}
                layout
                initial={false}
                animate={{
                  opacity: isWaiting ? 0.5 : 1,
                  scale: isRunning ? 1 : 1,
                }}
                transition={{ duration: 0.2 }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: T.space.sm,
                  padding: `${T.space.sm} ${T.space.md}`,
                  borderRadius: T.radius.sm,
                  backgroundColor: isRunning
                    ? T.bg.elevated
                    : 'transparent',
                  animation: isRunning ? 'd4c-pulse-glow 2.5s ease-in-out infinite' : undefined,
                  transition: 'background-color 0.2s',
                }}
              >
                {/* Icon */}
                <div style={{ flexShrink: 0, width: 22, display: 'flex', justifyContent: 'center' }}>
                  {isWaiting && (
                    <Clock size={16} style={{ color: T.text.tertiary }} />
                  )}
                  {isRunning && (
                    <Loader2
                      size={18}
                      style={{
                        color: T.accent.teal,
                        animation: 'd4c-spin 1s linear infinite',
                      }}
                    />
                  )}
                  {isCompleted && (
                    <motion.div
                      initial={{ rotate: -90, scale: 0.5 }}
                      animate={{ rotate: 0, scale: 1 }}
                      transition={{ duration: 0.2, type: 'spring', stiffness: 300 }}
                    >
                      <CheckCircle size={18} style={{ color: T.accent.teal }} />
                    </motion.div>
                  )}
                  {isError && (
                    <XCircle size={18} style={{ color: T.accent.red }} />
                  )}
                </div>

                {/* Stage icon */}
                <Icon size={14} style={{ color: accentColor, flexShrink: 0 }} />

                {/* Label + message */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: T.space.sm,
                  }}>
                    <span style={{
                      fontSize: 13,
                      fontWeight: isRunning || isCompleted ? 500 : 400,
                      color: isWaiting ? T.text.tertiary : T.text.primary,
                      fontFamily: T.font.display,
                    }}>
                      {meta.label}
                    </span>
                    {isCompleted && state.duration != null && (
                      <span style={{
                        fontSize: 11,
                        fontFamily: T.font.mono,
                        color: T.text.tertiary,
                        flexShrink: 0,
                      }}>
                        {state.duration < 60
                          ? `${Math.round(state.duration)}s`
                          : `${Math.floor(state.duration / 60)}m ${Math.round(state.duration % 60)}s`}
                      </span>
                    )}
                  </div>
                  {(isRunning || isError) && state.message && (
                    <motion.p
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      style={{
                        margin: `2px 0 0`,
                        fontSize: 11,
                        fontFamily: T.font.mono,
                        color: isError ? T.accent.red : T.text.secondary,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap' as const,
                      }}
                    >
                      {state.message}
                    </motion.p>
                  )}
                </div>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>

      {/* ── Error banner ────────────────────────────────────────────────── */}
      {status === 'failed' && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            marginTop: T.space.lg,
            padding: T.space.md,
            backgroundColor: T.accent.red + '10',
            borderRadius: T.radius.sm,
            border: `1px solid ${T.accent.red}30`,
          }}
        >
          <p style={{ fontSize: 13, fontWeight: 600, color: T.accent.red, margin: '0 0 4px' }}>
            An&aacute;lisis fallido
          </p>
          <p style={{
            fontSize: 11,
            color: T.accent.red,
            fontFamily: T.font.mono,
            wordBreak: 'break-all' as const,
            margin: 0,
          }}>
            {errorMessage || 'Error desconocido. Revis\u00e1 las credenciales e intent\u00e1 nuevamente.'}
          </p>
        </motion.div>
      )}

      {/* ── Educational carousel ────────────────────────────────────────── */}
      {status === 'running' && (
        <div style={{
          marginTop: T.space.xl,
          textAlign: 'center' as const,
          minHeight: 40,
          position: 'relative' as const,
        }}>
          <AnimatePresence mode="wait">
            <motion.p
              key={carouselIdx}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.5 }}
              style={{
                fontSize: 14,
                fontStyle: 'italic',
                fontFamily: "'DM Sans', sans-serif",
                color: T.text.tertiary,
                margin: 0,
                padding: `0 ${T.space.md}`,
                lineHeight: 1.5,
              }}
            >
              {CAROUSEL_FACTS[carouselIdx]}
            </motion.p>
          </AnimatePresence>
        </div>
      )}
    </motion.div>
  )
}

export default AnalysisProgress
