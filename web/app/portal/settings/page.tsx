'use client'

import { useEffect, useState } from 'react'
import { T } from '@/components/d4c/tokens'
import { getClient, getToken } from '@/lib/auth'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function PortalSettingsPage() {
  const client = getClient()
  const [dbStatus, setDbStatus] = useState<'connected' | 'disconnected' | 'checking'>('checking')
  const [frequency, setFrequency] = useState('monthly')
  const [emailDigest, setEmailDigest] = useState(true)

  useEffect(() => {
    // Check DB connection status
    async function checkStatus() {
      try {
        const token = getToken()
        const res = await fetch(`${BASE_URL}/api/v1/portal/status`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          setDbStatus(data.db_connected ? 'connected' : 'disconnected')
          setFrequency(data.frequency || 'monthly')
          setEmailDigest(data.email_digest ?? true)
        } else {
          setDbStatus('disconnected')
        }
      } catch {
        setDbStatus('disconnected')
      }
    }
    checkStatus()
  }, [])

  return (
    <div>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: T.space.xl }}>
        Configuracion
      </h1>

      {/* Account info */}
      <Section title="Cuenta">
        <Row label="Empresa" value={client?.name || '—'} />
        <Row label="Email" value={client?.email || '—'} />
      </Section>

      {/* DB connection */}
      <Section title="Conexion de datos">
        <Row
          label="Estado"
          value={
            dbStatus === 'checking' ? 'Verificando...' :
            dbStatus === 'connected' ? 'Conectado' : 'Desconectado'
          }
          valueColor={
            dbStatus === 'connected' ? T.accent.teal :
            dbStatus === 'disconnected' ? T.accent.red : T.text.tertiary
          }
        />
        <p style={{ color: T.text.tertiary, fontSize: '0.813rem', margin: `${T.space.sm} 0 0` }}>
          Contacta a tu ejecutivo de cuenta para modificar la conexion.
        </p>
      </Section>

      {/* Diagnosis frequency */}
      <Section title="Frecuencia de diagnostico">
        <div style={{ display: 'flex', gap: T.space.sm }}>
          {['weekly', 'monthly'].map((f) => (
            <button
              key={f}
              onClick={() => setFrequency(f)}
              style={{
                padding: `${T.space.sm} ${T.space.lg}`,
                borderRadius: T.radius.sm,
                border: frequency === f ? `1px solid ${T.accent.teal}` : T.border.card,
                backgroundColor: frequency === f ? T.bg.elevated : T.bg.card,
                color: frequency === f ? T.accent.teal : T.text.secondary,
                cursor: 'pointer',
                fontSize: '0.875rem',
                fontWeight: 500,
              }}
            >
              {f === 'weekly' ? 'Semanal' : 'Mensual'}
            </button>
          ))}
        </div>
      </Section>

      {/* Notifications */}
      <Section title="Notificaciones">
        <label style={{
          display: 'flex',
          alignItems: 'center',
          gap: T.space.md,
          cursor: 'pointer',
        }}>
          <input
            type="checkbox"
            checked={emailDigest}
            onChange={(e) => setEmailDigest(e.target.checked)}
            style={{ accentColor: T.accent.teal }}
          />
          <span style={{ color: T.text.secondary, fontSize: '0.875rem' }}>
            Recibir resumen por email cuando haya un nuevo diagnostico
          </span>
        </label>
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      backgroundColor: T.bg.card,
      borderRadius: T.radius.md,
      border: T.border.card,
      padding: T.space.lg,
      marginBottom: T.space.md,
    }}>
      <h3 style={{
        fontSize: '0.875rem',
        fontWeight: 600,
        color: T.text.primary,
        marginTop: 0,
        marginBottom: T.space.md,
      }}>
        {title}
      </h3>
      {children}
    </div>
  )
}

function Row({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      padding: `${T.space.xs} 0`,
    }}>
      <span style={{ color: T.text.tertiary, fontSize: '0.875rem' }}>{label}</span>
      <span style={{ color: valueColor || T.text.primary, fontSize: '0.875rem', fontWeight: 500 }}>
        {value}
      </span>
    </div>
  )
}
