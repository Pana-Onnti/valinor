'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  ArrowLeft,
  Database,
  Network,
  Map,
  Cpu,
  BrainCircuit,
  FileText,
  CheckCircle2,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { AnalysisForm } from '@/components/AnalysisForm'
import { AnalysisProgress } from '@/components/AnalysisProgress'
import { ResultsDisplay } from '@/components/ResultsDisplay'

// ── Pipeline step labels shown in sidebar ────────────────────────────────────
const PIPELINE_STEPS = [
  {
    icon: Network,
    label: 'SSH Tunnel',
    description: 'Conexión cifrada y efímera a tu servidor',
  },
  {
    icon: Map,
    label: 'Cartographer',
    description: 'Mapeo automático de tablas y entidades',
  },
  {
    icon: Cpu,
    label: 'Query Builder',
    description: 'Generación de consultas de negocio',
  },
  {
    icon: BrainCircuit,
    label: 'AI Agents',
    description: 'Analyst · Sentinel · Hunter en paralelo',
  },
  {
    icon: FileText,
    label: 'Report',
    description: 'Reporte ejecutivo listo para el CEO',
  },
]

// ── Step labels used by the wizard (3 steps, 0-indexed) ──────────────────────
const WIZARD_STEPS = [
  { short: 'Sistema', long: '¿Qué sistema usás?' },
  { short: 'Conexión', long: 'Conectá tu base de datos' },
  { short: 'Lanzar', long: 'Confirmar y lanzar' },
]

// ── Top step-indicator bar ────────────────────────────────────────────────────
function WizardStepBar({ step }: { step: number }) {
  return (
    <div className="flex items-center gap-0">
      {WIZARD_STEPS.map((s, i) => {
        const done = i < step
        const active = i === step
        return (
          <div key={i} className="flex items-center">
            {/* circle */}
            <div
              className={`flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold transition-all ${
                done
                  ? 'bg-violet-600 text-white'
                  : active
                  ? 'bg-violet-100 dark:bg-violet-900/50 text-violet-700 dark:text-violet-300 ring-2 ring-violet-500'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-400'
              }`}
            >
              {done ? <CheckCircle2 className="h-4 w-4" /> : i + 1}
            </div>
            {/* label — visible on sm+ */}
            <span
              className={`hidden sm:block ml-2 text-sm font-medium transition-colors ${
                active
                  ? 'text-gray-900 dark:text-white'
                  : done
                  ? 'text-violet-600 dark:text-violet-400'
                  : 'text-gray-400'
              }`}
            >
              {s.short}
            </span>
            {/* connector line */}
            {i < WIZARD_STEPS.length - 1 && (
              <div
                className={`mx-3 h-px w-10 sm:w-16 transition-all ${
                  done ? 'bg-violet-500' : 'bg-gray-200 dark:bg-gray-700'
                }`}
              />
            )}
          </div>
        )
      })}
      <span className="ml-4 text-xs text-gray-400 font-mono whitespace-nowrap">
        Paso {step + 1} de {WIZARD_STEPS.length}
      </span>
    </div>
  )
}

// ── Sidebar — "Lo que hace Valinor" ──────────────────────────────────────────
function PipelineSidebar() {
  return (
    <aside className="hidden lg:flex flex-col w-72 xl:w-80 flex-shrink-0">
      <div className="sticky top-24">
        <p className="text-xs font-mono tracking-widest text-indigo-500 uppercase mb-4">
          Lo que hace Valinor
        </p>

        <ol className="relative border-l-2 border-gray-200 dark:border-gray-700 space-y-0">
          {PIPELINE_STEPS.map((ps, i) => {
            const Icon = ps.icon
            return (
              <motion.li
                key={i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.08 }}
                className="ml-6 pb-7 last:pb-0"
              >
                {/* timeline dot / icon */}
                <span className="absolute -left-[1.15rem] flex items-center justify-center w-9 h-9 rounded-full bg-white dark:bg-gray-900 border-2 border-gray-200 dark:border-gray-700 ring-4 ring-white dark:ring-gray-900">
                  <Icon className="h-4 w-4 text-indigo-500 dark:text-indigo-400" />
                </span>

                <div className="pt-1 pl-2">
                  <p className="text-sm font-semibold text-gray-900 dark:text-white leading-tight">
                    {ps.label}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">
                    {ps.description}
                  </p>
                </div>
              </motion.li>
            )
          })}
        </ol>

        {/* Zero-data guarantee callout */}
        <div className="mt-8 px-4 py-3 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-2xl">
          <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-300 mb-1">
            Zero Data Storage
          </p>
          <p className="text-xs text-emerald-600 dark:text-emerald-400 leading-snug">
            Tus datos nunca salen de tu servidor. Valinor solo lee, nunca escribe ni almacena.
          </p>
        </div>
      </div>
    </aside>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function NewAnalysisPage() {
  const router = useRouter()
  const [wizardStep, setWizardStep] = useState(0)
  const [stage, setStage] = useState<'setup' | 'running' | 'complete'>('setup')
  const [analysisId, setAnalysisId] = useState<string | null>(null)

  const handleStartAnalysis = (jobId: string) => {
    setAnalysisId(jobId)
    setStage('running')
  }

  const handleAnalysisComplete = () => {
    setStage('complete')
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-blue-50 dark:from-gray-900 dark:via-gray-800 dark:to-indigo-900">
      {/* ── Header ── */}
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between py-4 gap-6">
            {/* Back link */}
            <Link
              href="/dashboard"
              className="flex items-center gap-2 text-sm text-gray-500 hover:text-violet-600 dark:text-gray-400 dark:hover:text-violet-400 transition-colors flex-shrink-0"
            >
              <ArrowLeft className="h-4 w-4" />
              <span className="hidden sm:inline">Dashboard</span>
            </Link>

            {/* Branding */}
            <div className="flex items-center gap-2 flex-shrink-0">
              <Database className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
              <span className="font-bold text-gray-900 dark:text-white text-sm sm:text-base">
                Valinor SaaS
              </span>
            </div>

            {/* Wizard step indicator — only during setup */}
            <div className="flex-1 flex justify-end">
              {stage === 'setup' && (
                <WizardStepBar step={wizardStep} />
              )}
              {stage === 'running' && (
                <span className="text-xs font-mono text-indigo-500 uppercase tracking-widest">
                  Analizando...
                </span>
              )}
              {stage === 'complete' && (
                <span className="text-xs font-mono text-emerald-500 uppercase tracking-widest">
                  Análisis completo
                </span>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* ── Body ── */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {stage === 'setup' && (
          <div className="flex gap-12 xl:gap-16 items-start">
            {/* Sidebar */}
            <PipelineSidebar />

            {/* Form area */}
            <div className="flex-1 min-w-0">
              <motion.div
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
              >
                {/*
                  AnalysisForm manages its own step state internally.
                  We use a wrapper that intercepts the step changes through
                  a key-based re-render approach — but since AnalysisForm
                  exposes no onStepChange prop, we mirror its internal
                  step by having the form call onStartAnalysis when done,
                  and we sync visible steps via onChange on each step button.

                  To keep the header indicator in sync we wrap the form in a
                  div and intercept clicks on the Continuar / Atrás buttons
                  via event delegation.
                */}
                <div
                  onClick={(e) => {
                    const target = e.target as HTMLElement
                    const btn = target.closest('button')
                    if (!btn) return
                    const text = btn.textContent?.trim() ?? ''
                    if (text.startsWith('Continuar')) {
                      setWizardStep(s => Math.min(s + 1, WIZARD_STEPS.length - 1))
                    } else if (text.startsWith('Atrás')) {
                      setWizardStep(s => Math.max(s - 1, 0))
                    }
                  }}
                >
                  <AnalysisForm onStartAnalysis={handleStartAnalysis} />
                </div>
              </motion.div>
            </div>
          </div>
        )}

        {stage === 'running' && analysisId && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <AnalysisProgress
              analysisId={analysisId}
              onComplete={handleAnalysisComplete}
            />
          </motion.div>
        )}

        {stage === 'complete' && analysisId && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <ResultsDisplay
              analysisId={analysisId}
              onNewAnalysis={() => {
                setStage('setup')
                setAnalysisId(null)
                setWizardStep(0)
              }}
            />
          </motion.div>
        )}
      </main>

      {/* ── Footer ── */}
      <footer className="mt-auto border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex justify-between items-center text-sm text-gray-500 dark:text-gray-400">
            <p>© 2026 Delta 4C — Valinor SaaS v2.0</p>
            <Link href="/docs" className="hover:text-violet-600 dark:hover:text-violet-400 transition-colors">
              API docs
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
