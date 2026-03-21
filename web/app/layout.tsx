import type { Metadata } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import { Suspense } from 'react'
import './globals.css'
import { Providers } from './providers'
import ConnectionStatusBadge from '@/components/ConnectionStatusBadge'
import ErrorBoundary from '@/components/ErrorBoundary'
import Sidebar from '@/components/Sidebar'
import { T } from '@/components/d4c/tokens'

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' })
const mono  = JetBrains_Mono({ subsets: ['latin'], variable: '--font-mono', weight: ['400', '600'] })

export const metadata: Metadata = {
  title: 'Valinor — Delta 4C',
  description: 'Transform your database into executive insights in 15 minutes',
  icons: { icon: '/favicon.ico' },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${inter.variable} ${mono.variable}`} style={{ height: '100%' }}>
      <body
        style={{
          fontFamily: T.font.display,
          backgroundColor: T.bg.primary,
          color: T.text.primary,
          margin: 0,
          height: '100%',
        }}
      >
        <ErrorBoundary>
          <Suspense fallback={<div style={{ minHeight: '100vh', backgroundColor: T.bg.primary }} />}>
            <Providers>
              <div style={{ display: 'flex', minHeight: '100vh' }}>
                <Sidebar />
                <main style={{ flex: 1, overflowY: 'auto' }}>
                  {children}
                </main>
              </div>
            </Providers>
          </Suspense>
        </ErrorBoundary>
        <ConnectionStatusBadge />
      </body>
    </html>
  )
}