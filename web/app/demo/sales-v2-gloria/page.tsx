'use client'

/**
 * Demo route — SalesReportV2 con datos REALES de Gloria.
 *
 * Lee el JSON generado por scripts/generate_sales_report_v2_gloria.py que
 * corre las 5 queries sales_v2 contra Gloria Postgres y arma el payload
 * determinísticamente (sin LLM).
 *
 * Para refrescar los datos:
 *   $ python3 scripts/generate_sales_report_v2_gloria.py
 *
 * Refs: VAL-141
 */

import { useEffect, useState } from 'react'
import SalesReportV2, {
  parseSalesReportV2,
  type SalesReportV2Data,
} from '@/components/ko-report/SalesReportV2'
import { T } from '@/components/d4c/tokens'

export default function SalesV2GloriaDemoPage() {
  const [report, setReport] = useState<SalesReportV2Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/demo/sales-v2-gloria.json', { cache: 'no-store' })
      .then((r) => r.text())
      .then((raw) => {
        const parsed = parseSalesReportV2(raw)
        if (!parsed) setError('JSON inválido o schema no coincide.')
        else setReport(parsed)
      })
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <div style={{ background: T.bg.primary, minHeight: '100vh' }}>
      <div style={{
        maxWidth: 1100, margin: '0 auto',
        fontFamily: T.font.display,
      }}>
        {error && (
          <div style={{
            padding: T.space.lg, margin: T.space.lg,
            background: `${T.accent.red}10`, border: `1px solid ${T.accent.red}33`,
            borderRadius: T.radius.md, color: T.accent.red,
          }}>
            Error cargando datos reales de Gloria: {error}
            <br/>
            <span style={{ fontSize: 11, opacity: 0.8 }}>
              Ejecutar: <code>python3 scripts/generate_sales_report_v2_gloria.py</code>
            </span>
          </div>
        )}
        {!report && !error && (
          <div style={{
            padding: T.space.xl, color: T.text.tertiary,
            fontFamily: T.font.mono, fontSize: 12,
          }}>
            Cargando datos reales de Gloria…
          </div>
        )}
        {report && <SalesReportV2 report={report} />}
      </div>
    </div>
  )
}
