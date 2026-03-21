'use client'

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import axios from 'axios'
import {
  Database, Server, ChevronRight, ChevronLeft, Zap,
  CheckCircle2, Shield, Clock, AlertTriangle, Lock,
  ArrowRight, Loader2, Calendar
} from 'lucide-react'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── ERP Options ──────────────────────────────────────────────────────────────
const ERP_OPTIONS = [
  {
    id: 'openbravo',
    name: 'Openbravo',
    description: 'ERP para distribución, manufactura y retail',
    icon: '📦',
    db: 'postgresql',
    popular: true,
    hints: ['c_invoice', 'c_bpartner', 'm_product'],
  },
  {
    id: 'odoo',
    name: 'Odoo',
    description: 'ERP open source todo-en-uno',
    icon: '🔧',
    db: 'postgresql',
    hints: ['account_move', 'res_partner', 'product_template'],
  },
  {
    id: 'sap',
    name: 'SAP',
    description: 'SAP ECC / S/4HANA',
    icon: '🏢',
    db: 'sqlserver',
    hints: ['BKPF', 'VBAK', 'KNA1'],
  },
  {
    id: 'mysql_generic',
    name: 'MySQL / MariaDB',
    description: 'Base de datos relacional genérica',
    icon: '🐬',
    db: 'mysql',
    hints: [],
  },
  {
    id: 'postgres_generic',
    name: 'PostgreSQL',
    description: 'Base de datos relacional avanzada',
    icon: '🐘',
    db: 'postgresql',
    hints: [],
  },
  {
    id: 'excel',
    name: 'Excel / CSV',
    description: 'Archivos exportados desde cualquier sistema',
    icon: '📊',
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
  data_from?: string   // "YYYY-MM"
  data_to?: string     // "YYYY-MM"
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
    <div className="flex items-center gap-2 mb-8">
      {Array.from({ length: total }, (_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
            i < current
              ? 'bg-violet-600 text-white'
              : i === current
                ? 'bg-violet-100 dark:bg-violet-900/50 text-violet-700 dark:text-violet-300 ring-2 ring-violet-500'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400'
          }`}>
            {i < current ? <CheckCircle2 className="h-4 w-4" /> : i + 1}
          </div>
          {i < total - 1 && (
            <div className={`h-px w-8 transition-all ${
              i < current ? 'bg-violet-500' : 'bg-gray-200 dark:bg-gray-700'
            }`} />
          )}
        </div>
      ))}
      <span className="ml-2 text-xs text-gray-400 font-mono">Paso {current + 1} de {total}</span>
    </div>
  )
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
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
    >
      <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
        ¿Qué sistema usás?
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Valinor se adapta a cualquier ERP o base de datos
      </p>

      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Nombre del cliente / empresa
        </label>
        <input
          type="text"
          value={clientName}
          onChange={e => onClientName(e.target.value)}
          placeholder="Ej: Gloria Pet Distribution"
          className="w-full px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500 text-sm"
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {ERP_OPTIONS.map(erp => (
          <button
            key={erp.id}
            type="button"
            onClick={() => !erp.comingSoon && onSelect(erp.id, erp.db)}
            disabled={!!erp.comingSoon}
            className={`relative text-left p-4 rounded-2xl border-2 transition-all ${
              erp.comingSoon
                ? 'opacity-50 cursor-not-allowed border-gray-200 dark:border-gray-800'
                : selected === erp.id
                  ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20 shadow-md'
                  : 'border-gray-200 dark:border-gray-700 hover:border-violet-300 dark:hover:border-violet-700 hover:shadow-sm'
            }`}
          >
            {erp.popular && !erp.comingSoon && (
              <span className="absolute top-2 right-2 text-xs font-semibold text-violet-600 dark:text-violet-400 bg-violet-100 dark:bg-violet-900/50 px-1.5 py-0.5 rounded-full">
                Popular
              </span>
            )}
            {erp.comingSoon && (
              <span className="absolute top-2 right-2 text-xs text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded-full">
                Pronto
              </span>
            )}
            <div className="text-2xl mb-2">{erp.icon}</div>
            <div className="font-semibold text-sm text-gray-900 dark:text-white">{erp.name}</div>
            <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 leading-snug">{erp.description}</div>
            {selected === erp.id && (
              <div className="absolute bottom-2 right-2">
                <CheckCircle2 className="h-4 w-4 text-violet-600" />
              </div>
            )}
          </button>
        ))}
      </div>

      {selected && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-4 flex items-start gap-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl px-4 py-3"
        >
          <Zap className="h-4 w-4 text-blue-500 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-blue-700 dark:text-blue-300">
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
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
    >
      <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
        Conectá tu base de datos
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
        Conexión de solo lectura · tus datos nunca se almacenan
      </p>

      <div className="flex items-center gap-2 mb-5 px-4 py-2.5 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl">
        <Shield className="h-4 w-4 text-emerald-500 flex-shrink-0" />
        <p className="text-xs text-emerald-700 dark:text-emerald-300">
          Zero Data Storage — Valinor solo lee, nunca escribe ni almacena datos de clientes
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2 sm:col-span-1">
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5 uppercase tracking-wide">Host</label>
          <input {...register('db_host')} placeholder="localhost"
            className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500" />
          {errors.db_host && <p className="text-xs text-red-500 mt-1">{errors.db_host.message}</p>}
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5 uppercase tracking-wide">Puerto</label>
          <input {...register('db_port')} type="number" placeholder="5432"
            className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500" />
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5 uppercase tracking-wide">Base de datos</label>
          <input {...register('db_name')} placeholder="nombre_de_la_base"
            className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500" />
          {errors.db_name && <p className="text-xs text-red-500 mt-1">{errors.db_name.message}</p>}
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5 uppercase tracking-wide">Usuario</label>
          <input {...register('db_user')} placeholder="readonly_user"
            className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500" />
          {errors.db_user && <p className="text-xs text-red-500 mt-1">{errors.db_user.message}</p>}
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5 uppercase tracking-wide">Contraseña</label>
          <input {...register('db_password')} type="password" placeholder="••••••••"
            className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500" />
          {errors.db_password && <p className="text-xs text-red-500 mt-1">{errors.db_password.message}</p>}
        </div>

        <div className="col-span-2 mt-1">
          <button
            type="button"
            onClick={onTestConnection}
            disabled={testingConnection || !watch('db_host') || !watch('db_user')}
            className="w-full py-2 px-4 rounded-lg border-2 border-violet-200 text-violet-700 hover:border-violet-400 disabled:opacity-50 text-sm font-medium transition-all"
          >
            {testingConnection ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />Probando conexión...
              </span>
            ) : 'Probar conexión'}
          </button>

          {testResult && (
            <div className={`mt-2 rounded-lg p-3 text-sm ${testResult.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
              {testResult.success ? (
                <div className="space-y-1">
                  <p className="text-green-800 font-medium">
                    ✓ Conectado ({testResult.latency_ms}ms) · {testResult.erp_detected} · {testResult.table_count} tablas
                  </p>
                  {testResult.data_from && testResult.data_to && (
                    <p className="text-green-700 text-xs flex items-center gap-1">
                      <Calendar className="h-3 w-3" />
                      Datos disponibles: <strong>{testResult.data_from}</strong> → <strong>{testResult.data_to}</strong>
                    </p>
                  )}
                </div>
              ) : (
                <div className="text-red-800">✗ Error: {testResult.error}</div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="mt-5">
        <label className="flex items-center gap-3 cursor-pointer">
          <div className={`relative w-10 h-5 rounded-full transition-colors ${useSsh ? 'bg-violet-600' : 'bg-gray-200 dark:bg-gray-700'}`}>
            <input type="checkbox" {...register('use_ssh')} className="sr-only" />
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${useSsh ? 'translate-x-5' : ''}`} />
          </div>
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Tunnel SSH</span>
          <span className="text-xs text-gray-400">(si la DB no es accesible directamente)</span>
        </label>

        <AnimatePresence>
          {useSsh && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 grid grid-cols-2 gap-4 overflow-hidden"
            >
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5 uppercase tracking-wide">SSH Host</label>
                <input {...register('ssh_host')} placeholder="bastion.empresa.com"
                  className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5 uppercase tracking-wide">SSH Usuario</label>
                <input {...register('ssh_user')} placeholder="ubuntu"
                  className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500" />
              </div>
              <div className="col-span-2">
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5 uppercase tracking-wide">Ruta de clave privada</label>
                <input {...register('ssh_key_path')} placeholder="/home/user/.ssh/id_rsa"
                  className="w-full px-3 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500" />
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
    { icon: '🗺️', text: 'Mapeo automático de entidades de negocio' },
    { icon: '🔍', text: 'Detección de anomalías y riesgos financieros' },
    { icon: '💰', text: 'Identificación de oportunidades de mejora' },
    { icon: '📋', text: 'Reporte ejecutivo listo para el CEO' },
  ]

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
    >
      <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
        Elegí el período a analizar
      </h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
        {dataFrom && dataTo
          ? `Datos disponibles: ${dataFrom} → ${dataTo}`
          : 'Seleccioná el rango de tiempo para el análisis'}
      </p>

      {/* Summary card */}
      <div className="bg-gray-50 dark:bg-gray-800/50 rounded-2xl border border-gray-200 dark:border-gray-700 p-4 mb-5">
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <p className="text-xs text-gray-400 mb-0.5">Cliente</p>
            <p className="font-semibold text-gray-900 dark:text-white">{clientName || '—'}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-0.5">Sistema</p>
            <p className="font-semibold text-gray-900 dark:text-white">{erp?.icon} {erp?.name || '—'}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-0.5">Host</p>
            <p className="font-mono text-xs text-gray-700 dark:text-gray-300 truncate">{dbHost || '—'}</p>
          </div>
          <div>
            <p className="text-xs text-gray-400 mb-0.5">Base de datos</p>
            <p className="font-mono text-xs text-gray-700 dark:text-gray-300 truncate">{dbName || '—'}</p>
          </div>
        </div>
      </div>

      {/* Period tabs */}
      <div className="mb-2">
        <div className="flex gap-1 p-1 bg-gray-100 dark:bg-gray-800 rounded-xl mb-3 w-fit">
          {(['month', 'quarter', 'year'] as PeriodTab[]).map(t => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                tab === t
                  ? 'bg-white dark:bg-gray-700 text-violet-700 dark:text-violet-300 shadow-sm'
                  : 'text-gray-500 dark:text-gray-400 hover:text-gray-700'
              }`}
            >
              {t === 'month' ? 'Mes' : t === 'quarter' ? 'Trimestre' : 'Año'}
            </button>
          ))}
        </div>

        <div className="grid grid-cols-3 gap-1.5 max-h-48 overflow-y-auto pr-1">
          {opts.map(p => (
            <button
              key={p.value}
              type="button"
              onClick={() => onPeriod(p.value)}
              className={`text-xs py-2 px-2 rounded-xl border transition-all text-left leading-tight ${
                period === p.value
                  ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 font-semibold'
                  : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-violet-300 hover:bg-gray-50'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>

        {period && (
          <div className="mt-2 flex items-center gap-2 text-xs text-violet-600 dark:text-violet-400">
            <CheckCircle2 className="h-3.5 w-3.5" />
            Período seleccionado: <strong>{period}</strong>
          </div>
        )}
      </div>

      {/* What to expect */}
      <div className="mt-4 mb-4">
        <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">Qué vas a recibir</p>
        <div className="grid grid-cols-2 gap-2">
          {whatToExpect.map((item, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-gray-600 dark:text-gray-400">
              <span className="flex-shrink-0">{item.icon}</span>
              <span>{item.text}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-3 text-xs text-gray-400 mb-1">
        <Clock className="h-3.5 w-3.5 flex-shrink-0" />
        <span>Tiempo estimado: 10-15 minutos según el tamaño de la base</span>
      </div>

      {jobId && (
        <div className="mt-3 flex items-center gap-2 bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 rounded-xl px-4 py-2.5">
          <Lock className="h-3.5 w-3.5 text-violet-400 flex-shrink-0" />
          <span className="text-xs text-violet-600 dark:text-violet-400 font-mono">
            Job ID: <strong>{jobId}</strong>
          </span>
        </div>
      )}

      {error && (
        <div className="mt-3 flex items-start gap-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl px-4 py-3">
          <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
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
    // Guard: only submit on the final confirmation step
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
    <div className="max-w-2xl mx-auto bg-white dark:bg-gray-900 rounded-3xl border border-gray-200 dark:border-gray-700 shadow-xl overflow-hidden">
      <div className="px-8 pt-8 pb-0">
        <StepIndicator current={step} total={3} />
      </div>

      <form onSubmit={handleSubmit(onSubmit)}>
        <div className="px-8 py-6 min-h-[420px]">
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
        <div className="px-8 pb-8 flex items-center justify-between border-t border-gray-100 dark:border-gray-800 pt-5">
          <button
            type="button"
            onClick={() => step > 0 && setStep(s => s - 1)}
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all ${
              step === 0
                ? 'invisible'
                : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white border border-gray-200 dark:border-gray-700 hover:border-gray-300'
            }`}
          >
            <ChevronLeft className="h-4 w-4" />Atrás
          </button>

          {step < 2 ? (
            <button
              type="button"
              onClick={() => canProceed() && setStep(s => s + 1)}
              disabled={!canProceed()}
              className="flex items-center gap-2 px-6 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-xl text-sm font-semibold transition-all shadow-sm shadow-violet-500/20"
            >
              Continuar<ChevronRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={isLoading || !period}
              className="flex items-center gap-2 px-6 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-xl text-sm font-semibold transition-all shadow-sm shadow-violet-500/20"
            >
              {isLoading ? (
                <><Loader2 className="h-4 w-4 animate-spin" />Iniciando análisis...</>
              ) : (
                <>Iniciar análisis<ArrowRight className="h-4 w-4" /></>
              )}
            </button>
          )}
        </div>
      </form>
    </div>
  )
}
