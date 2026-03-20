'use client'

import { useEffect, useState } from 'react'
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

  useEffect(() => {
    let interval: NodeJS.Timeout

    const poll = async () => {
      try {
        const res = await axios.get(`${API_URL}/api/jobs/${analysisId}/status`)
        const data = res.data

        if (data.status === 'completed') {
          setStatus('completed')
          setProgress(100)
          setSteps((prev) => prev.map((s) => ({ ...s, status: 'done' })))
          clearInterval(interval)
          setTimeout(onComplete, 1500)
        } else if (data.status === 'failed') {
          setStatus('failed')
          clearInterval(interval)
        } else {
          const p = data.progress || 0
          setProgress(p)
          const completedCount = Math.floor((p / 100) * PIPELINE_STEPS.length)
          setSteps((prev) =>
            prev.map((s, i) => ({
              ...s,
              status:
                i < completedCount ? 'done' : i === completedCount ? 'running' : 'pending',
            }))
          )
        }
      } catch {
        // keep polling
      }
    }

    poll()
    interval = setInterval(poll, 3000)
    return () => clearInterval(interval)
  }, [analysisId, onComplete])

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-2xl mx-auto"
    >
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
          Analysis in Progress
        </h2>
        <p className="text-gray-500 dark:text-gray-400 text-sm mb-6">
          Job ID: <span className="font-mono">{analysisId}</span>
        </p>

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
          <div className="mt-6 p-4 bg-red-50 dark:bg-red-900/20 rounded-lg text-red-600 dark:text-red-400 text-sm">
            Analysis failed. Please check your database credentials and try again.
          </div>
        )}
      </div>
    </motion.div>
  )
}
