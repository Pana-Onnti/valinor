'use client'

import { ResultsDisplay } from '@/components/ResultsDisplay'
import { useRouter } from 'next/navigation'

export default function ResultsPage({ params }: { params: { jobId: string } }) {
  const router = useRouter()

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800 p-6">
      <ResultsDisplay
        analysisId={params.jobId}
        onNewAnalysis={() => router.push('/')}
      />
    </main>
  )
}
