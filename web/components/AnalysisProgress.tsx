'use client'

import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import axios from 'axios'
import { CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react'

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

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-2xl mx-auto"
    >
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
          Análisis en progreso
        </h2>
        <div
          className="flex items-center gap-2 mb-6 px-3 py-2 bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-700 rounded-xl cursor-pointer group"
          onClick={() => navigator.clipboard.writeText(analysisId)}
          title="Copiar Job ID"
        >
          <span className="text-xs text-gray-400 uppercase tracking-wide font-medium flex-shrink-0">Job ID</span>
          <span className="font-mono text-xs text-gray-700 dark:text-gray-300 truncate flex-1">{analysisId}</span>
          <span className="text-xs text-gray-400 group-hover:text-violet-500 transition-colors flex-shrink-0">📋</span>
        </div>

        {/* Progress Bar */}
        <div className="mb-8">
          <div className="flex justify-between text-sm text-gray-600 dark:text-gray-400 mb-2">
            <span>Progress</span>
            <span>{progress}%</span>
          </div>
          <div className="h-3 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
            <motion.div
              className="h-full bg-indigo-600 rounded-full"
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>

          {/* DQ Score badge — shown as soon as it arrives */}
          {dqScore !== null && (
            <div className="mt-2 flex items-center gap-2 text-sm">
              <span
                className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                  dqScore >= 85
                    ? 'bg-green-100 text-green-700'
                    : dqScore >= 65
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-orange-100 text-orange-700'
                }`}
              >
                DQ {dqScore}/100{dqLabel ? ` · ${dqLabel}` : ''}
              </span>
            </div>
          )}
        </div>

        {/* Steps */}
        <div className="space-y-3">
          {steps.map((step, i) => (
            <div key={i} className="flex items-center">
              <div className="mr-3 flex-shrink-0">
                {step.status === 'done' && (
                  <CheckCircle className="h-5 w-5 text-green-500" />
                )}
                {step.status === 'running' && (
                  <Loader2 className="h-5 w-5 text-indigo-600 animate-spin" />
                )}
                {step.status === 'pending' && (
                  <Clock className="h-5 w-5 text-gray-300 dark:text-gray-600" />
                )}
                {step.status === 'error' && (
                  <XCircle className="h-5 w-5 text-red-500" />
                )}
              </div>
              <span
                className={`text-sm ${
                  step.status === 'done'
                    ? 'text-gray-900 dark:text-white font-medium'
                    : step.status === 'running'
                    ? 'text-indigo-600 dark:text-indigo-400 font-medium'
                    : 'text-gray-400 dark:text-gray-600'
                }`}
              >
                {step.name}
              </span>
            </div>
          ))}
        </div>

        {status === 'failed' && (
          <div className="mt-6 p-4 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
            <p className="text-sm font-semibold text-red-700 dark:text-red-400 mb-1">Análisis fallido</p>
            <p className="text-xs text-red-600 dark:text-red-400 font-mono break-words">
              {errorMessage || 'Error desconocido. Revisá las credenciales e intentá nuevamente.'}
            </p>
          </div>
        )}
      </div>
    </motion.div>
  )
}

export default AnalysisProgress
