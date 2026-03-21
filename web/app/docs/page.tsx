import Link from 'next/link'
import { T } from '@/components/d4c/tokens'

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

// Method badge colors
const METHOD_COLOR: Record<Endpoint['method'], string> = {
  GET:    T.accent.teal,
  POST:   T.accent.blue,
  PUT:    T.accent.orange,
  DELETE: T.accent.red,
}

// Category colors (all use T tokens — varied accents for distinction)
const CATEGORY_COLOR: Record<Endpoint['category'], string> = {
  Analysis:    T.accent.teal,
  Jobs:        T.accent.blue,
  Clients:     T.accent.blue,
  Quality:     T.accent.teal,
  System:      T.text.tertiary,
  Reports:     T.accent.yellow,
  Onboarding:  T.accent.teal,
  Alerts:      T.accent.red,
  Segmentation: T.accent.orange,
}

const ALL_CATEGORIES = [
  'Analysis', 'Jobs', 'Reports', 'Quality', 'Clients',
  'Alerts', 'Segmentation', 'Onboarding', 'System',
] as const

function MethodBadge({ method }: { method: Endpoint['method'] }) {
  const color = METHOD_COLOR[method]
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: T.radius.sm,
      fontSize: 11,
      fontWeight: 700,
      fontFamily: T.font.mono,
      backgroundColor: color + '15',
      border: `1px solid ${color}40`,
      color,
    }}>
      {method}
    </span>
  )
}

function CategoryBadge({ category }: { category: Endpoint['category'] }) {
  const color = CATEGORY_COLOR[category]
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 10px',
      borderRadius: 999,
      fontSize: 11,
      fontWeight: 500,
      backgroundColor: color + '10',
      border: `1px solid ${color}25`,
      color,
    }}>
      {category}
    </span>
  )
}

export default function DocsPage() {
  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* Header */}
      <header style={{ position: 'sticky', top: 0, zIndex: 50, backgroundColor: T.bg.card, borderBottom: T.border.card }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: `${T.space.md} ${T.space.xl}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm }}>
            <Link href="/" style={{ fontSize: 16, fontWeight: 700, color: T.text.primary, textDecoration: 'none' }}>
              Valinor SaaS
            </Link>
            <span style={{ color: T.text.tertiary, fontSize: 13 }}>/ API Reference</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg, fontSize: 13 }}>
            <Link href="/" style={{ color: T.text.secondary, textDecoration: 'none' }}>Home</Link>
            <Link href="/dashboard" style={{ color: T.text.secondary, textDecoration: 'none' }}>Dashboard</Link>
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="d4c-btn-primary"
              style={{ fontSize: 12 }}
            >
              Interactive docs (Swagger)
            </a>
          </div>
        </div>
      </header>

      <main style={{ maxWidth: 1280, margin: '0 auto', padding: `${T.space.xl} ${T.space.xl}` }}>
        {/* Title block */}
        <div style={{ marginBottom: T.space.xl }}>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: T.text.primary, marginBottom: T.space.sm }}>API Reference</h1>
          <p style={{ color: T.text.secondary, maxWidth: 680, fontSize: 14 }}>
            Valinor SaaS v2.0 — all endpoints exposed by the FastAPI backend at{' '}
            <code style={{ fontFamily: T.font.mono, fontSize: 12, color: T.accent.teal, backgroundColor: T.accent.teal + '10', padding: '2px 6px', borderRadius: T.radius.sm }}>
              http://localhost:8000
            </code>
          </p>
          <p style={{ fontSize: 12, color: T.text.tertiary, marginTop: 4 }}>
            {endpoints.length} endpoints across {ALL_CATEGORIES.length} categories
          </p>
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: T.space.sm, marginBottom: T.space.xl }}>
          {(['GET', 'POST', 'PUT', 'DELETE'] as const).map(m => (
            <MethodBadge key={m} method={m} />
          ))}
          <span style={{ color: T.bg.hover, margin: '0 8px' }}>|</span>
          {ALL_CATEGORIES.map(cat => (
            <CategoryBadge key={cat} category={cat as Endpoint['category']} />
          ))}
        </div>

        {/* Sections by category */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.xxl }}>
          {ALL_CATEGORIES.map(category => {
            const group = endpoints.filter(e => e.category === category)
            if (group.length === 0) return null
            const catColor = CATEGORY_COLOR[category as Endpoint['category']]
            return (
              <section key={category} id={category.toLowerCase()}>
                <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm, marginBottom: T.space.sm }}>
                  <h2 style={{ fontSize: 16, fontWeight: 600, color: T.text.primary, margin: 0 }}>{category}</h2>
                  <CategoryBadge category={category as Endpoint['category']} />
                </div>

                <div style={{ backgroundColor: T.bg.card, borderRadius: T.radius.lg, border: T.border.card, overflow: 'hidden' }}>
                  {/* Table header */}
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: '100px 280px 1fr',
                    gap: T.space.md,
                    padding: `${T.space.sm} ${T.space.lg}`,
                    backgroundColor: T.bg.elevated,
                    borderBottom: T.border.card,
                  }}>
                    {['Method', 'Path', 'Description'].map(h => (
                      <span key={h} style={{ fontSize: 10, fontWeight: 600, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.text.tertiary }}>
                        {h}
                      </span>
                    ))}
                  </div>

                  {/* Rows */}
                  {group.map((endpoint, idx) => (
                    <div
                      key={idx}
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '100px 280px 1fr',
                        gap: T.space.md,
                        padding: `12px ${T.space.lg}`,
                        alignItems: 'start',
                        borderTop: idx > 0 ? T.border.subtle : undefined,
                      }}
                    >
                      <div>
                        <MethodBadge method={endpoint.method} />
                      </div>
                      <code style={{ fontFamily: T.font.mono, fontSize: 12, color: T.text.secondary, wordBreak: 'break-all' }}>
                        {endpoint.path}
                      </code>
                      <span style={{ fontSize: 13, color: T.text.secondary }}>
                        {endpoint.description}
                      </span>
                    </div>
                  ))}
                </div>
              </section>
            )
          })}
        </div>

        {/* Typical flow callout */}
        <div style={{
          marginTop: T.space.xxl,
          padding: T.space.xl,
          borderRadius: T.radius.lg,
          backgroundColor: T.accent.teal + '08',
          border: `1px solid ${T.accent.teal}30`,
        }}>
          <h3 style={{ fontSize: 13, fontWeight: 600, color: T.accent.teal, marginBottom: T.space.sm }}>Typical analysis flow</h3>
          <ol style={{ paddingLeft: T.space.lg, display: 'flex', flexDirection: 'column', gap: T.space.xs }}>
            {[
              ['POST /api/onboarding/test-connection', '— validate DB connectivity and detect ERP'],
              ['POST /api/analyze', '— start analysis, receive job_id'],
              ['GET /api/jobs/{job_id}/stream', '— subscribe to SSE for real-time progress'],
              ['GET /api/jobs/{job_id}/quality', '— inspect Data Quality Gate report'],
              ['GET /api/jobs/{job_id}/results', '— fetch complete analysis results'],
              ['GET /api/jobs/{job_id}/pdf', '— download branded executive PDF'],
            ].map(([cmd, desc], i) => (
              <li key={i} style={{ fontSize: 13, color: T.text.secondary }}>
                <code style={{ fontFamily: T.font.mono, fontSize: 12, color: T.accent.teal }}>{cmd}</code>
                <span> {desc}</span>
              </li>
            ))}
          </ol>
        </div>
      </main>

      {/* Footer */}
      <footer style={{ marginTop: T.space.xxl, borderTop: T.border.card, backgroundColor: T.bg.card }}>
        <div style={{ maxWidth: 1280, margin: '0 auto', padding: `${T.space.lg} ${T.space.xl}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, color: T.text.tertiary }}>
          <span>Valinor SaaS v2.0 — Delta 4C</span>
          <div style={{ display: 'flex', gap: T.space.lg }}>
            <Link href="/" style={{ color: T.text.tertiary, textDecoration: 'none' }}>Home</Link>
            <Link href="/dashboard" style={{ color: T.text.tertiary, textDecoration: 'none' }}>Dashboard</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
