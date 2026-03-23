'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { T } from '@/components/d4c/tokens'
import { getAuthState, clearAuth, type PortalClient } from '@/lib/auth'

/** Routes that don't require authentication */
const PUBLIC_ROUTES = ['/portal/login']

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [client, setClient] = useState<PortalClient | null>(null)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    const { isAuthenticated, client: c } = getAuthState()

    if (!isAuthenticated && !PUBLIC_ROUTES.includes(pathname)) {
      router.replace('/portal/login')
      return
    }

    setClient(c)
    setChecked(true)
  }, [pathname, router])

  // Public routes render without chrome
  if (PUBLIC_ROUTES.includes(pathname)) {
    return <>{children}</>
  }

  // Wait for auth check
  if (!checked) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: T.bg.primary,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{ color: T.text.tertiary }}>Cargando...</div>
      </div>
    )
  }

  function handleLogout() {
    clearAuth()
    router.replace('/portal/login')
  }

  return (
    <div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }}>
      {/* Header */}
      <header style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: `${T.space.md} ${T.space.xl}`,
        borderBottom: T.border.subtle,
        backgroundColor: T.bg.card,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: T.space.lg }}>
          <span
            onClick={() => router.push('/portal')}
            style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              color: T.accent.teal,
              cursor: 'pointer',
            }}
          >
            Delta 4C
          </span>

          <nav style={{ display: 'flex', gap: T.space.md }}>
            {[
              { href: '/portal', label: 'Dashboard' },
              { href: '/portal/reports', label: 'Reportes' },
              { href: '/portal/settings', label: 'Configuracion' },
            ].map(({ href, label }) => (
              <a
                key={href}
                onClick={() => router.push(href)}
                style={{
                  color: pathname === href ? T.text.primary : T.text.secondary,
                  fontSize: '0.875rem',
                  fontWeight: pathname === href ? 600 : 400,
                  cursor: 'pointer',
                  textDecoration: 'none',
                  borderBottom: pathname === href ? `2px solid ${T.accent.teal}` : '2px solid transparent',
                  paddingBottom: T.space.xs,
                  transition: 'all 0.2s',
                }}
              >
                {label}
              </a>
            ))}
          </nav>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: T.space.md }}>
          {client && (
            <span style={{ color: T.text.secondary, fontSize: '0.875rem' }}>
              {client.name}
            </span>
          )}
          <button
            onClick={handleLogout}
            className="d4c-btn-ghost"
            style={{ fontSize: '0.813rem', padding: `${T.space.xs} ${T.space.md}` }}
          >
            Salir
          </button>
        </div>
      </header>

      {/* Content */}
      <main style={{ padding: T.space.xl, maxWidth: 1200, margin: '0 auto' }}>
        {children}
      </main>
    </div>
  )
}
