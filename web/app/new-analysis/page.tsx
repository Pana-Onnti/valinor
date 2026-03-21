'use client'

import { useState } from 'react'
import { motion } from 'framer-motion'
import { Network, Map, Cpu, BrainCircuit, FileText, CheckCircle2 } from 'lucide-react'
import { AnalysisForm } from '@/components/AnalysisForm'
import { AnalysisProgress } from '@/components/AnalysisProgress'
import { ResultsDisplay } from '@/components/ResultsDisplay'
import { T } from '@/components/d4c/tokens'

const PIPELINE_STEPS = [
  { icon: Network,      label: 'SSH Tunnel',    description: 'Conexión cifrada y efímera a tu servidor' },
  { icon: Map,          label: 'Cartographer',  description: 'Mapeo automático de tablas y entidades' },
  { icon: Cpu,          label: 'Query Builder', description: 'Generación de consultas de negocio' },
  { icon: BrainCircuit, label: 'AI Agents',     description: 'Analyst · Sentinel · Hunter en paralelo' },
  { icon: FileText,     label: 'Report',        description: 'Reporte ejecutivo listo para el CEO' },
]

const WIZARD_STEPS = [
  { short: 'Sistema',  long: '¿Qué sistema usás?' },
  { short: 'Conexión', long: 'Conectá tu base de datos' },
  { short: 'Lanzar',   long: 'Confirmar y lanzar' },
]

function WizardStepBar({ step }: { step: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
      {WIZARD_STEPS.map((s, i) => {
        const done   = i < step
        const active = i === step
        const color  = done ? T.accent.teal : active ? T.accent.teal : T.text.tertiary
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              width: 28, height: 28, borderRadius: '50%',
              fontSize: 11, fontWeight: 700, fontFamily: T.font.mono,
              backgroundColor: done ? T.accent.teal : active ? T.accent.teal + '20' : T.bg.elevated,
              color: done ? T.text.inverse : active ? T.accent.teal : T.text.tertiary,
              border: active ? `2px solid ${T.accent.teal}` : '2px solid transparent',
            }}>
              {done ? <CheckCircle2 size={14} /> : i + 1}
            </div>
            <span style={{ marginLeft: 8, fontSize: 12, fontWeight: 500, color, whiteSpace: 'nowrap' as const }}>
              {s.short}
            </span>
            {i < WIZARD_STEPS.length - 1 && (
              <div style={{ width: 40, height: 1, backgroundColor: done ? T.accent.teal : T.bg.hover, margin: '0 12px' }} />
            )}
          </div>
        )
      })}
      <span style={{ marginLeft: 16, fontSize: 11, color: T.text.tertiary, fontFamily: T.font.mono, whiteSpace: 'nowrap' as const }}>
        Paso {step + 1} de {WIZARD_STEPS.length}
      </span>
    </div>
  )
}

function PipelineSidebar() {
  return (
    <aside style={{ display: 'none', flexDirection: 'column' as const, width: 280, flexShrink: 0 }}>
      {/* Note: use lg breakpoint — kept as display:none since CSS media queries aren't inline.
          A future pass can add a CSS class for lg:flex. */}
      <div style={{ position: 'sticky', top: 96 }}>
        <p style={{ fontSize: 10, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.accent.teal, marginBottom: T.space.md }}>
          Lo que hace Valinor
        </p>
        <ol style={{ position: 'relative', borderLeft: `2px solid ${T.bg.hover}`, padding: 0, margin: 0, listStyle: 'none' }}>
          {PIPELINE_STEPS.map((ps, i) => {
            const Icon = ps.icon
            return (
              <motion.li
                key={i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.08 }}
                style={{ marginLeft: 24, paddingBottom: i < PIPELINE_STEPS.length - 1 ? T.space.xl : 0, position: 'relative' }}
              >
                <span style={{
                  position: 'absolute',
                  left: -36,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  width: 28, height: 28, borderRadius: '50%',
                  backgroundColor: T.bg.card,
                  border: `2px solid ${T.bg.hover}`,
                }}>
                  <Icon size={13} style={{ color: T.accent.teal }} />
                </span>
                <div style={{ paddingLeft: 8 }}>
                  <p style={{ fontSize: 13, fontWeight: 600, color: T.text.primary, lineHeight: 1.3, margin: 0 }}>{ps.label}</p>
                  <p style={{ fontSize: 11, color: T.text.secondary, marginTop: 2, lineHeight: 1.4 }}>{ps.description}</p>
                </div>
              </motion.li>
            )
          })}
        </ol>

        <div style={{
          marginTop: T.space.xl,
          padding: `${T.space.sm} ${T.space.md}`,
          backgroundColor: T.accent.teal + '10',
          border: `1px solid ${T.accent.teal}30`,
          borderRadius: T.radius.sm,
        }}>
          <p style={{ fontSize: 12, fontWeight: 600, color: T.accent.teal, marginBottom: 4 }}>Zero Data Storage</p>
          <p style={{ fontSize: 11, color: T.accent.teal, lineHeight: 1.4, margin: 0, opacity: 0.8 }}>
            Tus datos nunca salen de tu servidor. Valinor solo lee, nunca escribe ni almacena.
          </p>
        </div>
      </div>
    </aside>
  )
}

export default function NewAnalysisPage() {
  const [wizardStep, setWizardStep] = useState(0)
  const [stage, setStage] = useState<'setup' | 'running' | 'complete'>('setup')
  const [analysisId, setAnalysisId] = useState<string | null>(null)

  const handleStartAnalysis = (jobId: string) => {
    setAnalysisId(jobId)
    setStage('running')
  }

  const handleAnalysisComplete = () => setStage('complete')

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* Page header */}
      <div style={{
        borderBottom: T.border.card,
        backgroundColor: T.bg.card,
        padding: `${T.space.md} ${T.space.xl}`,
        position: 'sticky',
        top: 0,
        zIndex: 40,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <h1 style={{ fontSize: 15, fontWeight: 600, color: T.text.primary, margin: 0 }}>Nuevo análisis</h1>
        <div>
          {stage === 'setup' && <WizardStepBar step={wizardStep} />}
          {stage === 'running' && (
            <span style={{ fontSize: 10, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.accent.blue }}>
              Analizando...
            </span>
          )}
          {stage === 'complete' && (
            <span style={{ fontSize: 10, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.accent.teal }}>
              Análisis completo
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <main style={{ maxWidth: 1200, margin: '0 auto', padding: T.space.xl }}>
        {stage === 'setup' && (
          <div style={{ display: 'flex', gap: T.space.xxl, alignItems: 'flex-start' }}>
            <PipelineSidebar />
            <div style={{ flex: 1, minWidth: 0 }}>
              <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
                <div
                  onClick={(e) => {
                    const btn = (e.target as HTMLElement).closest('button')
                    if (!btn) return
                    const text = btn.textContent?.trim() ?? ''
                    if (text.startsWith('Continuar')) setWizardStep(s => Math.min(s + 1, WIZARD_STEPS.length - 1))
                    else if (text.startsWith('Atrás')) setWizardStep(s => Math.max(s - 1, 0))
                  }}
                >
                  <AnalysisForm onStartAnalysis={handleStartAnalysis} />
                </div>
              </motion.div>
            </div>
          </div>
        )}

        {stage === 'running' && analysisId && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <AnalysisProgress analysisId={analysisId} onComplete={handleAnalysisComplete} />
          </motion.div>
        )}

        {stage === 'complete' && analysisId && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
            <ResultsDisplay
              analysisId={analysisId}
              onNewAnalysis={() => { setStage('setup'); setAnalysisId(null); setWizardStep(0) }}
            />
          </motion.div>
        )}
      </main>
    </div>
  )
}
