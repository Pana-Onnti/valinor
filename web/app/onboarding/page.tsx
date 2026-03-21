'use client'

import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  XCircle,
  Loader2,
  Server,
  Database,
  Wifi,
  Settings2,
  AlertTriangle,
  DollarSign,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { T } from '@/components/d4c/tokens'

// ─── Types ────────────────────────────────────────────────────────────────────

interface SSHForm {
  ssh_host: string
  ssh_port: string
  ssh_user: string
  /** Path to private key file on the server (never stored) */
  ssh_private_key_path: string
}

interface DBForm {
  db_type: string
  db_host: string
  db_port: string
  db_name: string
  db_user: string
  db_password: string
}

interface AnalysisForm {
  client_name: string
  period: string
}

interface TestResult {
  ssh_ok: boolean
  db_ok: boolean
  ssh_latency_ms?: number
  db_latency_ms?: number
  error: string | null
}

// ─── Constants ────────────────────────────────────────────────────────────────

const DB_TYPES = [
  { id: 'postgres', label: 'PostgreSQL', default_port: '5432' },
  { id: 'mysql', label: 'MySQL / MariaDB', default_port: '3306' },
  { id: 'sqlserver', label: 'SQL Server', default_port: '1433' },
  { id: 'oracle', label: 'Oracle Database', default_port: '1521' },
]

const PERIODS = [
  'Q1-2025',
  'Q2-2025',
  'Q3-2025',
  'Q4-2025',
  'H1-2025',
  'H2-2025',
  '2025',
]

const CLIENT_NAME_RE = /^[a-zA-Z0-9_]+$/

const STEPS = [
  { id: 1, label: 'Conexión SSH', icon: Server },
  { id: 2, label: 'Base de Datos', icon: Database },
  { id: 3, label: 'Test de Conexión', icon: Wifi },
  { id: 4, label: 'Configurar Análisis', icon: Settings2 },
]

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ─── Step progress bar ────────────────────────────────────────────────────────

function StepBar({ current }: { current: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0, marginBottom: T.space.xl }}>
      {STEPS.map((step, idx) => {
        const StepIcon = step.icon
        const isCompleted = current > step.id
        const isActive = current === step.id

        return (
          <div key={step.id} style={{ display: 'flex', alignItems: 'center' }}>
            {/* Circle */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <div
                style={{
                  width: '40px',
                  height: '40px',
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.3s',
                  border: isCompleted
                    ? `2px solid ${T.accent.teal}`
                    : isActive
                    ? `2px solid ${T.accent.teal}`
                    : `2px solid ${T.bg.elevated}`,
                  backgroundColor: isCompleted
                    ? T.accent.teal
                    : isActive
                    ? T.accent.teal
                    : T.bg.elevated,
                  color: isCompleted || isActive ? T.text.inverse : T.text.tertiary,
                }}
              >
                {isCompleted
                  ? <CheckCircle2 style={{ height: '20px', width: '20px' }} />
                  : <StepIcon style={{ height: '16px', width: '16px' }} />}
              </div>
              <span
                style={{
                  fontSize: '12px',
                  marginTop: '6px',
                  fontWeight: 500,
                  whiteSpace: 'nowrap',
                  color: isActive
                    ? T.accent.teal
                    : isCompleted
                    ? T.accent.teal
                    : T.text.tertiary,
                }}
              >
                {step.label}
              </span>
            </div>

            {/* Connector */}
            {idx < STEPS.length - 1 && (
              <div
                style={{
                  width: '64px',
                  height: '2px',
                  margin: '0 4px',
                  marginBottom: '20px',
                  transition: 'background-color 0.3s',
                  backgroundColor: current > step.id ? T.accent.teal : T.bg.elevated,
                }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Reusable form field ──────────────────────────────────────────────────────

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: '14px', fontWeight: 500, color: T.text.secondary, marginBottom: '4px' }}>
        {label}
      </label>
      {children}
      {hint && (
        <p style={{ marginTop: '4px', fontSize: '12px', color: T.text.tertiary }}>{hint}</p>
      )}
    </div>
  )
}

function Input({
  type = 'text',
  value,
  onChange,
  placeholder,
  className = '',
}: {
  type?: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`d4c-input${className ? ' ' + className : ''}`}
      style={{ width: '100%' }}
    />
  )
}

// ─── Step 1: SSH ──────────────────────────────────────────────────────────────

function StepSSH({
  form,
  onChange,
}: {
  form: SSHForm
  onChange: (patch: Partial<SSHForm>) => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
      <div>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: T.text.primary, marginBottom: '4px' }}>
          Conexión SSH
        </h2>
        <p style={{ fontSize: '14px', color: T.text.secondary }}>
          Valinor accede a tu base de datos a través de un túnel SSH efímero. Ningún dato es almacenado.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: T.space.md }}>
        <div>
          <Field label="SSH Host *" hint="IP o dominio del servidor SSH del cliente">
            <Input
              value={form.ssh_host}
              onChange={(v) => onChange({ ssh_host: v })}
              placeholder="203.0.113.10"
            />
          </Field>
        </div>
        <div>
          <Field label="Puerto">
            <Input
              value={form.ssh_port}
              onChange={(v) => onChange({ ssh_port: v })}
              placeholder="22"
            />
          </Field>
        </div>
      </div>

      <Field label="Usuario SSH *">
        <Input
          value={form.ssh_user}
          onChange={(v) => onChange({ ssh_user: v })}
          placeholder="ubuntu"
        />
      </Field>

      <Field
        label="Ruta de la clave privada *"
        hint="Ruta absoluta al archivo de clave privada en el servidor (ej. /home/ubuntu/.ssh/id_rsa). No se almacena."
      >
        <Input
          value={form.ssh_private_key_path}
          onChange={(v) => onChange({ ssh_private_key_path: v })}
          placeholder="/home/ubuntu/.ssh/id_rsa"
        />
      </Field>
    </div>
  )
}

// ─── Step 2: Database ─────────────────────────────────────────────────────────

function StepDatabase({
  form,
  onChange,
  estimatedCost,
  estimatingCost,
}: {
  form: DBForm
  onChange: (patch: Partial<DBForm>) => void
  estimatedCost: number | null
  estimatingCost: boolean
}) {
  const handleDbTypeChange = (id: string) => {
    const found = DB_TYPES.find((d) => d.id === id)
    onChange({ db_type: id, db_port: found?.default_port ?? '5432' })
  }

  const allFilled = !!(form.db_host && form.db_port && form.db_name && form.db_user && form.db_password)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
      <div>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: T.text.primary, marginBottom: '4px' }}>
          Base de Datos
        </h2>
        <p style={{ fontSize: '14px', color: T.text.secondary }}>
          Datos de conexión a la base de datos del cliente (accedida a través del túnel SSH).
        </p>
      </div>

      <Field label="Tipo de base de datos *">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: T.space.sm }}>
          {DB_TYPES.map((db) => (
            <button
              key={db.id}
              type="button"
              onClick={() => handleDbTypeChange(db.id)}
              style={{
                padding: `${T.space.sm} ${T.space.md}`,
                borderRadius: T.radius.sm,
                fontSize: '14px',
                fontWeight: 500,
                textAlign: 'left',
                transition: 'all 0.15s',
                cursor: 'pointer',
                border: form.db_type === db.id
                  ? `2px solid ${T.accent.teal}`
                  : `1px solid ${T.bg.elevated}`,
                backgroundColor: form.db_type === db.id
                  ? T.accent.teal + '10'
                  : T.bg.card,
                color: form.db_type === db.id
                  ? T.accent.teal
                  : T.text.secondary,
              }}
            >
              {db.label}
            </button>
          ))}
        </div>
      </Field>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: T.space.md }}>
        <div>
          <Field label="Host de la DB *" hint="Dirección del servidor de BD (desde el servidor SSH)">
            <Input
              value={form.db_host}
              onChange={(v) => onChange({ db_host: v })}
              placeholder="localhost"
            />
          </Field>
        </div>
        <div>
          <Field label="Puerto *">
            <Input
              value={form.db_port}
              onChange={(v) => onChange({ db_port: v })}
              placeholder="5432"
            />
          </Field>
        </div>
      </div>

      <Field label="Nombre de la base de datos *">
        <Input
          value={form.db_name}
          onChange={(v) => onChange({ db_name: v })}
          placeholder="production_db"
        />
      </Field>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: T.space.md }}>
        <Field label="Usuario *">
          <Input
            value={form.db_user}
            onChange={(v) => onChange({ db_user: v })}
            placeholder="readonly_user"
          />
        </Field>
        <Field label="Contraseña *">
          <Input
            type="password"
            value={form.db_password}
            onChange={(v) => onChange({ db_password: v })}
            placeholder="••••••••"
          />
        </Field>
      </div>

      {/* Estimated cost banner */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: T.space.md,
          padding: `${T.space.md} ${T.space.lg}`,
          borderRadius: T.radius.md,
          transition: 'all 0.15s',
          border: estimatedCost !== null && !estimatingCost
            ? `1px solid ${T.accent.teal}40`
            : `1px solid ${T.bg.elevated}`,
          backgroundColor: estimatedCost !== null && !estimatingCost
            ? T.accent.teal + '10'
            : T.bg.elevated,
        }}
      >
        {estimatingCost ? (
          <Loader2 style={{ height: '16px', width: '16px', color: T.accent.teal, flexShrink: 0 }} className="animate-spin" />
        ) : (
          <DollarSign style={{ height: '16px', width: '16px', color: T.accent.teal, flexShrink: 0 }} />
        )}
        <div>
          <p style={{ fontSize: '12px', fontWeight: 600, color: T.text.primary }}>Costo estimado</p>
          <p style={{ fontSize: '12px', color: T.text.secondary }}>
            {estimatingCost
              ? 'Calculando…'
              : estimatedCost !== null
              ? `~$${estimatedCost.toFixed(2)} USD por análisis`
              : allFilled
              ? 'Calculando estimado…'
              : 'Completa los campos para ver el estimado'}
          </p>
        </div>
      </div>
    </div>
  )
}

// ─── Step 3: Connection test ──────────────────────────────────────────────────

function StepTest({
  sshForm,
  dbForm,
  testResult,
  testing,
  testStale,
  onTest,
}: {
  sshForm: SSHForm
  dbForm: DBForm
  testResult: TestResult | null
  testing: boolean
  testStale: boolean
  onTest: () => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
      <div>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: T.text.primary, marginBottom: '4px' }}>
          Test de Conexión
        </h2>
        <p style={{ fontSize: '14px', color: T.text.secondary }}>
          Verificamos que SSH y la base de datos son accesibles antes de lanzar el análisis.
        </p>
      </div>

      {/* Stale warning */}
      <AnimatePresence>
        {testStale && testResult !== null && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: T.space.sm,
              padding: T.space.md,
              backgroundColor: T.accent.yellow + '15',
              border: `1px solid ${T.accent.yellow}40`,
              borderRadius: T.radius.sm,
            }}
          >
            <AlertTriangle style={{ height: '16px', width: '16px', color: T.accent.yellow, marginTop: '2px', flexShrink: 0 }} />
            <p style={{ fontSize: '14px', color: T.accent.yellow }}>
              Modificaste los datos de conexión después del último test. El resultado puede estar desactualizado — volvé a testear antes de continuar.
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Summary card */}
      <div
        style={{
          backgroundColor: T.bg.elevated,
          borderRadius: T.radius.md,
          padding: T.space.md,
          border: T.border.card,
          display: 'flex',
          flexDirection: 'column',
          gap: T.space.sm,
        }}
      >
        <p style={{ fontSize: '12px', fontFamily: T.font.mono, color: T.text.tertiary, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: T.space.sm }}>
          Configuración a probar
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: T.space.xl, rowGap: '4px', fontSize: '14px' }}>
          <span style={{ color: T.text.secondary }}>SSH host</span>
          <span style={{ fontFamily: T.font.mono, color: T.text.primary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {sshForm.ssh_host || '—'}:{sshForm.ssh_port}
          </span>
          <span style={{ color: T.text.secondary }}>SSH user</span>
          <span style={{ fontFamily: T.font.mono, color: T.text.primary }}>{sshForm.ssh_user || '—'}</span>
          <span style={{ color: T.text.secondary }}>DB type</span>
          <span style={{ fontFamily: T.font.mono, color: T.text.primary, textTransform: 'capitalize' }}>{dbForm.db_type}</span>
          <span style={{ color: T.text.secondary }}>DB host:port</span>
          <span style={{ fontFamily: T.font.mono, color: T.text.primary }}>
            {dbForm.db_host || '—'}:{dbForm.db_port}
          </span>
          <span style={{ color: T.text.secondary }}>Base de datos</span>
          <span style={{ fontFamily: T.font.mono, color: T.text.primary }}>{dbForm.db_name || '—'}</span>
        </div>
      </div>

      {/* Test button */}
      <button
        type="button"
        onClick={onTest}
        disabled={testing}
        className="d4c-btn-primary"
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: T.space.sm,
          padding: `${T.space.md} ${T.space.lg}`,
          opacity: testing ? 0.7 : 1,
          cursor: testing ? 'not-allowed' : 'pointer',
        }}
      >
        {testing ? (
          <>
            <Loader2 style={{ height: '16px', width: '16px' }} className="animate-spin" />
            Probando conexión…
          </>
        ) : (
          <>
            <Wifi style={{ height: '16px', width: '16px' }} />
            {testResult ? 'Volver a testear' : 'Probar conexión ahora'}
          </>
        )}
      </button>

      {/* Results */}
      <AnimatePresence>
        {testResult && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            style={{ display: 'flex', flexDirection: 'column', gap: T.space.md }}
          >
            <CheckRow
              label="SSH Tunnel"
              ok={testResult.ssh_ok}
              detail={
                testResult.ssh_ok
                  ? `Conectado a ${sshForm.ssh_host}${testResult.ssh_latency_ms !== undefined ? ` (${testResult.ssh_latency_ms} ms)` : ''}`
                  : 'No se pudo conectar via SSH'
              }
            />
            <CheckRow
              label="Base de Datos"
              ok={testResult.db_ok}
              detail={
                testResult.db_ok
                  ? `Alcanzable${testResult.db_latency_ms !== undefined ? ` (${testResult.db_latency_ms} ms)` : ''}`
                  : 'Base de datos inaccesible'
              }
            />

            {testResult.error && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: T.space.sm,
                  padding: T.space.md,
                  backgroundColor: T.accent.red + '15',
                  border: `1px solid ${T.accent.red}40`,
                  borderRadius: T.radius.sm,
                  color: T.accent.red,
                }}
              >
                <XCircle style={{ height: '16px', width: '16px', marginTop: '2px', flexShrink: 0 }} />
                <p style={{ fontSize: '14px', fontFamily: T.font.mono, wordBreak: 'break-all' }}>
                  {testResult.error}
                </p>
              </div>
            )}

            {testResult.ssh_ok && testResult.db_ok && !testStale && (
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: T.space.sm,
                  padding: T.space.md,
                  backgroundColor: T.accent.teal + '15',
                  border: `1px solid ${T.accent.teal}40`,
                  borderRadius: T.radius.sm,
                  color: T.accent.teal,
                }}
              >
                <CheckCircle2 style={{ height: '16px', width: '16px', flexShrink: 0 }} />
                <p style={{ fontSize: '14px', fontWeight: 600 }}>
                  Todo listo — puedes continuar con el análisis.
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function CheckRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: T.space.md,
        padding: T.space.md,
        borderRadius: T.radius.sm,
        border: ok
          ? `1px solid ${T.accent.teal}40`
          : `1px solid ${T.accent.red}40`,
        backgroundColor: ok
          ? T.accent.teal + '10'
          : T.accent.red + '10',
      }}
    >
      {ok ? (
        <CheckCircle2 style={{ height: '20px', width: '20px', color: T.accent.teal, flexShrink: 0 }} />
      ) : (
        <XCircle style={{ height: '20px', width: '20px', color: T.accent.red, flexShrink: 0 }} />
      )}
      <div>
        <p style={{ fontWeight: 600, fontSize: '14px', color: ok ? T.accent.teal : T.accent.red }}>
          {label}
        </p>
        <p style={{ fontSize: '12px', color: ok ? T.accent.teal : T.accent.red, opacity: 0.8 }}>
          {detail}
        </p>
      </div>
    </div>
  )
}

// ─── Step 4: Configure analysis ───────────────────────────────────────────────

function StepConfigure({
  form,
  onChange,
  onSubmit,
  submitting,
  submitError,
}: {
  form: AnalysisForm
  onChange: (patch: Partial<AnalysisForm>) => void
  onSubmit: () => void
  submitting: boolean
  submitError: string | null
}) {
  const nameInvalid = form.client_name.length > 0 && !CLIENT_NAME_RE.test(form.client_name)
  const canSubmit = !!(form.client_name && form.period && !nameInvalid && !submitting)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.lg }}>
      <div>
        <h2 style={{ fontSize: '20px', fontWeight: 700, color: T.text.primary, marginBottom: '4px' }}>
          Configurar Análisis
        </h2>
        <p style={{ fontSize: '14px', color: T.text.secondary }}>
          Define el período y el nombre del cliente para el reporte ejecutivo.
        </p>
      </div>

      <Field
        label="Nombre del cliente *"
        hint={nameInvalid ? undefined : 'Solo letras, números y guiones bajos (_). Se usa como identificador en la URL.'}
      >
        <input
          value={form.client_name}
          onChange={(e) => onChange({ client_name: e.target.value })}
          placeholder="acme_corp"
          className="d4c-input"
          style={{
            width: '100%',
            ...(nameInvalid ? { borderColor: T.accent.red } : {}),
          }}
        />
        {nameInvalid && (
          <p style={{ marginTop: '4px', fontSize: '12px', color: T.accent.red }}>
            Solo se permiten letras, números y guiones bajos (_).
          </p>
        )}
      </Field>

      <Field label="Período a analizar *">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: T.space.sm }}>
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onChange({ period: p })}
              style={{
                padding: `${T.space.sm} ${T.space.md}`,
                borderRadius: T.radius.sm,
                fontSize: '14px',
                fontWeight: 500,
                transition: 'all 0.15s',
                cursor: 'pointer',
                border: form.period === p
                  ? `2px solid ${T.accent.teal}`
                  : `1px solid ${T.bg.elevated}`,
                backgroundColor: form.period === p
                  ? T.accent.teal + '10'
                  : T.bg.card,
                color: form.period === p
                  ? T.accent.teal
                  : T.text.secondary,
              }}
            >
              {p}
            </button>
          ))}
        </div>
      </Field>

      <button
        type="button"
        onClick={onSubmit}
        disabled={!canSubmit}
        className={canSubmit ? 'd4c-btn-primary' : 'd4c-btn-ghost'}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: T.space.sm,
          padding: `14px ${T.space.lg}`,
          opacity: !canSubmit ? 0.5 : 1,
          cursor: !canSubmit ? 'not-allowed' : 'pointer',
        }}
      >
        {submitting ? (
          <>
            <Loader2 style={{ height: '16px', width: '16px' }} className="animate-spin" />
            Iniciando análisis…
          </>
        ) : (
          <>
            Lanzar análisis
            <ArrowRight style={{ height: '16px', width: '16px' }} />
          </>
        )}
      </button>

      {/* Submit error */}
      <AnimatePresence>
        {submitError && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: T.space.sm,
              padding: T.space.md,
              backgroundColor: T.accent.red + '15',
              border: `1px solid ${T.accent.red}40`,
              borderRadius: T.radius.sm,
              color: T.accent.red,
            }}
          >
            <XCircle style={{ height: '16px', width: '16px', marginTop: '2px', flexShrink: 0 }} />
            <p style={{ fontSize: '14px' }}>{submitError}</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const router = useRouter()

  // Steps are 1-indexed to match STEPS array ids
  const [step, setStep] = useState(1)

  const [sshForm, setSSHForm] = useState<SSHForm>({
    ssh_host: '',
    ssh_port: '22',
    ssh_user: '',
    ssh_private_key_path: '',
  })

  const [dbForm, setDBForm] = useState<DBForm>({
    db_type: 'postgres',
    db_host: 'localhost',
    db_port: '5432',
    db_name: '',
    db_user: '',
    db_password: '',
  })

  const [analysisForm, setAnalysisForm] = useState<AnalysisForm>({
    client_name: '',
    period: 'Q1-2025',
  })

  // Connection test state
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testing, setTesting] = useState(false)
  // testStale: true when SSH/DB fields changed after a successful test
  const [testStale, setTestStale] = useState(false)

  // Cost estimate state
  const [estimatedCost, setEstimatedCost] = useState<number | null>(null)
  const [estimatingCost, setEstimatingCost] = useState(false)

  // Submit state
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [errorBanner, setErrorBanner] = useState<string | null>(null)

  // ── Mark test stale when SSH or DB fields change after a successful test ──
  // Use a ref to track previous test result presence so we only mark stale
  // if the user had already run a test.
  const prevTestResultRef = useRef<TestResult | null>(null)
  useEffect(() => {
    prevTestResultRef.current = testResult
  })

  useEffect(() => {
    if (prevTestResultRef.current !== null) {
      setTestStale(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    sshForm.ssh_host,
    sshForm.ssh_port,
    sshForm.ssh_user,
    sshForm.ssh_private_key_path,
    dbForm.db_type,
    dbForm.db_host,
    dbForm.db_port,
    dbForm.db_name,
    dbForm.db_user,
    dbForm.db_password,
  ])

  // ── Fetch cost estimate whenever DB step is active and fields are filled ──
  const isDbFilled = !!(
    dbForm.db_host &&
    dbForm.db_port &&
    dbForm.db_name &&
    dbForm.db_user &&
    dbForm.db_password
  )

  useEffect(() => {
    if (step !== 2 || !isDbFilled) return

    let cancelled = false
    setEstimatingCost(true)

    fetch(`${API_URL}/api/onboarding/estimate-cost`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        db_type: dbForm.db_type,
        db_host: dbForm.db_host,
        db_port: parseInt(dbForm.db_port, 10) || 5432,
        db_name: dbForm.db_name,
      }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (!cancelled && data) {
          setEstimatedCost(data.estimated_cost_usd ?? null)
        }
      })
      .catch(() => { /* informational; ignore errors */ })
      .finally(() => {
        if (!cancelled) setEstimatingCost(false)
      })

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, isDbFilled, dbForm.db_type, dbForm.db_host, dbForm.db_port, dbForm.db_name])

  // ── Validation ────────────────────────────────────────────────────────────
  const canAdvance = (): boolean => {
    if (step === 1) {
      return !!(sshForm.ssh_host && sshForm.ssh_user && sshForm.ssh_private_key_path)
    }
    if (step === 2) {
      return !!(dbForm.db_host && dbForm.db_port && dbForm.db_name && dbForm.db_user && dbForm.db_password)
    }
    if (step === 3) {
      return !!(testResult?.ssh_ok && testResult?.db_ok && !testStale)
    }
    return false
  }

  const handleNext = () => {
    if (canAdvance() && step < 4) setStep(step + 1)
  }

  const handleBack = () => {
    if (step > 1) setStep(step - 1)
  }

  // ── Connection test ───────────────────────────────────────────────────────
  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    setTestStale(false)
    setErrorBanner(null)

    try {
      const resp = await fetch(`${API_URL}/api/onboarding/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ssh_host: sshForm.ssh_host,
          ssh_port: parseInt(sshForm.ssh_port, 10) || 22,
          ssh_user: sshForm.ssh_user,
          ssh_private_key_path: sshForm.ssh_private_key_path,
          db_host: dbForm.db_host,
          db_port: parseInt(dbForm.db_port, 10) || 5432,
          db_type: dbForm.db_type,
          db_name: dbForm.db_name,
          db_user: dbForm.db_user,
          db_password: dbForm.db_password,
        }),
      })

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }

      const data = await resp.json()
      // Normalize both flat and nested response shapes
      const result: TestResult = {
        ssh_ok: data.ssh?.ok ?? data.ssh_ok ?? false,
        db_ok: data.db?.ok ?? data.db_ok ?? false,
        ssh_latency_ms: data.ssh?.latency_ms ?? data.ssh_latency_ms,
        db_latency_ms: data.db?.latency_ms ?? data.db_latency_ms,
        error: data.error ?? data.ssh?.error ?? data.db?.error ?? null,
      }
      setTestResult(result)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err)
      setErrorBanner(`Error al probar la conexión: ${message}`)
      setTestResult({ ssh_ok: false, db_ok: false, error: message })
    } finally {
      setTesting(false)
    }
  }

  // ── Submit ────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    setSubmitting(true)
    setSubmitError(null)

    try {
      const resp = await fetch(`${API_URL}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          client_name: analysisForm.client_name,
          period: analysisForm.period,
          db_type: dbForm.db_type,
          host: dbForm.db_host,
          port: parseInt(dbForm.db_port, 10),
          database: dbForm.db_name,
          user: dbForm.db_user,
          password: dbForm.db_password,
          ssh_host: sshForm.ssh_host,
          ssh_port: parseInt(sshForm.ssh_port, 10) || 22,
          ssh_user: sshForm.ssh_user,
          ssh_private_key_path: sshForm.ssh_private_key_path,
        }),
      })

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${resp.status}`)
      }

      router.push(`/clients/${analysisForm.client_name}`)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err)
      setSubmitError(`Error al iniciar el análisis: ${message}`)
      setSubmitting(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary, fontFamily: T.font.display }}>
      {/* Header */}
      <header
        style={{
          borderBottom: T.border.subtle,
          backgroundColor: T.bg.card + 'CC',
          backdropFilter: 'blur(8px)',
          position: 'sticky',
          top: 0,
          zIndex: 50,
        }}
      >
        <div style={{ maxWidth: '768px', margin: '0 auto', padding: `0 ${T.space.lg}` }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: `${T.space.md} 0` }}>
            <Link
              href="/dashboard"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: T.space.sm,
                fontSize: '14px',
                color: T.text.secondary,
                textDecoration: 'none',
                transition: 'color 0.15s',
              }}
            >
              <ArrowLeft style={{ height: '16px', width: '16px' }} />
              <span>Dashboard</span>
            </Link>
            <span style={{ fontSize: '14px', fontWeight: 600, color: T.text.primary }}>
              Onboarding — Valinor SaaS
            </span>
            <span style={{ fontSize: '12px', color: T.text.tertiary, fontFamily: T.font.mono }}>
              Paso {step} / {STEPS.length}
            </span>
          </div>
        </div>
      </header>

      <main style={{ maxWidth: '768px', margin: '0 auto', padding: `${T.space.xxl} ${T.space.lg}` }}>
        {/* Step progress bar */}
        <StepBar current={step} />

        {/* General error banner */}
        <AnimatePresence>
          {errorBanner && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              style={{
                marginBottom: T.space.lg,
                display: 'flex',
                alignItems: 'flex-start',
                gap: T.space.sm,
                padding: T.space.md,
                backgroundColor: T.accent.red + '15',
                border: `1px solid ${T.accent.red}40`,
                borderRadius: T.radius.md,
                color: T.accent.red,
              }}
            >
              <XCircle style={{ height: '16px', width: '16px', marginTop: '2px', flexShrink: 0 }} />
              <p style={{ fontSize: '14px' }}>{errorBanner}</p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step card */}
        <div
          style={{
            backgroundColor: T.bg.card,
            borderRadius: T.radius.lg,
            border: T.border.card,
            padding: T.space.xxl,
          }}
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
            >
              {step === 1 && (
                <StepSSH form={sshForm} onChange={(p) => setSSHForm((f) => ({ ...f, ...p }))} />
              )}
              {step === 2 && (
                <StepDatabase
                  form={dbForm}
                  onChange={(p) => {
                    setDBForm((f) => ({ ...f, ...p }))
                    setEstimatedCost(null)
                  }}
                  estimatedCost={estimatedCost}
                  estimatingCost={estimatingCost}
                />
              )}
              {step === 3 && (
                <StepTest
                  sshForm={sshForm}
                  dbForm={dbForm}
                  testResult={testResult}
                  testing={testing}
                  testStale={testStale}
                  onTest={handleTest}
                />
              )}
              {step === 4 && (
                <StepConfigure
                  form={analysisForm}
                  onChange={(p) => setAnalysisForm((f) => ({ ...f, ...p }))}
                  onSubmit={handleSubmit}
                  submitting={submitting}
                  submitError={submitError}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Navigation */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: T.space.lg }}>
          <button
            type="button"
            onClick={handleBack}
            disabled={step === 1}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: T.space.sm,
              padding: `${T.space.sm} ${T.space.md}`,
              borderRadius: T.radius.sm,
              fontSize: '14px',
              fontWeight: 500,
              transition: 'all 0.15s',
              background: 'none',
              border: 'none',
              cursor: step === 1 ? 'not-allowed' : 'pointer',
              color: step === 1 ? T.text.tertiary : T.text.secondary,
            }}
          >
            <ArrowLeft style={{ height: '16px', width: '16px' }} />
            Anterior
          </button>

          {step < 4 && (
            <button
              type="button"
              onClick={handleNext}
              disabled={!canAdvance()}
              className={canAdvance() ? 'd4c-btn-primary' : 'd4c-btn-ghost'}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: T.space.sm,
                padding: `${T.space.sm} ${T.space.lg}`,
                opacity: !canAdvance() ? 0.5 : 1,
                cursor: !canAdvance() ? 'not-allowed' : 'pointer',
              }}
            >
              Siguiente
              <ArrowRight style={{ height: '16px', width: '16px' }} />
            </button>
          )}

          {step === 4 && (
            <span style={{ fontSize: '12px', color: T.text.tertiary, fontStyle: 'italic' }}>
              Presiona &quot;Lanzar análisis&quot; para continuar
            </span>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer
        style={{
          marginTop: 'auto',
          borderTop: T.border.subtle,
          backgroundColor: T.bg.card,
        }}
      >
        <div style={{ maxWidth: '768px', margin: '0 auto', padding: `${T.space.lg} ${T.space.lg}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '14px', color: T.text.tertiary }}>
            <p>© 2026 Delta 4C — Valinor SaaS v2.0</p>
            <Link
              href="/docs"
              style={{ color: T.text.tertiary, textDecoration: 'none', transition: 'color 0.15s' }}
            >
              API docs
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
