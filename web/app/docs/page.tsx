import Link from 'next/link'

interface Endpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  description: string
  category: 'Analysis' | 'Jobs' | 'Clients' | 'Quality' | 'System' | 'Reports' | 'Onboarding' | 'Alerts' | 'Segmentation'
}

const endpoints: Endpoint[] = [
  // System
  { method: 'GET', path: '/health', description: 'Service health check — Redis and storage status', category: 'System' },
  { method: 'GET', path: '/api/system/status', description: 'Comprehensive system status: services, versions, feature flags, installed packages', category: 'System' },
  { method: 'GET', path: '/api/system/metrics', description: 'Operational metrics — job counts by status, success rate, client count', category: 'System' },

  // Analysis
  { method: 'POST', path: '/api/analyze', description: 'Start a new analysis job. Returns job_id immediately. Rate limited: 10/min', category: 'Analysis' },

  // Jobs
  { method: 'GET', path: '/api/jobs', description: 'List recent analysis jobs. Supports ?status_filter=completed|failed|pending|running|cancelled and ?limit=N', category: 'Jobs' },
  { method: 'GET', path: '/api/jobs/{job_id}/status', description: 'Get current status of an analysis job (pending, running, completed, failed)', category: 'Jobs' },
  { method: 'GET', path: '/api/jobs/{job_id}/stream', description: 'Server-Sent Events (SSE) stream for real-time job progress. Closes automatically on completion', category: 'Jobs' },
  { method: 'GET', path: '/api/jobs/{job_id}/results', description: 'Get full results from a completed analysis job, including download URLs', category: 'Jobs' },
  { method: 'GET', path: '/api/jobs/{job_id}/download/{filename}', description: 'Download a specific result file (executive_report.pdf, ceo_report.pdf, controller_report.pdf, sales_report.pdf, raw_data.json)', category: 'Jobs' },
  { method: 'POST', path: '/api/jobs/{job_id}/cancel', description: 'Cancel a running or pending job', category: 'Jobs' },
  { method: 'POST', path: '/api/jobs/{job_id}/retry', description: 'Retry a failed or cancelled job with the original parameters', category: 'Jobs' },

  // Reports
  { method: 'GET', path: '/api/jobs/{job_id}/pdf', description: 'Generate and download a branded PDF report for a completed job. Rate limited: 30/min', category: 'Reports' },
  { method: 'GET', path: '/api/jobs/{job_id}/digest', description: 'Preview HTML email digest for a completed job', category: 'Reports' },
  { method: 'POST', path: '/api/jobs/{job_id}/send-digest', description: 'Send email digest to a specified address (?to_email=...)', category: 'Reports' },

  // Quality
  { method: 'GET', path: '/api/jobs/{job_id}/quality', description: 'Get the Data Quality Gate report for a completed job (score, label, currency warnings)', category: 'Quality' },
  { method: 'GET', path: '/api/quality/schema/{client_name}', description: 'Run a real-time schema integrity check description for a client (requires active connection via /api/analyze)', category: 'Quality' },
  { method: 'GET', path: '/api/quality/methodology', description: 'Returns the full data quality methodology documentation (9 checks, score interpretation)', category: 'Quality' },
  { method: 'GET', path: '/api/clients/{client_name}/dq-history', description: 'Historical DQ scores for a client, with average and trend (improving / stable / declining)', category: 'Quality' },

  // Clients
  { method: 'GET', path: '/api/clients', description: 'List all clients that have profiles', category: 'Clients' },
  { method: 'GET', path: '/api/clients/summary', description: 'Aggregated summary of all clients: total critical findings, average DQ score, total runs', category: 'Clients' },
  { method: 'GET', path: '/api/clients/{client_name}/profile', description: 'Get the persistent ClientProfile for a client (run history, findings, baseline)', category: 'Clients' },
  { method: 'PUT', path: '/api/clients/{client_name}/profile/false-positive', description: 'Mark a finding as a false positive — suppressed in future runs (?finding_id=...)', category: 'Clients' },
  { method: 'DELETE', path: '/api/clients/{client_name}/profile', description: 'Reset (delete) a client profile. Use when the database schema changes significantly', category: 'Clients' },
  { method: 'GET', path: '/api/clients/{client_name}/stats', description: 'Summary stats: run count, active/resolved findings, critical count, findings trend', category: 'Clients' },

  // Alerts
  { method: 'GET', path: '/api/clients/{client_name}/alerts', description: 'Get alert thresholds and recent triggered alerts for a client', category: 'Alerts' },
  { method: 'POST', path: '/api/clients/{client_name}/alerts', description: 'Add an alert threshold. Body: { label, metric, operator, value }', category: 'Alerts' },
  { method: 'DELETE', path: '/api/clients/{client_name}/alerts/{alert_label}', description: 'Remove an alert threshold by label', category: 'Alerts' },

  // Webhooks (under Clients)
  { method: 'GET', path: '/api/clients/{client_name}/webhooks', description: 'List registered webhooks for a client', category: 'Clients' },
  { method: 'POST', path: '/api/clients/{client_name}/webhooks', description: 'Register a webhook URL. Body: { url }. Max 5 per client', category: 'Clients' },
  { method: 'DELETE', path: '/api/clients/{client_name}/webhooks', description: 'Remove a webhook by URL (?url=...)', category: 'Clients' },

  // Segmentation
  { method: 'GET', path: '/api/clients/{client_name}/segmentation', description: 'Get latest customer segmentation results (segments, total customers, total revenue)', category: 'Segmentation' },

  // Onboarding
  { method: 'POST', path: '/api/onboarding/test-connection', description: 'Test DB connectivity and auto-detect ERP type (Odoo, iDempiere, generic). Ephemeral — no data stored', category: 'Onboarding' },
  { method: 'POST', path: '/api/onboarding/validate-period', description: 'Validate that a period string is correctly formatted (Q1-2025, H1-2025, 2025)', category: 'Onboarding' },
]

const METHOD_STYLES: Record<Endpoint['method'], string> = {
  GET:    'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  POST:   'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  PUT:    'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300',
  DELETE: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
}

const CATEGORY_STYLES: Record<Endpoint['category'], string> = {
  Analysis:    'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
  Jobs:        'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
  Clients:     'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  Quality:     'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  System:      'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
  Reports:     'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  Onboarding:  'bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300',
  Alerts:      'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  Segmentation:'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
}

const ALL_CATEGORIES = [
  'Analysis', 'Jobs', 'Reports', 'Quality', 'Clients',
  'Alerts', 'Segmentation', 'Onboarding', 'System',
] as const

export default function DocsPage() {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div>
              <Link href="/" className="text-xl font-bold text-gray-900 dark:text-white hover:text-indigo-600 transition-colors">
                Valinor SaaS
              </Link>
              <span className="ml-3 text-sm text-gray-400">/ API Reference</span>
            </div>
            <div className="flex items-center gap-4 text-sm">
              <Link href="/" className="text-gray-500 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-400 transition-colors">
                Home
              </Link>
              <Link href="/dashboard" className="text-gray-500 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-400 transition-colors">
                Dashboard
              </Link>
              <a
                href="http://localhost:8000/docs"
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
              >
                Interactive docs (Swagger)
              </a>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {/* Title block */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">API Reference</h1>
          <p className="text-gray-500 dark:text-gray-400 max-w-2xl">
            Valinor SaaS v2.0 — all endpoints exposed by the FastAPI backend at{' '}
            <code className="text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950 px-1.5 py-0.5 rounded text-sm">
              http://localhost:8000
            </code>
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-1">
            {endpoints.length} endpoints across {ALL_CATEGORIES.length} categories
          </p>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap gap-3 mb-8">
          {(['GET', 'POST', 'PUT', 'DELETE'] as const).map(m => (
            <span key={m} className={`px-2.5 py-1 rounded-md text-xs font-bold font-mono ${METHOD_STYLES[m]}`}>
              {m}
            </span>
          ))}
          <span className="mx-2 text-gray-300 dark:text-gray-600">|</span>
          {ALL_CATEGORIES.map(cat => (
            <span key={cat} className={`px-2 py-1 rounded-full text-xs font-medium ${CATEGORY_STYLES[cat as Endpoint['category']]}`}>
              {cat}
            </span>
          ))}
        </div>

        {/* Sections by category */}
        <div className="space-y-10">
          {ALL_CATEGORIES.map(category => {
            const group = endpoints.filter(e => e.category === category)
            if (group.length === 0) return null
            return (
              <section key={category} id={category.toLowerCase()}>
                <div className="flex items-center gap-3 mb-3">
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">{category}</h2>
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${CATEGORY_STYLES[category as Endpoint['category']]}`}>
                    {group.length} endpoint{group.length > 1 ? 's' : ''}
                  </span>
                </div>

                <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
                        <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-20">Method</th>
                        <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide w-80">Path</th>
                        <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">Description</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                      {group.map((endpoint, idx) => (
                        <tr
                          key={idx}
                          className="hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors"
                        >
                          <td className="px-4 py-3">
                            <span className={`px-2 py-0.5 rounded text-xs font-bold font-mono ${METHOD_STYLES[endpoint.method]}`}>
                              {endpoint.method}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <code className="text-xs text-gray-700 dark:text-gray-300 font-mono break-all">
                              {endpoint.path}
                            </code>
                          </td>
                          <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                            {endpoint.description}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )
          })}
        </div>

        {/* Typical flow callout */}
        <div className="mt-12 p-6 rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-950/40">
          <h3 className="text-sm font-semibold text-indigo-800 dark:text-indigo-300 mb-3">Typical analysis flow</h3>
          <ol className="space-y-1.5 text-sm text-indigo-700 dark:text-indigo-400 list-decimal list-inside">
            <li><code className="font-mono">POST /api/onboarding/test-connection</code> — validate DB connectivity and detect ERP</li>
            <li><code className="font-mono">POST /api/analyze</code> — start analysis, receive <code className="font-mono">job_id</code></li>
            <li><code className="font-mono">GET /api/jobs/{'{job_id}'}/stream</code> — subscribe to SSE for real-time progress</li>
            <li><code className="font-mono">GET /api/jobs/{'{job_id}'}/quality</code> — inspect Data Quality Gate report</li>
            <li><code className="font-mono">GET /api/jobs/{'{job_id}'}/results</code> — fetch complete analysis results</li>
            <li><code className="font-mono">GET /api/jobs/{'{job_id}'}/pdf</code> — download branded executive PDF</li>
          </ol>
        </div>
      </main>

      {/* Footer */}
      <footer className="mt-16 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex justify-between items-center text-sm text-gray-400">
          <span>Valinor SaaS v2.0 — Delta 4C</span>
          <div className="flex gap-4">
            <Link href="/" className="hover:text-indigo-600 transition-colors">Home</Link>
            <Link href="/dashboard" className="hover:text-indigo-600 transition-colors">Dashboard</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
