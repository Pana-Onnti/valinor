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
    <div className="flex items-center justify-center gap-0 mb-10">
      {STEPS.map((step, idx) => {
        const StepIcon = step.icon
        const isCompleted = current > step.id
        const isActive = current === step.id

        return (
          <div key={step.id} className="flex items-center">
            {/* Circle */}
            <div
              className={[
                'flex flex-col items-center',
              ].join(' ')}
            >
              <div
                className={[
                  'w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 border-2',
                  isCompleted
                    ? 'bg-emerald-500 border-emerald-500 text-white'
                    : isActive
                    ? 'bg-indigo-600 border-indigo-600 text-white shadow-lg shadow-indigo-500/25'
                    : 'bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-400',
                ].join(' ')}
              >
                {isCompleted
                  ? <CheckCircle2 className="h-5 w-5" />
                  : <StepIcon className="h-4 w-4" />}
              </div>
              <span
                className={[
                  'text-xs mt-1.5 font-medium whitespace-nowrap',
                  isActive
                    ? 'text-indigo-600 dark:text-indigo-400'
                    : isCompleted
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-gray-400',
                ].join(' ')}
              >
                {step.label}
              </span>
            </div>

            {/* Connector */}
            {idx < STEPS.length - 1 && (
              <div
                className={[
                  'w-16 h-0.5 mx-1 mb-5 transition-colors duration-300',
                  current > step.id
                    ? 'bg-emerald-500'
                    : 'bg-gray-200 dark:bg-gray-700',
                ].join(' ')}
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
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
        {label}
      </label>
      {children}
      {hint && (
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{hint}</p>
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
      className={[
        'w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600',
        'bg-white dark:bg-gray-800 text-gray-900 dark:text-white',
        'placeholder:text-gray-400 dark:placeholder:text-gray-500',
        'focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent',
        'text-sm transition-colors',
        className,
      ].join(' ')}
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
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">
          Conexión SSH
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Valinor accede a tu base de datos a través de un túnel SSH efímero. Ningún dato es almacenado.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
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
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">
          Base de Datos
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Datos de conexión a la base de datos del cliente (accedida a través del túnel SSH).
        </p>
      </div>

      <Field label="Tipo de base de datos *">
        <div className="grid grid-cols-2 gap-2">
          {DB_TYPES.map((db) => (
            <button
              key={db.id}
              type="button"
              onClick={() => handleDbTypeChange(db.id)}
              className={[
                'px-3 py-2 rounded-lg border text-sm font-medium text-left transition-all',
                form.db_type === db.id
                  ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                  : 'border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:border-indigo-300',
              ].join(' ')}
            >
              {db.label}
            </button>
          ))}
        </div>
      </Field>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
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

      <div className="grid grid-cols-2 gap-4">
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
        className={[
          'flex items-center gap-3 px-4 py-3 rounded-xl border transition-all',
          estimatingCost
            ? 'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50'
            : estimatedCost !== null
            ? 'border-violet-200 dark:border-violet-800 bg-violet-50 dark:bg-violet-900/20'
            : 'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50',
        ].join(' ')}
      >
        {estimatingCost ? (
          <Loader2 className="h-4 w-4 text-violet-500 animate-spin flex-shrink-0" />
        ) : (
          <DollarSign className="h-4 w-4 text-violet-500 flex-shrink-0" />
        )}
        <div>
          <p className="text-xs font-semibold text-gray-700 dark:text-gray-300">Costo estimado</p>
          <p className="text-xs text-gray-500 dark:text-gray-400">
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
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">
          Test de Conexión
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
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
            className="flex items-start gap-2 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg"
          >
            <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
            <p className="text-sm text-amber-700 dark:text-amber-300">
              Modificaste los datos de conexión después del último test. El resultado puede estar desactualizado — volvé a testear antes de continuar.
            </p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Summary card */}
      <div className="bg-gray-50 dark:bg-gray-800 rounded-xl p-4 border border-gray-200 dark:border-gray-700 space-y-2">
        <p className="text-xs font-mono text-gray-500 uppercase tracking-wide mb-2">Configuración a probar</p>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <span className="text-gray-500 dark:text-gray-400">SSH host</span>
          <span className="font-mono text-gray-900 dark:text-white truncate">
            {sshForm.ssh_host || '—'}:{sshForm.ssh_port}
          </span>
          <span className="text-gray-500 dark:text-gray-400">SSH user</span>
          <span className="font-mono text-gray-900 dark:text-white">{sshForm.ssh_user || '—'}</span>
          <span className="text-gray-500 dark:text-gray-400">DB type</span>
          <span className="font-mono text-gray-900 dark:text-white capitalize">{dbForm.db_type}</span>
          <span className="text-gray-500 dark:text-gray-400">DB host:port</span>
          <span className="font-mono text-gray-900 dark:text-white">
            {dbForm.db_host || '—'}:{dbForm.db_port}
          </span>
          <span className="text-gray-500 dark:text-gray-400">Base de datos</span>
          <span className="font-mono text-gray-900 dark:text-white">{dbForm.db_name || '—'}</span>
        </div>
      </div>

      {/* Test button */}
      <button
        type="button"
        onClick={onTest}
        disabled={testing}
        className={[
          'w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl',
          'font-semibold text-sm transition-all',
          testing
            ? 'bg-indigo-400 cursor-not-allowed text-white'
            : 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-md shadow-indigo-500/20',
        ].join(' ')}
      >
        {testing ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Probando conexión…
          </>
        ) : (
          <>
            <Wifi className="h-4 w-4" />
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
            className="space-y-3"
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
              <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
                <XCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
                <p className="text-sm text-red-700 dark:text-red-300 font-mono break-all">
                  {testResult.error}
                </p>
              </div>
            )}

            {testResult.ssh_ok && testResult.db_ok && !testStale && (
              <div className="flex items-center gap-2 p-3 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-lg">
                <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
                <p className="text-sm text-emerald-700 dark:text-emerald-300 font-semibold">
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
      className={[
        'flex items-center gap-3 p-3 rounded-lg border',
        ok
          ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800'
          : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800',
      ].join(' ')}
    >
      {ok ? (
        <CheckCircle2 className="h-5 w-5 text-emerald-500 shrink-0" />
      ) : (
        <XCircle className="h-5 w-5 text-red-500 shrink-0" />
      )}
      <div>
        <p className={`font-semibold text-sm ${ok ? 'text-emerald-800 dark:text-emerald-200' : 'text-red-800 dark:text-red-200'}`}>
          {label}
        </p>
        <p className={`text-xs ${ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
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
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-1">
          Configurar Análisis
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Define el período y el nombre del cliente para el reporte ejecutivo.
        </p>
      </div>

      <Field
        label="Nombre del cliente *"
        hint={nameInvalid ? undefined : 'Solo letras, números y guiones bajos (_). Se usa como identificador en la URL.'}
      >
        <Input
          value={form.client_name}
          onChange={(v) => onChange({ client_name: v })}
          placeholder="acme_corp"
          className={nameInvalid ? 'border-red-400 focus:ring-red-400' : ''}
        />
        {nameInvalid && (
          <p className="mt-1 text-xs text-red-500">
            Solo se permiten letras, números y guiones bajos (_).
          </p>
        )}
      </Field>

      <Field label="Período a analizar *">
        <div className="grid grid-cols-3 gap-2">
          {PERIODS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onChange({ period: p })}
              className={[
                'px-3 py-2 rounded-lg border text-sm font-medium transition-all',
                form.period === p
                  ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                  : 'border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:border-indigo-300',
              ].join(' ')}
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
        className={[
          'w-full flex items-center justify-center gap-2 px-4 py-3.5 rounded-xl',
          'font-semibold text-sm transition-all',
          !canSubmit
            ? 'bg-gray-300 dark:bg-gray-700 cursor-not-allowed text-gray-500 dark:text-gray-400'
            : 'bg-violet-600 hover:bg-violet-700 text-white shadow-md shadow-violet-500/20',
        ].join(' ')}
      >
        {submitting ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Iniciando análisis…
          </>
        ) : (
          <>
            Lanzar análisis
            <ArrowRight className="h-4 w-4" />
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
            className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg"
          >
            <XCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
            <p className="text-sm text-red-700 dark:text-red-300">{submitError}</p>
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
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-blue-50 dark:from-gray-900 dark:via-gray-800 dark:to-indigo-900">
      {/* Header */}
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between py-4">
            <Link
              href="/dashboard"
              className="flex items-center gap-2 text-sm text-gray-500 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-400 transition-colors"
            >
              <ArrowLeft className="h-4 w-4" />
              <span className="hidden sm:inline">Dashboard</span>
            </Link>
            <span className="text-sm font-semibold text-gray-900 dark:text-white">
              Onboarding — Valinor SaaS
            </span>
            <span className="text-xs text-gray-400 font-mono">
              Paso {step} / {STEPS.length}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {/* Step progress bar */}
        <StepBar current={step} />

        {/* General error banner */}
        <AnimatePresence>
          {errorBanner && (
            <motion.div
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mb-6 flex items-start gap-2 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl"
            >
              <XCircle className="h-4 w-4 text-red-500 mt-0.5 shrink-0" />
              <p className="text-sm text-red-700 dark:text-red-300">{errorBanner}</p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step card */}
        <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-sm p-8">
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
        <div className="flex items-center justify-between mt-6">
          <button
            type="button"
            onClick={handleBack}
            disabled={step === 1}
            className={[
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              step === 1
                ? 'text-gray-300 dark:text-gray-600 cursor-not-allowed'
                : 'text-gray-600 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-700',
            ].join(' ')}
          >
            <ArrowLeft className="h-4 w-4" />
            Anterior
          </button>

          {step < 4 && (
            <button
              type="button"
              onClick={handleNext}
              disabled={!canAdvance()}
              className={[
                'flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold transition-all',
                canAdvance()
                  ? 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm shadow-indigo-500/20'
                  : 'bg-gray-200 dark:bg-gray-700 text-gray-400 cursor-not-allowed',
              ].join(' ')}
            >
              Siguiente
              <ArrowRight className="h-4 w-4" />
            </button>
          )}

          {step === 4 && (
            <span className="text-xs text-gray-400 italic">
              Presiona "Lanzar análisis" para continuar
            </span>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="mt-auto border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex justify-between items-center text-sm text-gray-500 dark:text-gray-400">
            <p>© 2026 Delta 4C — Valinor SaaS v2.0</p>
            <Link
              href="/docs"
              className="hover:text-violet-600 dark:hover:text-violet-400 transition-colors"
            >
              API docs
            </Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
