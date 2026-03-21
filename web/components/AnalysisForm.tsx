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
  ArrowRight, Loader2, Calendar
} from 'lucide-react'
import { T } from '@/components/d4c/tokens'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── ERP Options ──────────────────────────────────────────────────────────────
const ERP_OPTIONS = [
  {
    id: 'openbravo',
    name: 'Openbravo',
    description: 'ERP para distribución, manufactura y retail',
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
    id: 'mysql_generic',
    name: 'MySQL / MariaDB',
    description: 'Base de datos relacional genérica',
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
    comingSoon: true,
  },
]

// ── Zod schema ────────────────────────────────────────────────────────────────
const ConnectionSchema = z.object({
  client_name: z.string().min(2, 'Mínimo 2 caracteres'),
  erp_type: z.string().min(1, 'Seleccioná un sistema'),
  db_host: z.string().min(1, 'Host requerido'),
  db_port: z.coerce.number().int().min(1).max(65535).default(5432),
  db_name: z.string().min(1, 'Nombre de base de datos requerido'),
  db_user: z.string().min(1, 'Usuario requerido'),
  db_password: z.string().min(1, 'Contraseña requerida'),
  db_type: z.string().default('postgresql'),
  period: z.string().min(1, 'Período requerido'),
  use_ssh: z.boolean().default(false),
  ssh_host: z.string().optional(),
  ssh_user: z.string().optional(),
  ssh_key_path: z.string().optional(),
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
    options.push({ value: String(y), label: `Año completo ${y}` })
  }
  return options
}

// ── Step indicator ─────────────────────────────────────────────────────────────
function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: T.space.xl }}>
      {Array.from({ length: total }, (_, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 28,
            height: 28,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            fontWeight: 700,
            fontFamily: T.font.mono,
            backgroundColor: i < current ? T.accent.teal : i === current ? T.accent.teal + '20' : T.bg.elevated,
            color: i < current ? T.text.inverse : i === current ? T.accent.teal : T.text.tertiary,
            border: i === current ? `2px solid ${T.accent.teal}` : '2px solid transparent',
            transition: 'all 200ms ease',
          }}>
            {i < current ? <CheckCircle2 size={14} /> : i + 1}
          </div>
          {i < total - 1 && (
            <div style={{
              height: 1,
              width: 32,
              backgroundColor: i < current ? T.accent.teal : T.bg.hover,
              transition: 'background-color 200ms ease',
            }} />
          )}
        </div>
      ))}
      <span style={{ marginLeft: 8, fontSize: 11, color: T.text.tertiary, fontFamily: T.font.mono }}>
        Paso {current + 1} de {total}
      </span>
    </div>
  )
}

// ── Form field helpers ────────────────────────────────────────────────────────
const fieldLabel: React.CSSProperties = {
  display: 'block',
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

// ── Step 1: ERP Selection ─────────────────────────────────────────────────────
function Step1ERPSelection({
  selected, onSelect, clientName, onClientName,
}: {
  selected: string
  onSelect: (id: string, db: string) => void
  clientName: string
  onClientName: (v: string) => void
}) {
  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, marginBottom: 6 }}>
        ¿Qué sistema usás?
      </h2>
      <p style={{ fontSize: 13, color: T.text.secondary, marginBottom: T.space.lg }}>
        Valinor se adapta a cualquier ERP o base de datos
      </p>

      <div style={{ marginBottom: T.space.lg }}>
        <label style={fieldLabel}>Nombre del cliente / empresa</label>
        <input
          type="text"
          value={clientName}
          onChange={e => onClientName(e.target.value)}
          placeholder="Ej: Gloria Pet Distribution"
          className="d4c-input"
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
        {ERP_OPTIONS.map(erp => {
          const isSelected = selected === erp.id
          return (
            <button
              key={erp.id}
              type="button"
              onClick={() => !erp.comingSoon && onSelect(erp.id, erp.db)}
              disabled={!!erp.comingSoon}
              style={{
                position: 'relative',
                textAlign: 'left',
                padding: T.space.md,
                borderRadius: T.radius.sm,
                border: isSelected ? `2px solid ${T.accent.teal}` : `2px solid ${T.bg.hover}`,
                backgroundColor: isSelected ? T.accent.teal + '10' : T.bg.elevated,
                cursor: erp.comingSoon ? 'not-allowed' : 'pointer',
                opacity: erp.comingSoon ? 0.5 : 1,
                transition: 'border-color 150ms ease, background-color 150ms ease',
              }}
            >
              {erp.popular && !erp.comingSoon && (
                <span style={{
                  position: 'absolute', top: 8, right: 8,
                  fontSize: 9, fontWeight: 700, fontFamily: T.font.mono,
                  color: T.accent.teal, backgroundColor: T.accent.teal + '15',
                  padding: '2px 6px', borderRadius: 4,
                }}>
                  Popular
                </span>
              )}
              {erp.comingSoon && (
                <span style={{
                  position: 'absolute', top: 8, right: 8,
                  fontSize: 9, color: T.text.tertiary, fontFamily: T.font.mono,
                  padding: '2px 6px', borderRadius: 4, backgroundColor: T.bg.hover,
                }}>
                  Pronto
                </span>
              )}
              <div style={{
                fontFamily: T.font.mono,
                fontSize: 16,
                fontWeight: 700,
                color: isSelected ? T.accent.teal : T.text.tertiary,
                marginBottom: 6,
              }}>
                {erp.abbr}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: T.text.primary }}>{erp.name}</div>
              <div style={{ fontSize: 11, color: T.text.secondary, marginTop: 2, lineHeight: 1.4 }}>{erp.description}</div>
              {isSelected && (
                <div style={{ position: 'absolute', bottom: 8, right: 8 }}>
                  <CheckCircle2 size={14} style={{ color: T.accent.teal }} />
                </div>
              )}
            </button>
          )
        })}
      </div>

      {selected && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            marginTop: T.space.md,
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
            El Cartographer priorizará las tablas de mayor valor para este ERP.
          </p>
        </motion.div>
      )}
    </motion.div>
  )
}

// ── Step 2: Connection details ────────────────────────────────────────────────
function Step2Connection({
  register, errors, watch, testResult, testingConnection, onTestConnection,
}: {
  register: any
  errors: any
  watch: any
  testResult: TestResult | null
  testingConnection: boolean
  onTestConnection: () => void
}) {
  const useSsh = watch('use_ssh')

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, marginBottom: 6 }}>
        Conectá tu base de datos
      </h2>
      <p style={{ fontSize: 13, color: T.text.secondary, marginBottom: T.space.lg }}>
        Conexión de solo lectura · tus datos nunca se almacenan
      </p>

      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        marginBottom: T.space.lg,
        padding: `${T.space.sm} ${T.space.md}`,
        backgroundColor: T.accent.teal + '10',
        border: `1px solid ${T.accent.teal}30`,
        borderRadius: T.radius.sm,
      }}>
        <Shield size={14} style={{ color: T.accent.teal, flexShrink: 0 }} />
        <p style={{ fontSize: 12, color: T.accent.teal, margin: 0 }}>
          Zero Data Storage — Valinor solo lee, nunca escribe ni almacena datos de clientes
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: T.space.md }}>
        <div style={{ gridColumn: 'span 1' }}>
          <label style={fieldLabel}>Host</label>
          <input {...register('db_host')} placeholder="localhost" className="d4c-input" />
          {errors.db_host && <p style={fieldError}>{errors.db_host.message}</p>}
        </div>
        <div>
          <label style={fieldLabel}>Puerto</label>
          <input {...register('db_port')} type="number" placeholder="5432" className="d4c-input" />
        </div>
        <div style={{ gridColumn: 'span 2' }}>
          <label style={fieldLabel}>Base de datos</label>
          <input {...register('db_name')} placeholder="nombre_de_la_base" className="d4c-input" />
          {errors.db_name && <p style={fieldError}>{errors.db_name.message}</p>}
        </div>
        <div>
          <label style={fieldLabel}>Usuario</label>
          <input {...register('db_user')} placeholder="readonly_user" className="d4c-input" />
          {errors.db_user && <p style={fieldError}>{errors.db_user.message}</p>}
        </div>
        <div>
          <label style={fieldLabel}>Contraseña</label>
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
              <><Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />Probando conexión...</>
            ) : 'Probar conexión'}
          </button>

          {testResult && (
            <div style={{
              marginTop: 8,
              borderRadius: T.radius.sm,
              padding: T.space.sm,
              fontSize: 12,
              backgroundColor: testResult.success ? T.accent.teal + '10' : T.accent.red + '10',
              border: `1px solid ${testResult.success ? T.accent.teal : T.accent.red}30`,
              color: testResult.success ? T.accent.teal : T.accent.red,
            }}>
              {testResult.success ? (
                <div>
                  <p style={{ margin: 0, fontWeight: 600 }}>
                    ✓ Conectado ({testResult.latency_ms}ms) · {testResult.erp_detected} · {testResult.table_count} tablas
                  </p>
                  {testResult.data_from && testResult.data_to && (
                    <p style={{ margin: '4px 0 0', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <Calendar size={10} />
                      Datos disponibles: <strong>{testResult.data_from}</strong> → <strong>{testResult.data_to}</strong>
                    </p>
                  )}
                </div>
              ) : (
                <p style={{ margin: 0 }}>✕ Error: {testResult.error}</p>
              )}
            </div>
          )}
        </div>
      </div>

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
  )
}

// ── Step 3: Period + Confirm ───────────────────────────────────────────────────
type PeriodTab = 'month' | 'quarter' | 'year'

function Step3Confirm({
  clientName, erpId, dbHost, dbName,
  period, onPeriod,
  isLoading, error, jobId,
  dataFrom, dataTo,
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
}) {
  const [tab, setTab] = useState<PeriodTab>('month')
  const erp = ERP_OPTIONS.find(e => e.id === erpId)

  const monthOpts   = buildMonthOptions(dataFrom, dataTo)
  const quarterOpts = buildQuarterOptions(dataFrom, dataTo)
  const yearOpts    = buildYearOptions(dataFrom, dataTo)

  const opts = tab === 'month' ? monthOpts : tab === 'quarter' ? quarterOpts : yearOpts

  const whatToExpect = [
    { symbol: '◈', text: 'Mapeo automático de entidades de negocio' },
    { symbol: '⊕', text: 'Detección de anomalías y riesgos financieros' },
    { symbol: '◆', text: 'Identificación de oportunidades de mejora' },
    { symbol: '≡', text: 'Reporte ejecutivo listo para el CEO' },
  ]

  return (
    <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
      <h2 style={{ fontSize: 22, fontWeight: 700, color: T.text.primary, marginBottom: 6 }}>
        Elegí el período a analizar
      </h2>
      <p style={{ fontSize: 13, color: T.text.secondary, marginBottom: T.space.md }}>
        {dataFrom && dataTo
          ? `Datos disponibles: ${dataFrom} → ${dataTo}`
          : 'Seleccioná el rango de tiempo para el análisis'}
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
        {[
          { label: 'Cliente', value: clientName || '—' },
          { label: 'Sistema', value: `${erp?.abbr || ''} ${erp?.name || '—'}` },
          { label: 'Host', value: dbHost || '—', mono: true },
          { label: 'Base de datos', value: dbName || '—', mono: true },
        ].map(({ label, value, mono }) => (
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
              {t === 'month' ? 'Mes' : t === 'quarter' ? 'Trimestre' : 'Año'}
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
            Período seleccionado: <strong>{period}</strong>
          </div>
        )}
      </div>

      {/* What to expect */}
      <div style={{ marginTop: T.space.md, marginBottom: T.space.md }}>
        <p style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: T.text.tertiary, marginBottom: 8, fontFamily: T.font.mono }}>
          Qué vas a recibir
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
        <span>Tiempo estimado: 10-15 minutos según el tamaño de la base</span>
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
      const v = getValues()
      return !!(v.db_host && v.db_name && v.db_user && v.db_password)
    }
    return period !== ''
  }

  const onSubmit = async (data: ConnectionFormData) => {
    if (step !== 2) return
    setIsLoading(true)
    setError(null)
    try {
      const payload: any = {
        client_name: clientName,
        period,
        erp: selectedErp || null,
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
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Error al iniciar el análisis')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div style={{
      maxWidth: 640,
      margin: '0 auto',
      backgroundColor: T.bg.card,
      borderRadius: T.radius.lg,
      border: T.border.card,
      overflow: 'hidden',
    }}>
      <div style={{ padding: `${T.space.xl} ${T.space.xl} 0` }}>
        <StepIndicator current={step} total={3} />
      </div>

      <form onSubmit={handleSubmit(onSubmit)}>
        <div style={{ padding: `0 ${T.space.xl} ${T.space.lg}`, minHeight: 420 }}>
          <AnimatePresence mode="wait">
            {step === 0 && (
              <Step1ERPSelection
                key="step1"
                selected={selectedErp}
                onSelect={handleSelectERP}
                clientName={clientName}
                onClientName={v => { setClientName(v); setValue('client_name', v) }}
              />
            )}
            {step === 1 && (
              <Step2Connection
                key="step2"
                register={register}
                errors={errors}
                watch={watch}
                testResult={testResult}
                testingConnection={testingConnection}
                onTestConnection={handleTestConnection}
              />
            )}
            {step === 2 && (
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
            onClick={() => step > 0 && setStep(s => s - 1)}
            className="d4c-btn-ghost"
            style={{ visibility: step === 0 ? 'hidden' : 'visible' }}
          >
            <ChevronLeft size={14} />Atrás
          </button>

          {step < 2 ? (
            <button
              type="button"
              onClick={() => canProceed() && setStep(s => s + 1)}
              disabled={!canProceed()}
              className="d4c-btn-primary"
            >
              Continuar<ChevronRight size={14} />
            </button>
          ) : (
            <button
              type="submit"
              disabled={isLoading || !period}
              className="d4c-btn-primary"
            >
              {isLoading ? (
                <><Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />Iniciando análisis...</>
              ) : (
                <>Iniciar análisis<ArrowRight size={14} /></>
              )}
            </button>
          )}
        </div>
      </form>
    </div>
  )
}
