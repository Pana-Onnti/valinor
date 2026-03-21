'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Database, Zap, Shield, Clock, ArrowRight, CheckCircle2 } from 'lucide-react'
import Link from 'next/link'
import { DemoModeWrapper } from '@/components/DemoMode'
import { T } from '@/components/d4c/tokens'

export default function HomePage() {
  const [recentClients, setRecentClients] = useState<Array<{
    client_name: string
    run_count: number
    last_run_date: string | null
    known_findings_count: number
  }>>([])

  useEffect(() => {
    const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    fetch(`${API_URL}/api/clients`)
      .then(r => r.json())
      .then(data => setRecentClients(data.clients || []))
      .catch(() => {})
  }, [])

  const FEATURES = [
    { icon: Shield, title: 'Zero Data Storage', description: 'Tus datos nunca salen de tu servidor' },
    { icon: Clock,  title: '15 Min Analysis',   description: 'Insights completos en tiempo récord' },
    { icon: Zap,    title: 'Multi-Agent AI',     description: 'Claude Opus + Sonnet en paralelo' },
    { icon: Database, title: 'Any Database',     description: 'PostgreSQL, MySQL, SQL Server, Oracle' },
  ]

  return (
    <div style={{ minHeight: '100vh', padding: T.space.xl }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>

        {/* Returning user — client cards */}
        {recentClients.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: T.space.xxl }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: T.space.lg, flexWrap: 'wrap', gap: T.space.md }}>
              <div>
                <p style={{ fontSize: 10, fontFamily: T.font.mono, letterSpacing: '0.1em', textTransform: 'uppercase', color: T.accent.teal, marginBottom: 4 }}>
                  Sistema activo
                </p>
                <h2 style={{ fontSize: 28, fontWeight: 700, color: T.text.primary, margin: 0 }}>
                  {recentClients.length === 1
                    ? `Bienvenido de vuelta, ${recentClients[0].client_name.replace('_', ' ')}`
                    : `${recentClients.length} clientes monitoreados`}
                </h2>
              </div>
              <Link href="/new-analysis" className="d4c-btn-primary">
                Nuevo análisis <ArrowRight size={14} />
              </Link>
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: recentClients.length === 1 ? '1fr' : 'repeat(auto-fill, minmax(220px, 1fr))',
              maxWidth: recentClients.length === 1 ? 400 : undefined,
              gap: T.space.md,
              marginBottom: T.space.xl,
            }}>
              {recentClients.slice(0, 8).map(client => (
                <a
                  key={client.client_name}
                  href={`/clients/${encodeURIComponent(client.client_name)}/history`}
                  style={{
                    backgroundColor: T.bg.card,
                    border: T.border.card,
                    borderRadius: T.radius.md,
                    padding: T.space.lg,
                    textDecoration: 'none',
                    display: 'block',
                    transition: 'border-color 150ms ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div style={{
                      padding: 8,
                      borderRadius: T.radius.sm,
                      backgroundColor: T.accent.teal + '15',
                    }}>
                      <Database size={14} style={{ color: T.accent.teal }} />
                    </div>
                    <span style={{ fontSize: 11, color: T.text.tertiary, fontFamily: T.font.mono }}>
                      {client.run_count} runs
                    </span>
                  </div>
                  <p style={{ fontWeight: 700, color: T.text.primary, marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 14 }}>
                    {client.client_name.replace(/_/g, ' ')}
                  </p>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    {client.known_findings_count > 0 ? (
                      <span style={{ fontSize: 11, fontWeight: 500, color: T.accent.orange, display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: T.accent.orange, display: 'inline-block' }} />
                        {client.known_findings_count} activo{client.known_findings_count > 1 ? 's' : ''}
                      </span>
                    ) : (
                      <span style={{ fontSize: 11, color: T.accent.teal, display: 'flex', alignItems: 'center', gap: 4 }}>
                        <CheckCircle2 size={10} />Sin alertas
                      </span>
                    )}
                    {client.last_run_date && (
                      <span style={{ fontSize: 11, color: T.text.tertiary }}>
                        {new Date(client.last_run_date).toLocaleDateString('es', { day: 'numeric', month: 'short' })}
                      </span>
                    )}
                  </div>
                </a>
              ))}
            </div>
          </motion.div>
        )}

        {/* New user hero */}
        {recentClients.length === 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            style={{ textAlign: 'center', marginBottom: T.space.xxl }}
          >
            <h2 style={{ fontSize: 44, fontWeight: 700, color: T.text.primary, marginBottom: T.space.md, lineHeight: 1.1 }}>
              Business Intelligence en{' '}
              <span style={{ color: T.accent.teal }}>15 minutos</span>
            </h2>
            <p style={{ fontSize: 18, color: T.text.secondary, maxWidth: 600, margin: '0 auto', marginBottom: T.space.xl }}>
              Conectá tu base de datos, dejá que los agentes AI la analicen, y recibí insights ejecutivos sin almacenar nada.
            </p>
            <Link href="/new-analysis" className="d4c-btn-primary" style={{ fontSize: 15, padding: '14px 32px' }}>
              Comenzar análisis <ArrowRight size={16} />
            </Link>
          </motion.div>
        )}

        {/* Features — only new users */}
        {recentClients.length === 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: T.space.md, marginBottom: T.space.xxl }}>
            {FEATURES.map((f, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.1 }}
                style={{ backgroundColor: T.bg.card, border: T.border.card, borderRadius: T.radius.md, padding: T.space.lg }}
              >
                <f.icon size={24} style={{ color: T.accent.teal, marginBottom: T.space.sm }} />
                <h3 style={{ fontWeight: 600, color: T.text.primary, marginBottom: 6, fontSize: 14 }}>{f.title}</h3>
                <p style={{ fontSize: 12, color: T.text.secondary }}>{f.description}</p>
              </motion.div>
            ))}
          </div>
        )}

        <div style={{ marginTop: T.space.lg }}>
          <DemoModeWrapper />
        </div>

        {/* Footer */}
        <footer style={{ marginTop: T.space.xxl, paddingTop: T.space.lg, borderTop: T.border.card }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <p style={{ fontSize: 12, color: T.text.tertiary }}>© 2026 Delta 4C — Valinor SaaS v2.0</p>
            <div style={{ display: 'flex', gap: T.space.lg }}>
              <Link href="/docs" style={{ fontSize: 12, color: T.text.tertiary, textDecoration: 'none' }}>API docs</Link>
              <Link href="/dashboard" style={{ fontSize: 12, color: T.text.tertiary, textDecoration: 'none' }}>Dashboard</Link>
            </div>
          </div>
        </footer>
      </div>
    </div>
  )
}
