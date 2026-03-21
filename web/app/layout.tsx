import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { Suspense } from 'react'
import './globals.css'
import { Providers } from './providers'
import ConnectionStatusBadge from '@/components/ConnectionStatusBadge'
import ErrorBoundary from '@/components/ErrorBoundary'
import Sidebar from '@/components/Sidebar'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Valinor SaaS - Business Intelligence Platform',
  description: 'Transform your database into executive insights in 15 minutes',
  icons: {
    icon: '/favicon.ico',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.className} h-full bg-gray-50 dark:bg-gray-900`}>
        <ErrorBoundary>
          <Suspense fallback={<div className="min-h-screen bg-gray-950 animate-pulse"/>}>
            <Providers>
              <div className="flex min-h-screen">
                <Sidebar />
                <main className="flex-1 overflow-auto">
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