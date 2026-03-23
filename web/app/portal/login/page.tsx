'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { T } from '@/components/d4c/tokens'
import { setAuth } from '@/lib/auth'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function PortalLoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [token, setToken] = useState('')
  const [mode, setMode] = useState<'email' | 'token'>('token')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleTokenLogin(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch(`${BASE_URL}/api/v1/portal/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token.trim() }),
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || 'Token inválido')
      }

      const data = await res.json()
      setAuth(data.token, data.client)
      router.push('/portal')
    } catch (err: any) {
      setError(err.message || 'Error al verificar token')
    } finally {
      setLoading(false)
    }
  }

  async function handleMagicLink(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch(`${BASE_URL}/api/v1/portal/magic-link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim() }),
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || 'Error al enviar link')
      }

      setError('')
      alert('Revisá tu email — te enviamos un link de acceso.')
    } catch (err: any) {
      setError(err.message || 'Error al enviar magic link')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: T.bg.primary,
      padding: T.space.lg,
    }}>
      <div style={{
        width: '100%',
        maxWidth: 420,
        backgroundColor: T.bg.card,
        borderRadius: T.radius.lg,
        border: T.border.card,
        padding: T.space.xxl,
      }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: T.space.xl }}>
          <h1 style={{
            fontSize: '1.75rem',
            fontWeight: 700,
            color: T.accent.teal,
            margin: 0,
          }}>
            Delta 4C
          </h1>
          <p style={{
            color: T.text.secondary,
            fontSize: '0.875rem',
            marginTop: T.space.sm,
          }}>
            Portal de Cliente
          </p>
        </div>

        {/* Tab toggle */}
        <div style={{
          display: 'flex',
          gap: T.space.xs,
          marginBottom: T.space.lg,
          backgroundColor: T.bg.primary,
          borderRadius: T.radius.sm,
          padding: '2px',
        }}>
          {(['token', 'email'] as const).map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); setError('') }}
              style={{
                flex: 1,
                padding: `${T.space.sm} ${T.space.md}`,
                border: 'none',
                borderRadius: T.radius.sm,
                backgroundColor: mode === m ? T.bg.elevated : 'transparent',
                color: mode === m ? T.text.primary : T.text.tertiary,
                cursor: 'pointer',
                fontSize: '0.875rem',
                fontWeight: 500,
                transition: 'all 0.2s',
              }}
            >
              {m === 'token' ? 'Token de acceso' : 'Magic link'}
            </button>
          ))}
        </div>

        {/* Forms */}
        {mode === 'token' ? (
          <form onSubmit={handleTokenLogin}>
            <label style={{ display: 'block', marginBottom: T.space.sm }}>
              <span style={{ color: T.text.secondary, fontSize: '0.875rem' }}>
                Token de acceso
              </span>
              <input
                type="text"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Pegá el token que te enviamos"
                className="d4c-input"
                style={{
                  width: '100%',
                  marginTop: T.space.xs,
                  boxSizing: 'border-box',
                }}
                required
              />
            </label>
            <button
              type="submit"
              disabled={loading || !token.trim()}
              className="d4c-btn-primary"
              style={{
                width: '100%',
                marginTop: T.space.lg,
                padding: `${T.space.sm} ${T.space.lg}`,
                opacity: loading ? 0.6 : 1,
              }}
            >
              {loading ? 'Verificando...' : 'Ingresar'}
            </button>
          </form>
        ) : (
          <form onSubmit={handleMagicLink}>
            <label style={{ display: 'block', marginBottom: T.space.sm }}>
              <span style={{ color: T.text.secondary, fontSize: '0.875rem' }}>
                Email
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="tu@empresa.com"
                className="d4c-input"
                style={{
                  width: '100%',
                  marginTop: T.space.xs,
                  boxSizing: 'border-box',
                }}
                required
              />
            </label>
            <button
              type="submit"
              disabled={loading || !email.trim()}
              className="d4c-btn-primary"
              style={{
                width: '100%',
                marginTop: T.space.lg,
                padding: `${T.space.sm} ${T.space.lg}`,
                opacity: loading ? 0.6 : 1,
              }}
            >
              {loading ? 'Enviando...' : 'Enviar link de acceso'}
            </button>
          </form>
        )}

        {error && (
          <p style={{
            color: T.accent.red,
            fontSize: '0.875rem',
            marginTop: T.space.md,
            textAlign: 'center',
          }}>
            {error}
          </p>
        )}

        <p style={{
          color: T.text.tertiary,
          fontSize: '0.75rem',
          textAlign: 'center',
          marginTop: T.space.xl,
        }}>
          Contactá a tu ejecutivo de cuenta si no tenés acceso.
        </p>
      </div>
    </div>
  )
}
