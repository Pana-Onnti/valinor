'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { T, SEV_COLOR } from '@/components/d4c/tokens'
import { getClient, getToken } from '@/lib/auth'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

interface ReportSummary {
  id: string
  date: string
  period: string
  findings_count: number
  critical: number
  warnings: number
  opportunities: number
}

export default function PortalDashboard() {
  const router = useRouter()
  const client = getClient()
  const [reports, setReports] = useState<ReportSummary[]>([])
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
        // API may not be ready yet — show empty state
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const latest = reports[0]

  return (
    <div>
      {/* Welcome */}
      <div style={{ marginBottom: T.space.xl }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0 }}>
          Bienvenido{client?.name ? `, ${client.name}` : ''}
        </h1>
        <p style={{ color: T.text.secondary, marginTop: T.space.xs }}>
          Tu panel de diagnosticos e insights financieros.
        </p>
      </div>

      {/* Hero: Latest Report */}
      {latest ? (
        <div
          onClick={() => router.push(`/portal/reports/${latest.id}`)}
          style={{
            backgroundColor: T.bg.card,
            borderRadius: T.radius.md,
            border: T.border.card,
            padding: T.space.xl,
            cursor: 'pointer',
            marginBottom: T.space.xl,
            transition: 'border-color 0.2s',
          }}
          onMouseEnter={(e) => e.currentTarget.style.borderColor = T.accent.teal}
          onMouseLeave={(e) => e.currentTarget.style.borderColor = '#282838'}
        >
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
          }}>
            <div>
              <span style={{
                fontSize: '0.75rem',
                color: T.accent.teal,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}>
                Ultimo diagnostico
              </span>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 600, margin: `${T.space.sm} 0` }}>
                Reporte {latest.period}
              </h2>
              <span style={{ color: T.text.tertiary, fontSize: '0.875rem' }}>
                {new Date(latest.date).toLocaleDateString('es-AR', {
                  day: 'numeric', month: 'long', year: 'numeric',
                })}
              </span>
            </div>
            <div style={{ display: 'flex', gap: T.space.md }}>
              {latest.critical > 0 && (
                <Stat label="Criticos" value={latest.critical} color={SEV_COLOR.CRITICAL} />
              )}
              <Stat label="Hallazgos" value={latest.findings_count} color={T.accent.teal} />
              <Stat label="Oportunidades" value={latest.opportunities} color={T.accent.blue} />
            </div>
          </div>
        </div>
      ) : !loading ? (
        <div style={{
          backgroundColor: T.bg.card,
          borderRadius: T.radius.md,
          border: T.border.card,
          padding: T.space.xxl,
          textAlign: 'center',
        }}>
          <p style={{ color: T.text.secondary, fontSize: '1rem' }}>
            Todavia no hay diagnosticos disponibles.
          </p>
          <p style={{ color: T.text.tertiary, fontSize: '0.875rem', marginTop: T.space.sm }}>
            Tu equipo de Delta 4C va a correr el primer analisis pronto.
          </p>
        </div>
      ) : null}

      {/* Report history */}
      {reports.length > 1 && (
        <div>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: T.space.md }}>
            Historial de diagnosticos
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: T.space.sm }}>
            {reports.slice(1).map((r) => (
              <div
                key={r.id}
                onClick={() => router.push(`/portal/reports/${r.id}`)}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  backgroundColor: T.bg.card,
                  borderRadius: T.radius.sm,
                  border: T.border.subtle,
                  padding: `${T.space.md} ${T.space.lg}`,
                  cursor: 'pointer',
                  transition: 'background-color 0.2s',
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = T.bg.elevated}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = T.bg.card}
              >
                <div>
                  <span style={{ fontWeight: 500 }}>{r.period}</span>
                  <span style={{ color: T.text.tertiary, fontSize: '0.813rem', marginLeft: T.space.md }}>
                    {new Date(r.date).toLocaleDateString('es-AR')}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: T.space.md, fontSize: '0.813rem' }}>
                  <span style={{ color: T.text.secondary }}>{r.findings_count} hallazgos</span>
                  {r.critical > 0 && (
                    <span style={{ color: SEV_COLOR.CRITICAL }}>{r.critical} criticos</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading && (
        <div style={{ textAlign: 'center', padding: T.space.xxl }}>
          <div style={{ color: T.text.tertiary }}>Cargando reportes...</div>
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: '1.5rem', fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: '0.75rem', color: T.text.tertiary }}>{label}</div>
    </div>
  )
}
