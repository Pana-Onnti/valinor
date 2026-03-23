'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { T, SEV_COLOR } from '@/components/d4c/tokens'
import { getToken } from '@/lib/auth'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface Report {
  id: string
  date: string
  period: string
  findings_count: number
  critical: number
  warnings: number
  opportunities: number
  status: string
}

export default function PortalReportsPage() {
  const router = useRouter()
  const [reports, setReports] = useState<Report[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const token = getToken()
        const res = await fetch(`${BASE_URL}/api/v1/portal/reports`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          setReports(data.reports || [])
        }
      } catch {
        // empty
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: T.space.xl }}>
        Reportes
      </h1>

      {loading ? (
        <div style={{ color: T.text.tertiary, textAlign: 'center', padding: T.space.xxl }}>
          Cargando...
        </div>
      ) : reports.length === 0 ? (
        <div style={{
          backgroundColor: T.bg.card,
          borderRadius: T.radius.md,
          border: T.border.card,
          padding: T.space.xxl,
          textAlign: 'center',
        }}>
          <p style={{ color: T.text.secondary }}>No hay reportes disponibles todavia.</p>
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
          gap: T.space.md,
        }}>
          {reports.map((r) => (
            <div
              key={r.id}
              onClick={() => router.push(`/portal/reports/${r.id}`)}
              style={{
                backgroundColor: T.bg.card,
                borderRadius: T.radius.md,
                border: T.border.card,
                padding: T.space.lg,
                cursor: 'pointer',
                transition: 'border-color 0.2s',
              }}
              onMouseEnter={(e) => e.currentTarget.style.borderColor = T.accent.teal}
              onMouseLeave={(e) => e.currentTarget.style.borderColor = '#282838'}
            >
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                marginBottom: T.space.md,
              }}>
                <div>
                  <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0 }}>
                    {r.period}
                  </h3>
                  <span style={{ color: T.text.tertiary, fontSize: '0.813rem' }}>
                    {new Date(r.date).toLocaleDateString('es-AR', {
                      day: 'numeric', month: 'long', year: 'numeric',
                    })}
                  </span>
                </div>
                <span style={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  color: r.status === 'completed' ? T.accent.teal : T.text.tertiary,
                  textTransform: 'uppercase',
                }}>
                  {r.status === 'completed' ? 'Completo' : r.status}
                </span>
              </div>

              <div style={{
                display: 'flex',
                gap: T.space.lg,
                fontSize: '0.875rem',
              }}>
                <div>
                  <span style={{ color: T.text.tertiary }}>Hallazgos: </span>
                  <span style={{ fontWeight: 600 }}>{r.findings_count}</span>
                </div>
                {r.critical > 0 && (
                  <div>
                    <span style={{ color: T.text.tertiary }}>Criticos: </span>
                    <span style={{ fontWeight: 600, color: SEV_COLOR.CRITICAL }}>{r.critical}</span>
                  </div>
                )}
                {r.opportunities > 0 && (
                  <div>
                    <span style={{ color: T.text.tertiary }}>Oportunidades: </span>
                    <span style={{ fontWeight: 600, color: T.accent.blue }}>{r.opportunities}</span>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
