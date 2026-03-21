'use client'

import { useRouter } from 'next/navigation'
import { KOReportLoader } from '@/components/ko-report/KOReportLoader'

export default function ResultsPage({ params }: { params: { jobId: string } }) {
  const router = useRouter()

  return (
    <KOReportLoader
      jobId={params.jobId}
      onNewAnalysis={() => router.push('/')}
    />
  )
}
