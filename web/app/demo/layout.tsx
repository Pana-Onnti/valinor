import { T } from '@/components/d4c/tokens'

export const metadata = {
  title: 'Demo — Delta 4C Valinor',
  description: 'Descubri lo que esconde tu base de datos. Analisis automatizado con IA.',
  openGraph: {
    title: 'Delta 4C — Analisis ejecutivo automatizado',
    description: 'Mira lo que encontramos en la base de datos de Gloria Distribuciones. Sin instalar nada.',
    type: 'website',
    siteName: 'Delta 4C',
  },
}

export default function DemoLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column' as const,
        backgroundColor: T.bg.primary,
      }}
    >
      {/* ── Header ──────────────────────────────────────────────────── */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: `${T.space.md} ${T.space.lg}`,
          borderBottom: T.border.subtle,
          backgroundColor: T.bg.card,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: `linear-gradient(135deg, ${T.accent.teal}, ${T.accent.blue})`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 16,
              fontWeight: 700,
              color: T.text.inverse,
            }}
          >
            4C
          </div>
          <span
            style={{
              fontFamily: T.font.display,
              fontSize: 18,
              fontWeight: 600,
              color: T.text.primary,
              letterSpacing: '-0.02em',
            }}
          >
            Delta 4C
          </span>
          <span
            style={{
              fontSize: 12,
              color: T.accent.teal,
              border: `1px solid ${T.accent.teal}40`,
              borderRadius: T.radius.sm,
              padding: `2px ${T.space.sm}`,
              marginLeft: T.space.xs,
            }}
          >
            DEMO
          </span>
        </div>
      </header>

      {/* ── Main ────────────────────────────────────────────────────── */}
      <main style={{ flex: 1 }}>{children}</main>

      {/* ── Footer ──────────────────────────────────────────────────── */}
      <footer
        style={{
          textAlign: 'center' as const,
          padding: `${T.space.lg} ${T.space.md}`,
          borderTop: T.border.subtle,
          backgroundColor: T.bg.card,
        }}
      >
        <p
          style={{
            fontSize: 13,
            color: T.text.tertiary,
            margin: 0,
          }}
        >
          Powered by{' '}
          <span style={{ color: T.accent.teal, fontWeight: 600 }}>
            Delta 4C
          </span>{' '}
          — Inteligencia ejecutiva sobre tus datos
        </p>
      </footer>
    </div>
  )
}
