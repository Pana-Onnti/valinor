'use client'

import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import axios from 'axios'
import { CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Step {
  name: string
  status: 'pending' | 'running' | 'done' | 'error'
  message?: string
}

interface AnalysisProgressProps {
  analysisId: string
  onComplete: () => void
}

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

const PIPELINE_STEPS = [
  'Connecting to database',
  'Cartographer: Mapping schema',
  'Query Builder: Generating queries',
  'Analyst: Running analysis',
  'Sentinel: Security check',
  'Hunter: Finding insights',
  'Narrators: Generating report',
]

export function AnalysisProgress({ analysisId, onComplete }: AnalysisProgressProps) {
  const [steps, setSteps] = useState<Step[]>(
    PIPELINE_STEPS.map((name) => ({ name, status: 'pending' }))
  )
  const [status, setStatus] = useState<'running' | 'completed' | 'failed'>('running')
  const [progress, setProgress] = useState(0)
  const [dqScore, setDqScore] = useState<number | null>(null)
  const [dqLabel, setDqLabel] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Keep a stable ref to onComplete so the SSE/polling closures don't go stale
  const onCompleteRef = useRef(onComplete)
  useEffect(() => { onCompleteRef.current = onComplete }, [onComplete])

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

    const applyUpdate = (data: ProgressUpdate) => {
      if (data.error || data.done) return

      const p = data.progress ?? 0
      setProgress(Math.max(0, p))
      if (data.stage) {
        const completedCount = Math.floor((Math.max(0, p) / 100) * PIPELINE_STEPS.length)
        setSteps((prev) =>
          prev.map((s, i) => ({
            ...s,
            status:
              i < completedCount ? 'done' : i === completedCount ? 'running' : 'pending',
          }))
        )
      }
      if (data.status) {
        setStatus(data.status as 'running' | 'completed' | 'failed')
        if (data.status === 'failed' && data.message) {
          setErrorMessage(data.message.replace(/^Analysis failed:\s*/i, ''))
        }
      }

      if (data.dq_score !== undefined) {
        setDqScore(data.dq_score ?? null)
        setDqLabel(data.dq_label ?? null)
      }

      if (
        !completed &&
        (data.final || data.status === 'completed' || data.status === 'failed')
      ) {
        completed = true
        if (data.status === 'completed') {
          setProgress(100)
          setSteps((prev) => prev.map((s) => ({ ...s, status: 'done' })))
          setTimeout(() => onCompleteRef.current(), 1500)
        }
        cleanup()
      }
    }

    // Tier 3: HTTP polling fallback
    const startPolling = () => {
      const poll = async () => {
        if (completed) return
        try {
          const res = await axios.get(`${API_URL}/api/jobs/${analysisId}/status`)
          applyUpdate({
            job_id: analysisId,
            status: res.data.status,
            stage: res.data.stage ?? '',
            progress: res.data.progress ?? 0,
            message: res.data.message ?? '',
          })
        } catch {
          // keep polling
        }
      }
      poll()
      pollInterval = setInterval(poll, 3000)
    }

    // Tier 2: SSE fallback
    const trySSE = () => {
      try {
        eventSource = new EventSource(
          `${API_URL}/api/jobs/${analysisId}/stream`
        )

        eventSource.onmessage = (event) => {
          try {
            const data: ProgressUpdate = JSON.parse(event.data)
            applyUpdate(data)
          } catch {
            // ignore parse errors
          }
        }

        eventSource.onerror = () => {
          eventSource?.close()
          eventSource = null
          // Fall back to polling if SSE fails
          if (!completed) startPolling()
        }
      } catch {
        startPolling()
      }
    }

    // Tier 1: WebSocket (preferred)
    const tryWebSocket = () => {
      try {
        const wsUrl = API_URL.replace(/^http/, 'ws')
        ws = new WebSocket(`${wsUrl}/api/jobs/${analysisId}/ws`)

        // Give WS 3 s to connect; if it doesn't, fall back to SSE
        const wsConnectTimeout = setTimeout(() => {
          if (ws && ws.readyState !== WebSocket.OPEN) {
            ws.close()
            ws = null
            if (!completed) trySSE()
          }
        }, 3000)

        ws.onopen = () => {
          clearTimeout(wsConnectTimeout)
        }

        ws.onmessage = (event) => {
          try {
            const data: ProgressUpdate = JSON.parse(event.data)
            applyUpdate(data)
          } catch {
            // ignore parse errors
          }
        }

        ws.onerror = () => {
          clearTimeout(wsConnectTimeout)
          ws?.close()
          ws = null
          if (!completed) trySSE()
        }

        ws.onclose = (event) => {
          clearTimeout(wsConnectTimeout)
          // Abnormal closure before completion → fall back to SSE
          if (!completed && event.code !== 1000) {
            trySSE()
          }
        }
      } catch {
        trySSE()
      }
    }

    tryWebSocket()

    return cleanup
  }, [analysisId])

  const dqColor = dqScore === null ? T.text.tertiary
    : dqScore >= 85 ? T.accent.teal
    : dqScore >= 65 ? T.accent.yellow
    : T.accent.orange

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      style={{ maxWidth: 640, margin: '0 auto' }}
    >
      <div style={{
        backgroundColor: T.bg.card,
        borderRadius: T.radius.lg,
        border: T.border.card,
        padding: T.space.xl,
      }}>
        <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, marginBottom: 8 }}>
          Análisis en progreso
        </h2>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: T.space.lg,
            padding: `${T.space.xs} ${T.space.sm}`,
            backgroundColor: T.bg.elevated,
            border: T.border.card,
            borderRadius: T.radius.sm,
            cursor: 'pointer',
          }}
          onClick={() => navigator.clipboard.writeText(analysisId)}
          title="Copiar Job ID"
        >
          <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' as const, color: T.text.tertiary, flexShrink: 0, fontFamily: T.font.mono }}>
            Job ID
          </span>
          <span style={{ fontFamily: T.font.mono, fontSize: 11, color: T.text.secondary, overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}>
            {analysisId}
          </span>
          <span style={{ fontSize: 11, color: T.text.tertiary, flexShrink: 0 }}>⧉</span>
        </div>

        {/* Progress Bar */}
        <div style={{ marginBottom: T.space.xl }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: T.text.secondary, marginBottom: 8 }}>
            <span>Progreso</span>
            <span style={{ fontFamily: T.font.mono }}>{progress}%</span>
          </div>
          <div style={{ height: 8, backgroundColor: T.bg.elevated, borderRadius: 4, overflow: 'hidden' }}>
            <motion.div
              style={{ height: '100%', backgroundColor: T.accent.teal, borderRadius: 4 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>

          {dqScore !== null && (
            <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                fontSize: 11,
                fontWeight: 600,
                fontFamily: T.font.mono,
                padding: '2px 10px',
                borderRadius: 999,
                backgroundColor: dqColor + '15',
                border: `1px solid ${dqColor}40`,
                color: dqColor,
              }}>
                DQ {dqScore}/100{dqLabel ? ` · ${dqLabel}` : ''}
              </span>
            </div>
          )}
        </div>

        {/* Steps */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {steps.map((step, i) => {
            const isDone    = step.status === 'done'
            const isRunning = step.status === 'running'
            const isError   = step.status === 'error'
            const color = isDone ? T.accent.teal : isRunning ? T.accent.blue : isError ? T.accent.red : T.text.tertiary

            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ flexShrink: 0 }}>
                  {isDone    && <CheckCircle  size={18} style={{ color: T.accent.teal }} />}
                  {isRunning && <Loader2      size={18} style={{ color: T.accent.blue, animation: 'spin 1s linear infinite' }} />}
                  {step.status === 'pending' && <Clock size={18} style={{ color: T.text.tertiary }} />}
                  {isError   && <XCircle      size={18} style={{ color: T.accent.red }} />}
                </div>
                <span style={{ fontSize: 13, fontWeight: isDone || isRunning ? 500 : 400, color }}>
                  {step.name}
                </span>
              </div>
            )
          })}
        </div>

        {status === 'failed' && (
          <div style={{
            marginTop: T.space.lg,
            padding: T.space.md,
            backgroundColor: T.accent.red + '10',
            borderRadius: T.radius.sm,
            border: `1px solid ${T.accent.red}30`,
          }}>
            <p style={{ fontSize: 13, fontWeight: 600, color: T.accent.red, margin: '0 0 4px' }}>Análisis fallido</p>
            <p style={{ fontSize: 11, color: T.accent.red, fontFamily: T.font.mono, wordBreak: 'break-all', margin: 0 }}>
              {errorMessage || 'Error desconocido. Revisá las credenciales e intentá nuevamente.'}
            </p>
          </div>
        )}
      </div>
    </motion.div>
  )
}

export default AnalysisProgress
