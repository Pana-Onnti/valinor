'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Database, Zap, Shield, Clock, ArrowRight, Play, CheckCircle, CheckCircle2 } from 'lucide-react'
import { AnalysisForm } from '@/components/AnalysisForm'
import { AnalysisProgress } from '@/components/AnalysisProgress'
import { ResultsDisplay } from '@/components/ResultsDisplay'

export default function HomePage() {
  const [stage, setStage] = useState<'setup' | 'running' | 'complete'>('setup')
  const [analysisId, setAnalysisId] = useState<string | null>(null)
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

  const handleStartAnalysis = (id: string) => {
    setAnalysisId(id)
    setStage('running')
  }

  const handleAnalysisComplete = () => {
    setStage('complete')
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-blue-50 dark:from-gray-900 dark:via-gray-800 dark:to-indigo-900">
      {/* Header */}
      <header className="border-b border-gray-200 dark:border-gray-700 bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div className="flex items-center">
              <motion.div
                initial={{ rotate: 0 }}
                animate={{ rotate: 360 }}
                transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
                className="mr-3"
              >
                <Database className="h-8 w-8 text-indigo-600 dark:text-indigo-400" />
              </motion.div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                Valinor SaaS
              </h1>
            </div>
            <div className="flex items-center space-x-4">
              <span className="text-sm text-gray-600 dark:text-gray-400">
                Provider: {process.env.NEXT_PUBLIC_LLM_PROVIDER || 'Anthropic API'}
              </span>
              <button className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors">
                Settings
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        {stage === 'setup' && (
          <>
            {/* Smart homepage: returning user */}
            {recentClients.length > 0 && (
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-10"
              >
                {/* Welcome back header */}
                <div className="flex items-start justify-between mb-6 flex-wrap gap-4">
                  <div>
                    <p className="text-xs font-mono tracking-widest text-indigo-500 uppercase mb-1">Sistema activo</p>
                    <h2 className="text-3xl font-bold text-gray-900 dark:text-white">
                      {recentClients.length === 1
                        ? `Bienvenido de vuelta, ${recentClients[0].client_name.replace('_', ' ')}`
                        : `${recentClients.length} clientes monitoreados`
                      }
                    </h2>
                  </div>
                </div>

                {/* Client cards — larger when 1 client, grid when multiple */}
                <div className={`grid gap-4 mb-8 ${recentClients.length === 1 ? 'grid-cols-1 max-w-md' : 'grid-cols-2 md:grid-cols-3 lg:grid-cols-4'}`}>
                  {recentClients.slice(0, 8).map(client => (
                    <a
                      key={client.client_name}
                      href={`/clients/${encodeURIComponent(client.client_name)}/history`}
                      className="group bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-5 hover:border-indigo-400 dark:hover:border-indigo-500 hover:shadow-lg transition-all"
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-900/30 group-hover:bg-indigo-100 dark:group-hover:bg-indigo-900/50 transition-colors">
                          <Database className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
                        </div>
                        <span className="text-xs text-gray-400 font-mono">{client.run_count} runs</span>
                      </div>
                      <p className="font-bold text-gray-900 dark:text-white mb-1 truncate">
                        {client.client_name.replace(/_/g, ' ')}
                      </p>
                      <div className="flex items-center justify-between">
                        {client.known_findings_count > 0 ? (
                          <span className="text-xs font-medium text-orange-500 flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-orange-500 inline-block animate-pulse" />
                            {client.known_findings_count} activo{client.known_findings_count > 1 ? 's' : ''}
                          </span>
                        ) : (
                          <span className="text-xs text-emerald-500 flex items-center gap-1">
                            <CheckCircle2 className="h-3 w-3" />Sin alertas
                          </span>
                        )}
                        {client.last_run_date && (
                          <span className="text-xs text-gray-400">
                            {new Date(client.last_run_date).toLocaleDateString('es', { day: 'numeric', month: 'short' })}
                          </span>
                        )}
                      </div>
                    </a>
                  ))}
                </div>

                {/* Divider before form */}
                <div className="flex items-center gap-4 mb-8">
                  <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
                  <span className="text-xs text-gray-400 font-mono uppercase tracking-wider">Nuevo análisis</span>
                  <div className="flex-1 h-px bg-gray-200 dark:bg-gray-700" />
                </div>
              </motion.div>
            )}

            {/* Hero Section — only for new users */}
            {recentClients.length === 0 && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5 }}
                className="text-center mb-12"
              >
                <h2 className="text-5xl font-bold text-gray-900 dark:text-white mb-4">
                  Business Intelligence in{' '}
                  <span className="text-indigo-600 dark:text-indigo-400">15 Minutes</span>
                </h2>
                <p className="text-xl text-gray-600 dark:text-gray-400 max-w-3xl mx-auto">
                  Connect your database securely, let our AI agents analyze it, and receive
                  executive-ready insights without storing any of your data.
                </p>
              </motion.div>
            )}

            {/* Features Grid — only for new users */}
            {recentClients.length === 0 && (
              <div className="grid md:grid-cols-4 gap-6 mb-12">
                {[
                  {
                    icon: Shield,
                    title: 'Zero Data Storage',
                    description: 'Your data never leaves your servers'
                  },
                  {
                    icon: Clock,
                    title: '15 Min Analysis',
                    description: 'Complete insights in record time'
                  },
                  {
                    icon: Zap,
                    title: 'Multi-Agent AI',
                    description: 'Powered by Claude Opus & Sonnet'
                  },
                  {
                    icon: Database,
                    title: 'Any Database',
                    description: 'PostgreSQL, MySQL, SQL Server, Oracle'
                  }
                ].map((feature, index) => (
                  <motion.div
                    key={index}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5, delay: index * 0.1 }}
                    className="bg-white dark:bg-gray-800 p-6 rounded-xl shadow-lg"
                  >
                    <feature.icon className="h-8 w-8 text-indigo-600 dark:text-indigo-400 mb-3" />
                    <h3 className="font-semibold text-gray-900 dark:text-white mb-2">
                      {feature.title}
                    </h3>
                    <p className="text-sm text-gray-600 dark:text-gray-400">
                      {feature.description}
                    </p>
                  </motion.div>
                ))}
              </div>
            )}

            {/* Analysis Form */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.5, delay: 0.4 }}
            >
              <AnalysisForm onStartAnalysis={handleStartAnalysis} />
            </motion.div>
          </>
        )}

        {stage === 'running' && analysisId && (
          <AnalysisProgress
            analysisId={analysisId}
            onComplete={handleAnalysisComplete}
          />
        )}

        {stage === 'complete' && analysisId && (
          <ResultsDisplay
            analysisId={analysisId}
            onNewAnalysis={() => {
              setStage('setup')
              setAnalysisId(null)
            }}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="mt-auto border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex justify-between items-center">
            <p className="text-gray-600 dark:text-gray-400">
              © 2026 Delta 4C - Valinor SaaS v2.0
            </p>
            <div className="flex space-x-4">
              <a href="#" className="text-gray-600 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-400">
                Documentation
              </a>
              <a href="#" className="text-gray-600 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-400">
                API
              </a>
              <a href="#" className="text-gray-600 hover:text-indigo-600 dark:text-gray-400 dark:hover:text-indigo-400">
                Support
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  )
}
