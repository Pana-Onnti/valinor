'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import axios from 'axios'
import {
  ChevronRight, ChevronLeft, Zap,
  CheckCircle2, Shield, Clock, AlertTriangle, Lock,
  ArrowRight, Loader2, Calendar,
  Truck, Store, Factory, Briefcase, Wheat, Building2,
  TrendingDown, BarChart3, Users, MessageSquare,
  Database, FileSpreadsheet, Eye, Trash2, HelpCircle,
} from 'lucide-react'
import { T } from '@/components/d4c/tokens'
import FileUpload from '@/components/FileUpload'
import DataPreview from '@/components/DataPreview'
import { startFileAnalysis } from '@/lib/api'
import type { UploadResult } from '@/lib/types'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Industry Options ────────────────────────────────────────────────────────
const INDUSTRY_OPTIONS = [
  { id: 'distribucion', name: 'Distribucion', icon: Truck },
  { id: 'retail', name: 'Retail', icon: Store },
  { id: 'manufactura', name: 'Manufactura', icon: Factory },
  { id: 'servicios', name: 'Servicios', icon: Briefcase },
  { id: 'agro', name: 'Agro', icon: Wheat },
  { id: 'otro', name: 'Otro', icon: Building2 },
]

// ── Goal Options ────────────────────────────────────────────────────────────
const GOAL_OPTIONS = [
  { id: 'perdidas', label: 'Donde estoy perdiendo plata', icon: TrendingDown, accent: T.accent.red },
  { id: 'numeros', label: 'Quiero entender mis numeros', icon: BarChart3, accent: T.accent.blue },
  { id: 'clientes', label: 'Analizar mis clientes', icon: Users, accent: T.accent.teal },
  { id: 'concreto', label: 'Tengo un problema concreto', icon: MessageSquare, accent: T.accent.orange },
]

// ── ERP Options ──────────────────────────────────────────────────────────────
const ERP_OPTIONS = [
  {
    id: 'openbravo',
    name: 'Openbravo',
    description: 'ERP para distribucion, manufactura y retail',
    abbr: 'OB',
    db: 'postgresql',
    popular: true,
    hints: ['c_invoice', 'c_bpartner', 'm_product'],
  },
  {
    id: 'odoo',
    name: 'Odoo',
    description: 'ERP open source todo-en-uno',
    abbr: 'OD',
    db: 'postgresql',
    hints: ['account_move', 'res_partner', 'product_template'],
  },
  {
    id: 'sap',
    name: 'SAP',
    description: 'SAP ECC / S/4HANA',
    abbr: 'SP',
    db: 'sqlserver',
    hints: ['BKPF', 'VBAK', 'KNA1'],
  },
  {
    id: 'tango',
    name: 'Tango Gestion',
    description: 'ERP lider en Argentina',
    abbr: 'TG',
    db: 'sqlserver',
    hints: [],
  },
  {
    id: 'bejerman',
    name: 'Bejerman',
    description: 'ERP argentino para PyMEs',
    abbr: 'BJ',
    db: 'sqlserver',
    hints: [],
  },
  {
    id: 'mysql_generic',
    name: 'MySQL / MariaDB',
    description: 'Base de datos relacional generica',
    abbr: 'MY',
    db: 'mysql',
    hints: [],
  },
  {
    id: 'postgres_generic',
    name: 'PostgreSQL',
    description: 'Base de datos relacional avanzada',
    abbr: 'PG',
    db: 'postgresql',
    hints: [],
  },
  {
    id: 'excel',
    name: 'Excel / CSV',
    description: 'Archivos exportados desde cualquier sistema',
    abbr: 'XL',
    db: 'sqlite',
    hints: [],
  },
]

// ── Zod schema ────────────────────────────────────────────────────────────────
const ConnectionSchema = z.object({
  client_name: z.string().min(2, 'Minimo 2 caracteres'),
  erp_type: z.string().min(1, 'Selecciona un sistema'),
  db_host: z.string().optional().default(''),
  db_port: z.coerce.number().int().min(1).max(65535).default(5432),
  db_name: z.string().optional().default(''),
  db_user: z.string().optional().default(''),
  db_password: z.string().optional().default(''),
  db_type: z.string().default('postgresql'),
  period: z.string().min(1, 'Periodo requerido'),
  use_ssh: z.boolean().default(false),
  ssh_host: z.string().optional(),
  ssh_user: z.string().optional(),
  ssh_key_path: z.string().optional(),
  industry: z.string().optional(),
  goal: z.string().optional(),
  goal_detail: z.string().optional(),
})

type ConnectionFormData = z.infer<typeof ConnectionSchema>

interface TestResult {
  success: boolean
  latency_ms?: number
  erp_detected?: string
  error?: string
  table_count?: number
  data_from?: string
  data_to?: string
}

interface AnalysisFormProps {
  onStartAnalysis: (jobId: string) => void
}

// ── Period helpers ────────────────────────────────────────────────────────────
const ES_MONTHS = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
const Q_RANGES  = [['Ene','Mar'],['Abr','Jun'],['Jul','Sep'],['Oct','Dic']]

function buildMonthOptions(dataFrom?: string, dataTo?: string) {
  const now = new Date()
  const toYear   = dataTo   ? parseInt(dataTo.slice(0, 4))   : now.getFullYear()
  const toMonth  = dataTo   ? parseInt(dataTo.slice(5, 7))   : now.getMonth() + 1
  const fromYear = dataFrom ? parseInt(dataFrom.slice(0, 4)) : toYear - 2
  const fromMonth= dataFrom ? parseInt(dataFrom.slice(5, 7)) : 1

  const options: { value: string; label: string }[] = []
  let y = toYear, m = toMonth
  while ((y > fromYear || (y === fromYear && m >= fromMonth)) && options.length < 24) {
    options.push({
      value: `${y}-${String(m).padStart(2, '0')}`,
      label: `${ES_MONTHS[m - 1]} ${y}`,
    })
    m--
    if (m < 1) { m = 12; y-- }
  }
  return options
}

function buildQuarterOptions(dataFrom?: string, dataTo?: string) {
  const now = new Date()
  const toYear  = dataTo   ? parseInt(dataTo.slice(0, 4))   : now.getFullYear()
  const toQ     = dataTo   ? Math.ceil(parseInt(dataTo.slice(5, 7)) / 3) : Math.ceil((now.getMonth() + 1) / 3)
  const fromYear= dataFrom ? parseInt(dataFrom.slice(0, 4)) : toYear - 2

  const options: { value: string; label: string }[] = []
  let y = toYear, q = toQ
  while (y >= fromYear && options.length < 12) {
    options.push({
      value: `Q${q}-${y}`,
      label: `Q${q} ${y}  (${Q_RANGES[q - 1][0]}–${Q_RANGES[q - 1][1]})`,
    })
    q--
    if (q < 1) { q = 4; y-- }
  }
  return options
}

function buildYearOptions(dataFrom?: string, dataTo?: string) {
  const now = new Date()
  const toYear  = dataTo   ? parseInt(dataTo.slice(0, 4))   : now.getFullYear()
  const fromYear= dataFrom ? parseInt(dataFrom.slice(0, 4)) : toYear - 4
  const options: { value: string; label: string }[] = []
  for (let y = toYear; y >= fromYear && options.length < 6; y--) {
    options.push({ value: String(y), label: `Ano completo ${y}` })
  }
  return options
}

// ── Tooltip helper ────────────────────────────────────────────────────────────
function Tooltip({ text }: { text: string }) {
  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', marginLeft: 4 }}>
      <HelpCircle
        size={13}
        style={{ color: T.text.tertiary, cursor: 'help' }}
        className="d4c-tooltip-trigger"
      />
      <span
        className="d4c-tooltip-content"
        style={{
          position: 'absolute',
          bottom: '100%',
          left: '50%',
          transform: 'translateX(-50%)',
          marginBottom: 6,
          padding: '6px 10px',
          borderRadius: T.radius.sm,
          backgroundColor: T.bg.elevated,
          border: T.border.card,
          color: T.text.secondary,
          fontSize: 11,
          lineHeight: 1.4,
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
          opacity: 0,
          transition: 'opacity 150ms ease',
          zIndex: 10,
        }}
      >
        {text}
      </span>
      <style>{`
        .d4c-tooltip-trigger:hover + .d4c-tooltip-content {
          opacity: 1 !important;
        }
      `}</style>
    </span>
  )
}

// ── Step indicator (redesigned: dot-based) ───────────────────────────────────
const STEP_LABELS = ['Empresa', 'Conexion', 'Analisis', 'Resultados']

function StepIndicator({ current }: { current: number }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      marginBottom: T.space.xl,
      flexWrap: 'wrap',
    }}>
      {STEP_LABELS.map((label, i) => {
        const isCompleted = i < current
        const isActive = i === current
        const isFuture = i > current
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                backgroundColor: isCompleted ? T.text.tertiary : isActive ? T.accent.teal : 'transparent',
                border: isFuture ? `1.5px solid ${T.text.tertiary}` : 'none',
                transition: 'all 200ms ease',
              }} />
              <span style={{
                fontSize: 12,
                fontWeight: isActive ? 600 : 400,
                color: isActive ? T.accent.teal : isCompleted ? T.text.tertiary : T.text.tertiary,
                fontFamily: T.font.display,
                transition: 'color 200ms ease',
              }}>
                {label}
              </span>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <span style={{ color: T.text.tertiary, fontSize: 11, margin: '0 2px' }}>·</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── Form field helpers ────────────────────────────────────────────────────────
const fieldLabel: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  fontSize: 10,
  fontWeight: 600,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: T.text.secondary,
  marginBottom: 6,
  fontFamily: T.font.mono,
}

const fieldError: React.CSSProperties = {
  fontSize: 11,
  color: T.accent.red,
  marginTop: 4,
}

// ── Trust signals strip ──────────────────────────────────────────────────────
function TrustSignals() {
  const signals = [
    { icon: Lock, text: 'Conexion encriptada TLS 1.3' },
    { icon: Eye, text: 'Solo lectura — nunca modificamos datos' },
    { icon: Trash2, text: 'Procesamiento en memoria — sin almacenamiento' },
  ]
  return (
    <div style={{
      backgroundColor: T.accent.teal + '08',
      border: `1px solid ${T.accent.teal}20`,
      borderRadius: T.radius.md,
      padding: T.space.md,
      display: 'flex',
      flexDirection: 'column',
      gap: T.space.sm,
    }}>
      <span style={{
        fontSize: 9,
        fontWeight: 700,
        letterSpacing: '0.12em',
        textTransform: 'uppercase',
        color: T.accent.teal,
        fontFamily: T.font.mono,
        marginBottom: 4,
      }}>
        Seguridad
      </span>
      {signals.map(({ icon: Icon, text }) => (
        <div key={text} style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 8,
        }}>
          <Icon size={14} style={{ color: T.accent.teal, flexShrink: 0, marginTop: 1 }} />
          <span style={{ fontSize: 12, color: T.accent.teal, lineHeight: 1.4 }}>{text}</span>
        </div>
      ))}
    </div>
  )
}

// ── Step 1: "Contanos sobre tu empresa" ──────────────────────────────────────
function Step1Company({
  selected, onSelect, clientName, onClientName,
  industry, onIndustry,
  goal, onGoal,
  goalDetail, onGoalDetail,
}: {
  selected: string
  onSelect: (id: string, db: string) => void
  clientName: string
  onClientName: (v: string) => void
  industry: string
  onIndustry: (v: string) => void
  goal: string
  onGoal: (v: string) => void
  goalDetail: string
  onGoalDetail: (v: string) => void
}) {
  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
      {/* Header */}
      <h2 style={{
        fontSize: 22,
        fontWeight: 700,
        color: T.text.primary,
        marginBottom: 4,
        fontFamily: T.font.display,
      }}>
        Primer diagnostico en menos de 10 minutos
      </h2>
      <p style={{ fontSize: 13, color: T.text.secondary, marginBottom: T.space.lg }}>
        Sin instalar nada. Sin tarjeta de credito.
      </p>

      {/* Client name */}
      <div style={{ marginBottom: T.space.lg }}>
        <label style={fieldLabel}>Nombre del cliente / empresa</label>
        <input
          type="text"
          value={clientName}
          onChange={e => onClientName(e.target.value)}
          placeholder="Ej: Gloria Distribuciones"
          className="d4c-input"
        />
      </div>

      {/* Industry selector */}
      <div style={{ marginBottom: T.space.lg }}>
        <label style={fieldLabel}>Industria</label>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 10,
        }}>
          {INDUSTRY_OPTIONS.map(ind => {
            const isSelected = industry === ind.id
            const Icon = ind.icon
            return (
              <button
                key={ind.id}
                type="button"
                onClick={() => onIndustry(ind.id)}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                  padding: `${T.space.md} ${T.space.sm}`,
                  borderRadius: T.radius.sm,
                  border: isSelected ? `2px solid ${T.accent.teal}` : `2px solid ${T.bg.hover}`,
                  backgroundColor: isSelected ? T.accent.teal + '10' : T.bg.elevated,
                  cursor: 'pointer',
                  transition: 'border-color 150ms ease, background-color 150ms ease',
                }}
              >
                <Icon size={32} style={{
                  color: isSelected ? T.accent.teal : T.text.tertiary,
                  transition: 'color 150ms ease',
                }} />
                <span style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: isSelected ? T.text.primary : T.text.secondary,
                }}>
                  {ind.name}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {/* ERP selector */}
      <div style={{ marginBottom: T.space.lg }}>
        <label style={fieldLabel}>Sistema / ERP</label>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
          {ERP_OPTIONS.map(erp => {
            const isSelected = selected === erp.id
            return (
              <button
                key={erp.id}
                type="button"
                onClick={() => onSelect(erp.id, erp.db)}
                style={{
                  position: 'relative',
                  textAlign: 'left',
                  padding: `${T.space.lg} ${T.space.md}`,
                  borderRadius: T.radius.md,
                  border: isSelected ? `2px solid ${T.accent.teal}` : `2px solid ${T.bg.hover}`,
                  backgroundColor: isSelected ? T.accent.teal + '10' : T.bg.elevated,
                  cursor: 'pointer',
                  transition: 'border-color 150ms ease, background-color 150ms ease',
                }}
              >
                {erp.popular && (
                  <span style={{
                    position: 'absolute', top: 8, right: 8,
                    fontSize: 9, fontWeight: 700, fontFamily: T.font.mono,
                    color: T.accent.teal, backgroundColor: T.accent.teal + '15',
                    padding: '2px 6px', borderRadius: 4,
                  }}>
                    Popular
                  </span>
                )}
                <div style={{
                  fontFamily: T.font.mono,
                  fontSize: 18,
                  fontWeight: 700,
                  color: isSelected ? T.accent.teal : T.text.tertiary,
                  marginBottom: 8,
                }}>
                  {erp.abbr}
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: T.text.primary }}>{erp.name}</div>
                <div style={{ fontSize: 11, color: T.text.secondary, marginTop: 3, lineHeight: 1.4 }}>
                  {erp.description}
                </div>
                <div style={{
                  fontSize: 10,
                  color: T.text.tertiary,
                  marginTop: 4,
                  fontFamily: T.font.mono,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}>
                  {erp.db}
                </div>
                {isSelected && (
                  <div style={{ position: 'absolute', bottom: 10, right: 10 }}>
                    <CheckCircle2 size={16} style={{ color: T.accent.teal }} />
                  </div>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {selected && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            marginBottom: T.space.lg,
            display: 'flex',
            alignItems: 'flex-start',
            gap: 10,
            backgroundColor: T.accent.blue + '10',
            border: `1px solid ${T.accent.blue}30`,
            borderRadius: T.radius.sm,
            padding: `${T.space.sm} ${T.space.md}`,
          }}
        >
          <Zap size={14} style={{ color: T.accent.blue, flexShrink: 0, marginTop: 1 }} />
          <p style={{ fontSize: 12, color: T.accent.blue, margin: 0 }}>
            Valinor ya conoce la estructura de {ERP_OPTIONS.find(e => e.id === selected)?.name}.
            El Cartographer priorizara las tablas de mayor valor para este ERP.
          </p>
        </motion.div>
      )}

      {/* Loss-framing question */}
      <div style={{ marginBottom: T.space.sm }}>
        <label style={fieldLabel}>Que queres entender?</label>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 10,
        }}>
          {GOAL_OPTIONS.map(g => {
            const isSelected = goal === g.id
            const Icon = g.icon
            return (
              <button
                key={g.id}
                type="button"
                onClick={() => onGoal(g.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: T.space.md,
                  borderRadius: T.radius.sm,
                  border: isSelected ? `2px solid ${g.accent}` : `2px solid ${T.bg.hover}`,
                  backgroundColor: isSelected ? g.accent + '10' : T.bg.elevated,
                  cursor: 'pointer',
                  textAlign: 'left',
                  transition: 'border-color 150ms ease, background-color 150ms ease',
                }}
              >
                <Icon size={20} style={{
                  color: isSelected ? g.accent : T.text.tertiary,
                  flexShrink: 0,
                  transition: 'color 150ms ease',
                }} />
                <span style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: isSelected ? T.text.primary : T.text.secondary,
                  lineHeight: 1.3,
                }}>
                  {g.label}
                </span>
              </button>
            )
          })}
        </div>

        {/* Free text input for "problema concreto" */}
        <AnimatePresence>
          {goal === 'concreto' && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              style={{ overflow: 'hidden' }}
            >
              <input
                type="text"
                value={goalDetail}
                onChange={e => onGoalDetail(e.target.value)}
                placeholder="Contanos brevemente tu problema..."
                className="d4c-input"
                style={{ marginTop: T.space.sm }}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}

// ── Step 2: "Conecta tu empresa" ─────────────────────────────────────────────
type ConnectionMode = 'db' | 'file' | null

function Step2Connect({
  register, errors, watch, testResult, testingConnection, onTestConnection,
  clientName,
  onUploadComplete,
  connectionMode, onConnectionMode,
  isFileMode,
}: {
  register: any
  errors: any
  watch: any
  testResult: TestResult | null
  testingConnection: boolean
  onTestConnection: () => void
  clientName: string
  onUploadComplete: (uploads: UploadResult[]) => void
  connectionMode: ConnectionMode
  onConnectionMode: (mode: ConnectionMode) => void
  isFileMode: boolean
}) {
  const useSsh = watch('use_ssh')

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, marginBottom: 4, fontFamily: T.font.display }}>
        Conecta tu empresa
      </h2>
      <p style={{ fontSize: 13, color: T.text.secondary, marginBottom: T.space.lg }}>
        Elegí como querés compartir tus datos
      </p>

      {/* Visual bifurcation cards */}
      {!isFileMode && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: connectionMode ? '1fr' : 'repeat(2, 1fr)',
          gap: T.space.md,
          marginBottom: T.space.lg,
        }}>
          {(connectionMode !== 'file') && (
            <button
              type="button"
              onClick={() => onConnectionMode('db')}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 10,
                padding: connectionMode === 'db' ? `${T.space.sm} ${T.space.md}` : T.space.xl,
                borderRadius: T.radius.md,
                border: connectionMode === 'db' ? `2px solid ${T.accent.teal}` : `2px solid ${T.bg.hover}`,
                backgroundColor: connectionMode === 'db' ? T.accent.teal + '10' : T.bg.elevated,
                cursor: 'pointer',
                transition: 'all 200ms ease',
              }}
            >
              <Database size={connectionMode === 'db' ? 20 : 36} style={{ color: connectionMode === 'db' ? T.accent.teal : T.text.tertiary }} />
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: T.text.primary }}>
                  Tengo una base de datos
                </div>
                <div style={{ fontSize: 11, color: T.text.secondary, marginTop: 2 }}>
                  PostgreSQL, MySQL, SQL Server...
                </div>
              </div>
              {connectionMode === 'db' && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onConnectionMode(null) }}
                  style={{
                    fontSize: 11,
                    color: T.text.tertiary,
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    textDecoration: 'underline',
                    padding: 0,
                  }}
                >
                  Cambiar
                </button>
              )}
            </button>
          )}
          {(connectionMode !== 'db') && (
            <button
              type="button"
              onClick={() => onConnectionMode('file')}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 10,
                padding: connectionMode === 'file' ? `${T.space.sm} ${T.space.md}` : T.space.xl,
                borderRadius: T.radius.md,
                border: connectionMode === 'file' ? `2px solid ${T.accent.teal}` : `2px solid ${T.bg.hover}`,
                backgroundColor: connectionMode === 'file' ? T.accent.teal + '10' : T.bg.elevated,
                cursor: 'pointer',
                transition: 'all 200ms ease',
              }}
            >
              <FileSpreadsheet size={connectionMode === 'file' ? 20 : 36} style={{ color: connectionMode === 'file' ? T.accent.teal : T.text.tertiary }} />
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: T.text.primary }}>
                  Tengo archivos Excel o CSV
                </div>
                <div style={{ fontSize: 11, color: T.text.secondary, marginTop: 2 }}>
                  Arrastra tu archivo aca
                </div>
              </div>
              {connectionMode === 'file' && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onConnectionMode(null) }}
                  style={{
                    fontSize: 11,
                    color: T.text.tertiary,
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    textDecoration: 'underline',
                    padding: 0,
                  }}
                >
                  Cambiar
                </button>
              )}
            </button>
          )}
        </div>
      )}

      {/* Content + trust signals layout */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: (connectionMode || isFileMode) ? '1fr 200px' : '1fr',
        gap: T.space.lg,
        alignItems: 'start',
      }}>
        {/* Left: form content */}
        <div>
          {/* DB connection form */}
          <AnimatePresence mode="wait">
            {connectionMode === 'db' && !isFileMode && (
              <motion.div
                key="db-form"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
              >
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: T.space.md }}>
                  <div style={{ gridColumn: 'span 1' }}>
                    <label style={fieldLabel}>
                      Host
                      <Tooltip text="La direccion IP o dominio de tu servidor de base de datos" />
                    </label>
                    <input {...register('db_host')} placeholder="localhost" className="d4c-input" />
                    {errors.db_host && <p style={fieldError}>{errors.db_host.message}</p>}
                  </div>
                  <div>
                    <label style={fieldLabel}>
                      Puerto
                      <Tooltip text="Puerto por defecto: PostgreSQL=5432, MySQL=3306, SQL Server=1433" />
                    </label>
                    <input {...register('db_port')} type="number" placeholder="5432" className="d4c-input" />
                  </div>
                  <div style={{ gridColumn: 'span 2' }}>
                    <label style={fieldLabel}>
                      Base de datos
                      <Tooltip text="El nombre de la base de datos a la que queres conectarte" />
                    </label>
                    <input {...register('db_name')} placeholder="nombre_de_la_base" className="d4c-input" />
                    {errors.db_name && <p style={fieldError}>{errors.db_name.message}</p>}
                  </div>
                  <div>
                    <label style={fieldLabel}>
                      Usuario
                      <Tooltip text="Un usuario con permisos de solo lectura es suficiente" />
                    </label>
                    <input {...register('db_user')} placeholder="readonly_user" className="d4c-input" />
                    {errors.db_user && <p style={fieldError}>{errors.db_user.message}</p>}
                  </div>
                  <div>
                    <label style={fieldLabel}>
                      Contrasena
                      <Tooltip text="La contrasena se transmite encriptada y no se almacena" />
                    </label>
                    <input {...register('db_password')} type="password" placeholder="••••••••" className="d4c-input" />
                    {errors.db_password && <p style={fieldError}>{errors.db_password.message}</p>}
                  </div>

                  <div style={{ gridColumn: 'span 2', marginTop: 4 }}>
                    <button
                      type="button"
                      onClick={onTestConnection}
                      disabled={testingConnection || !watch('db_host') || !watch('db_user')}
                      style={{
                        width: '100%',
                        padding: `${T.space.sm} ${T.space.md}`,
                        borderRadius: T.radius.sm,
                        border: `1px solid ${T.accent.teal}50`,
                        backgroundColor: 'transparent',
                        color: T.accent.teal,
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: 'pointer',
                        fontFamily: T.font.display,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 6,
                        opacity: testingConnection || !watch('db_host') || !watch('db_user') ? 0.5 : 1,
                        transition: 'opacity 150ms ease',
                      }}
                    >
                      {testingConnection ? (
                        <><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />Probando conexion...</>
                      ) : 'Probar conexion'}
                    </button>

                    {testResult && (
                      <motion.div
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        style={{
                          marginTop: 8,
                          borderRadius: T.radius.sm,
                          padding: T.space.md,
                          fontSize: 12,
                          backgroundColor: testResult.success ? T.accent.teal + '10' : T.accent.red + '10',
                          border: `1px solid ${testResult.success ? T.accent.teal : T.accent.red}30`,
                          color: testResult.success ? T.accent.teal : T.accent.red,
                        }}
                      >
                        {testResult.success ? (
                          <div>
                            <div style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 8,
                              marginBottom: 8,
                            }}>
                              <CheckCircle2 size={18} style={{ color: T.accent.teal }} />
                              <span style={{ fontSize: 15, fontWeight: 700 }}>Conexion exitosa</span>
                            </div>
                            <div style={{
                              display: 'grid',
                              gridTemplateColumns: 'repeat(3, 1fr)',
                              gap: 8,
                            }}>
                              <div style={{
                                textAlign: 'center',
                                padding: T.space.sm,
                                backgroundColor: T.accent.teal + '10',
                                borderRadius: T.radius.sm,
                              }}>
                                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: T.font.mono }}>
                                  {testResult.table_count}
                                </div>
                                <div style={{ fontSize: 10, color: T.accent.teal, marginTop: 2 }}>tablas</div>
                              </div>
                              <div style={{
                                textAlign: 'center',
                                padding: T.space.sm,
                                backgroundColor: T.accent.teal + '10',
                                borderRadius: T.radius.sm,
                              }}>
                                <div style={{ fontSize: 14, fontWeight: 600, fontFamily: T.font.mono }}>
                                  {testResult.latency_ms}ms
                                </div>
                                <div style={{ fontSize: 10, color: T.accent.teal, marginTop: 2 }}>latencia</div>
                              </div>
                              <div style={{
                                textAlign: 'center',
                                padding: T.space.sm,
                                backgroundColor: T.accent.teal + '10',
                                borderRadius: T.radius.sm,
                              }}>
                                <div style={{ fontSize: 12, fontWeight: 600, fontFamily: T.font.mono }}>
                                  {testResult.erp_detected || '—'}
                                </div>
                                <div style={{ fontSize: 10, color: T.accent.teal, marginTop: 2 }}>ERP</div>
                              </div>
                            </div>
                            {testResult.data_from && testResult.data_to && (
                              <p style={{ margin: '8px 0 0', display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                                <Calendar size={10} />
                                Datos: <strong>{testResult.data_from}</strong> → <strong>{testResult.data_to}</strong>
                              </p>
                            )}
                          </div>
                        ) : (
                          <div>
                            <p style={{ margin: 0, fontWeight: 600 }}>Error: {testResult.error}</p>
                            <p style={{
                              margin: '6px 0 0',
                              fontSize: 11,
                              color: T.text.tertiary,
                              cursor: 'pointer',
                              textDecoration: 'underline',
                            }}>
                              Necesitas ayuda?
                            </p>
                          </div>
                        )}
                      </motion.div>
                    )}
                  </div>
                </div>

                {/* SSH toggle */}
                <div style={{ marginTop: T.space.lg }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
                    <div style={{
                      position: 'relative',
                      width: 40,
                      height: 20,
                      borderRadius: 10,
                      backgroundColor: useSsh ? T.accent.teal : T.bg.hover,
                      transition: 'background-color 150ms ease',
                    }}>
                      <input type="checkbox" {...register('use_ssh')} style={{ position: 'absolute', opacity: 0, width: 0, height: 0 }} />
                      <span style={{
                        position: 'absolute',
                        top: 2,
                        left: useSsh ? 22 : 2,
                        width: 16,
                        height: 16,
                        backgroundColor: T.text.primary,
                        borderRadius: '50%',
                        transition: 'left 150ms ease',
                      }} />
                    </div>
                    <span style={{ fontSize: 13, fontWeight: 500, color: T.text.primary }}>Tunnel SSH</span>
                    <span style={{ fontSize: 12, color: T.text.tertiary }}>(si la DB no es accesible directamente)</span>
                  </label>

                  <AnimatePresence>
                    {useSsh && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: 'auto' }}
                        exit={{ opacity: 0, height: 0 }}
                        style={{ marginTop: T.space.md, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: T.space.md, overflow: 'hidden' }}
                      >
                        <div>
                          <label style={fieldLabel}>SSH Host</label>
                          <input {...register('ssh_host')} placeholder="bastion.empresa.com" className="d4c-input" />
                        </div>
                        <div>
                          <label style={fieldLabel}>SSH Usuario</label>
                          <input {...register('ssh_user')} placeholder="ubuntu" className="d4c-input" />
                        </div>
                        <div style={{ gridColumn: 'span 2' }}>
                          <label style={fieldLabel}>Ruta de clave privada</label>
                          <input {...register('ssh_key_path')} placeholder="/home/user/.ssh/id_rsa" className="d4c-input" />
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
            )}

            {/* File upload form */}
            {(connectionMode === 'file' || isFileMode) && (
              <motion.div
                key="file-form"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
              >
                <div style={{
                  minHeight: 200,
                  display: 'flex',
                  flexDirection: 'column',
                }}>
                  <FileUpload
                    clientName={clientName}
                    onUploadComplete={onUploadComplete}
                  />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Right: trust signals sidebar */}
        {(connectionMode || isFileMode) && (
          <div style={{ position: 'sticky', top: T.space.lg }}>
            <TrustSignals />
          </div>
        )}
      </div>
    </motion.div>
  )
}

// ── Step 2.5 (File mode): Preview + Column Mapping ───────────────────────────
function Step2_5Preview({
  uploadedFiles,
  onConfirm,
}: {
  uploadedFiles: UploadResult[]
  onConfirm: (mapping: Record<string, string>) => void
}) {
  const first = uploadedFiles[0]
  if (!first) return null

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, marginBottom: 6 }}>
        Verifica los datos
      </h2>
      <p style={{ fontSize: 13, color: T.text.secondary, marginBottom: T.space.lg }}>
        Revisa la vista previa y mapea las columnas a las entidades de negocio
      </p>

      <DataPreview
        uploadId={first.upload_id}
        sheets={first.sheets ?? []}
        onConfirm={onConfirm}
      />
    </motion.div>
  )
}

// ── Step 3: Period + Confirm ───────────────────────────────────────────────────
type PeriodTab = 'month' | 'quarter' | 'year'

function Step3Confirm({
  clientName, erpId, dbHost, dbName,
  period, onPeriod,
  isLoading, error, jobId,
  dataFrom, dataTo,
  // File mode props
  isFileMode, uploadedFiles, columnMapping,
}: {
  clientName: string
  erpId: string
  dbHost: string
  dbName: string
  period: string
  onPeriod: (v: string) => void
  isLoading: boolean
  error: string | null
  jobId: string | null
  dataFrom?: string
  dataTo?: string
  isFileMode?: boolean
  uploadedFiles?: UploadResult[]
  columnMapping?: Record<string, string>
}) {
  const [tab, setTab] = useState<PeriodTab>('month')
  const erp = ERP_OPTIONS.find(e => e.id === erpId)

  const monthOpts   = buildMonthOptions(dataFrom, dataTo)
  const quarterOpts = buildQuarterOptions(dataFrom, dataTo)
  const yearOpts    = buildYearOptions(dataFrom, dataTo)

  const opts = tab === 'month' ? monthOpts : tab === 'quarter' ? quarterOpts : yearOpts

  const whatToExpect = [
    { symbol: '◈', text: 'Mapeo automatico de entidades de negocio' },
    { symbol: '⊕', text: 'Deteccion de anomalias y riesgos financieros' },
    { symbol: '◆', text: 'Identificacion de oportunidades de mejora' },
    { symbol: '≡', text: 'Reporte ejecutivo listo para el CEO' },
  ]

  // Summary rows differ between file mode and DB mode
  const summaryRows = isFileMode && uploadedFiles && uploadedFiles.length > 0
    ? [
        { label: 'Cliente', value: clientName || '—' },
        { label: 'Sistema', value: 'XL Excel / CSV' },
        {
          label: uploadedFiles.length === 1 ? 'Archivo' : 'Archivos',
          value: uploadedFiles.length === 1
            ? uploadedFiles[0].filename
            : `${uploadedFiles.length} archivos`,
          mono: true,
        },
        {
          label: 'Columnas mapeadas',
          value: columnMapping ? `${Object.keys(columnMapping).length} columnas` : '—',
          mono: true,
        },
      ]
    : [
        { label: 'Cliente', value: clientName || '—' },
        { label: 'Sistema', value: `${erp?.abbr || ''} ${erp?.name || '—'}` },
        { label: 'Host', value: dbHost || '—', mono: true },
        { label: 'Base de datos', value: dbName || '—', mono: true },
      ]

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, marginBottom: 6 }}>
        Elegi el periodo a analizar
      </h2>
      <p style={{ fontSize: 13, color: T.text.secondary, marginBottom: T.space.md }}>
        {dataFrom && dataTo
          ? `Datos disponibles: ${dataFrom} → ${dataTo}`
          : 'Selecciona el rango de tiempo para el analisis'}
      </p>

      {/* Summary card */}
      <div style={{
        backgroundColor: T.bg.elevated,
        borderRadius: T.radius.sm,
        border: T.border.card,
        padding: T.space.md,
        marginBottom: T.space.lg,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 12,
      }}>
        {summaryRows.map(({ label, value, mono }) => (
          <div key={label}>
            <p style={{ fontSize: 10, color: T.text.tertiary, marginBottom: 2 }}>{label}</p>
            <p style={{
              fontSize: mono ? 11 : 13,
              fontWeight: 600,
              color: T.text.primary,
              fontFamily: mono ? T.font.mono : T.font.display,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              margin: 0,
            }}>
              {value}
            </p>
          </div>
        ))}
      </div>

      {/* Period tabs */}
      <div style={{ marginBottom: 8 }}>
        <div style={{
          display: 'flex',
          gap: 4,
          padding: 4,
          backgroundColor: T.bg.elevated,
          borderRadius: T.radius.sm,
          marginBottom: 12,
          width: 'fit-content',
        }}>
          {(['month', 'quarter', 'year'] as PeriodTab[]).map(t => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              style={{
                padding: '6px 12px',
                borderRadius: 6,
                fontSize: 12,
                fontWeight: 500,
                border: 'none',
                cursor: 'pointer',
                fontFamily: T.font.display,
                backgroundColor: tab === t ? T.bg.card : 'transparent',
                color: tab === t ? T.accent.teal : T.text.secondary,
                transition: 'all 150ms ease',
              }}
            >
              {t === 'month' ? 'Mes' : t === 'quarter' ? 'Trimestre' : 'Ano'}
            </button>
          ))}
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 6,
          maxHeight: 192,
          overflowY: 'auto',
          paddingRight: 4,
        }}>
          {opts.map(p => {
            const isSelected = period === p.value
            return (
              <button
                key={p.value}
                type="button"
                onClick={() => onPeriod(p.value)}
                style={{
                  fontSize: 11,
                  padding: '8px 6px',
                  borderRadius: T.radius.sm,
                  border: isSelected ? `1px solid ${T.accent.teal}` : T.border.card,
                  backgroundColor: isSelected ? T.accent.teal + '10' : T.bg.elevated,
                  color: isSelected ? T.accent.teal : T.text.secondary,
                  fontWeight: isSelected ? 600 : 400,
                  cursor: 'pointer',
                  textAlign: 'left',
                  lineHeight: 1.3,
                  fontFamily: T.font.display,
                  transition: 'all 150ms ease',
                }}
              >
                {p.label}
              </button>
            )
          })}
        </div>

        {period && (
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: T.accent.teal }}>
            <CheckCircle2 size={12} />
            Periodo seleccionado: <strong>{period}</strong>
          </div>
        )}
      </div>

      {/* What to expect */}
      <div style={{ marginTop: T.space.md, marginBottom: T.space.md }}>
        <p style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: T.text.tertiary, marginBottom: 8, fontFamily: T.font.mono }}>
          Que vas a recibir
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {whatToExpect.map((item, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12, color: T.text.secondary }}>
              <span style={{ flexShrink: 0, color: T.text.tertiary, fontFamily: T.font.mono }}>{item.symbol}</span>
              <span>{item.text}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: T.text.tertiary, marginBottom: 4 }}>
        <Clock size={12} style={{ flexShrink: 0 }} />
        <span>Tiempo estimado: 10-15 minutos segun el tamano de la base</span>
      </div>

      {jobId && (
        <div style={{
          marginTop: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          backgroundColor: T.accent.teal + '10',
          border: `1px solid ${T.accent.teal}30`,
          borderRadius: T.radius.sm,
          padding: `${T.space.sm} ${T.space.md}`,
        }}>
          <Lock size={12} style={{ color: T.accent.teal, flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: T.accent.teal, fontFamily: T.font.mono }}>
            Job ID: <strong>{jobId}</strong>
          </span>
        </div>
      )}

      {error && (
        <div style={{
          marginTop: 12,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 8,
          backgroundColor: T.accent.red + '10',
          border: `1px solid ${T.accent.red}30`,
          borderRadius: T.radius.sm,
          padding: `${T.space.sm} ${T.space.md}`,
        }}>
          <AlertTriangle size={14} style={{ color: T.accent.red, flexShrink: 0, marginTop: 1 }} />
          <p style={{ fontSize: 13, color: T.accent.red, margin: 0 }}>{error}</p>
        </div>
      )}
    </motion.div>
  )
}

// ── Main Wizard ───────────────────────────────────────────────────────────────
export function AnalysisForm({ onStartAnalysis }: AnalysisFormProps) {
  const [step, setStep] = useState(0)
  const [selectedErp, setSelectedErp] = useState('')
  const [clientName, setClientName] = useState('')
  const [period, setPeriod] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingJobId, setPendingJobId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testingConnection, setTestingConnection] = useState(false)

  // ── New state for redesign ───────────────────────────────────────────────
  const [industry, setIndustry] = useState('')
  const [goal, setGoal] = useState('')
  const [goalDetail, setGoalDetail] = useState('')
  const [connectionMode, setConnectionMode] = useState<ConnectionMode>(null)

  // ── File mode state ───────────────────────────────────────────────────────
  const [uploadedFiles, setUploadedFiles] = useState<UploadResult[]>([])
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({})

  const isFileMode = selectedErp === 'excel'

  // In file mode the wizard has 4 steps (0,1,2,3); DB mode has 3 steps (0,1,2)
  const totalSteps = isFileMode ? 4 : 3
  // Step index of the final "launch" step
  const confirmStep = isFileMode ? 3 : 2

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    formState: { errors },
  } = useForm<ConnectionFormData>({
    resolver: zodResolver(ConnectionSchema),
    defaultValues: { db_type: 'postgresql', db_port: 5432, use_ssh: false, period: '' },
  })

  const handleSelectERP = (id: string, db: string) => {
    setSelectedErp(id)
    setValue('erp_type', id)
    setValue('db_type', db)
    setValue('client_name', clientName)
    // Reset file state when switching ERP
    setUploadedFiles([])
    setColumnMapping({})
    // Auto-set connection mode for file mode ERP
    if (id === 'excel') {
      setConnectionMode('file')
    } else {
      setConnectionMode(null)
    }
  }

  const handleTestConnection = async () => {
    setTestingConnection(true)
    setTestResult(null)
    try {
      const v = getValues()
      const r = await fetch(`${API_URL}/api/onboarding/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          host: v.db_host,
          port: Number(v.db_port) || 5432,
          database: v.db_name,
          user: v.db_user,
          password: v.db_password,
          db_type: v.db_type || 'postgresql',
        }),
      })
      setTestResult(await r.json())
    } catch {
      setTestResult({ success: false, error: 'No se pudo conectar con la API' })
    } finally {
      setTestingConnection(false)
    }
  }

  const canProceed = () => {
    if (step === 0) return selectedErp !== '' && clientName.trim().length >= 2
    if (step === 1) {
      if (isFileMode || connectionMode === 'file') {
        return uploadedFiles.length > 0
      }
      if (connectionMode === 'db') {
        const v = getValues()
        return !!(v.db_host && v.db_name && v.db_user && v.db_password)
      }
      return false
    }
    // Step 2 in file mode = preview; proceed when onConfirm has been called (mapping set)
    if (step === 2 && isFileMode) return true
    return period !== ''
  }

  const handleFileUploadComplete = (uploads: UploadResult[]) => {
    setUploadedFiles(uploads)
  }

  const handlePreviewConfirm = (mapping: Record<string, string>) => {
    setColumnMapping(mapping)
    setStep(3)
  }

  const onSubmit = async (data: ConnectionFormData) => {
    if (step !== confirmStep) return
    setIsLoading(true)
    setError(null)
    try {
      if (isFileMode || connectionMode === 'file') {
        // File-based analysis path
        const result = await startFileAnalysis({
          client_name: clientName,
          upload_ids: uploadedFiles.map(u => u.upload_id),
          column_mapping: columnMapping,
          period,
        })
        setPendingJobId(result.job_id)
        onStartAnalysis(result.job_id)
      } else {
        // DB connection analysis path (unchanged)
        const payload: any = {
          client_name: clientName,
          period,
          erp: selectedErp || null,
          industry: industry || undefined,
          goal: goal || undefined,
          goal_detail: goalDetail || undefined,
          db_config: {
            host: data.db_host,
            port: data.db_port,
            name: data.db_name,
            user: data.db_user,
            password: data.db_password,
            type: data.db_type,
          },
        }
        if (data.use_ssh && data.ssh_host) {
          payload.ssh_config = {
            host: data.ssh_host,
            username: data.ssh_user,
            private_key_path: data.ssh_key_path,
          }
        }
        const res = await axios.post(`${API_URL}/api/analyze`, payload)
        setPendingJobId(res.data.job_id)
        onStartAnalysis(res.data.job_id)
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Error al iniciar el analisis')
    } finally {
      setIsLoading(false)
    }
  }

  const handleBack = () => {
    if (step > 0) setStep(s => s - 1)
  }

  const handleContinue = () => {
    // Sync form values before advancing
    setValue('industry', industry)
    setValue('goal', goal)
    setValue('goal_detail', goalDetail)
    if (canProceed()) setStep(s => s + 1)
  }

  // In file mode, step 2 (preview) advances via the DataPreview "Confirmar datos" button,
  // not the regular "Continuar" button, so we hide "Continuar" on that step.
  const isPreviewStep = isFileMode && step === 2
  const isLastStep = step === confirmStep

  return (
    <div style={{
      maxWidth: 720,
      margin: '0 auto',
      backgroundColor: T.bg.card,
      borderRadius: T.radius.lg,
      border: T.border.card,
      overflow: 'hidden',
    }}>
      <div style={{ padding: `${T.space.xl} ${T.space.xl} 0` }}>
        <StepIndicator current={step} />
      </div>

      <form onSubmit={handleSubmit(onSubmit)}>
        <div style={{ padding: `0 ${T.space.xl} ${T.space.lg}`, minHeight: 420 }}>
          <AnimatePresence mode="wait">
            {step === 0 && (
              <Step1Company
                key="step1"
                selected={selectedErp}
                onSelect={handleSelectERP}
                clientName={clientName}
                onClientName={v => { setClientName(v); setValue('client_name', v) }}
                industry={industry}
                onIndustry={v => { setIndustry(v); setValue('industry', v) }}
                goal={goal}
                onGoal={v => { setGoal(v); setValue('goal', v) }}
                goalDetail={goalDetail}
                onGoalDetail={v => { setGoalDetail(v); setValue('goal_detail', v) }}
              />
            )}
            {step === 1 && (
              <Step2Connect
                key="step2"
                register={register}
                errors={errors}
                watch={watch}
                testResult={testResult}
                testingConnection={testingConnection}
                onTestConnection={handleTestConnection}
                clientName={clientName}
                onUploadComplete={handleFileUploadComplete}
                connectionMode={isFileMode ? 'file' : connectionMode}
                onConnectionMode={setConnectionMode}
                isFileMode={isFileMode}
              />
            )}
            {step === 2 && isFileMode && (
              <Step2_5Preview
                key="step2-5"
                uploadedFiles={uploadedFiles}
                onConfirm={handlePreviewConfirm}
              />
            )}
            {step === confirmStep && (
              <Step3Confirm
                key="step3"
                clientName={clientName}
                erpId={selectedErp}
                dbHost={getValues('db_host') || ''}
                dbName={getValues('db_name') || ''}
                period={period}
                onPeriod={v => { setPeriod(v); setValue('period', v) }}
                isLoading={isLoading}
                error={error}
                jobId={pendingJobId}
                dataFrom={testResult?.data_from}
                dataTo={testResult?.data_to}
                isFileMode={isFileMode}
                uploadedFiles={uploadedFiles}
                columnMapping={columnMapping}
              />
            )}
          </AnimatePresence>
        </div>

        {/* Navigation */}
        <div style={{
          padding: `${T.space.lg} ${T.space.xl} ${T.space.xl}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderTop: T.border.card,
        }}>
          <button
            type="button"
            onClick={handleBack}
            className="d4c-btn-ghost"
            style={{ visibility: step === 0 ? 'hidden' : 'visible' }}
          >
            <ChevronLeft size={14} />Atras
          </button>

          {/* Preview step: DataPreview has its own "Confirmar datos" button */}
          {isPreviewStep && (
            <span style={{ fontSize: 12, color: T.text.tertiary }}>
              Confirma los datos en la tabla para continuar →
            </span>
          )}

          {!isPreviewStep && !isLastStep && (
            <button
              type="button"
              onClick={handleContinue}
              disabled={!canProceed()}
              className="d4c-btn-primary"
            >
              Continuar<ChevronRight size={14} />
            </button>
          )}

          {isLastStep && (
            <button
              type="submit"
              disabled={isLoading || !period}
              className="d4c-btn-primary"
            >
              {isLoading ? (
                <><Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />Iniciando analisis...</>
              ) : (
                <>Lanzar analisis<ArrowRight size={14} /></>
              )}
            </button>
          )}
        </div>
      </form>
    </div>
  )
}

export default AnalysisForm
