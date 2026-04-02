'use client'

import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { T, SEV_COLOR, SEV_LABEL } from '@/components/d4c/tokens'
import { DEMO_FINDINGS, DEMO_STATS, LOADING_STEPS, type DemoFinding } from '@/lib/demo-data'

// ── Loading sequence ────────────────────────────────────────────────────────

function LoadingSequence({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState(0)

  useEffect(() => {
    if (step >= LOADING_STEPS.length) {
      const t = setTimeout(onComplete, 400)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setStep((s) => s + 1), LOADING_STEPS[step].duration)
    return () => clearTimeout(t)
  }, [step, onComplete])

  return (
    <div
      style={{
        minHeight: '80vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: T.space.lg,
        padding: T.space.lg,
      }}
    >
      {/* Pulse ring */}
      <motion.div
        animate={{ scale: [1, 1.2, 1], opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 1.5, repeat: Infinity }}
        style={{
          width: 80,
          height: 80,
          borderRadius: '50%',
          border: `3px solid ${T.accent.teal}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 28,
          fontWeight: 700,
          color: T.accent.teal,
        }}
      >
        4C
      </motion.div>

      {/* Steps */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: T.space.sm,
          minWidth: 280,
        }}
      >
        {LOADING_STEPS.map((s, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, x: -20 }}
            animate={i <= step ? { opacity: 1, x: 0 } : {}}
            transition={{ duration: 0.3 }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: T.space.sm,
              fontSize: 14,
              fontFamily: T.font.mono,
              color: i < step ? T.accent.teal : i === step ? T.text.primary : T.text.tertiary,
            }}
          >
            <span style={{ width: 18, textAlign: 'center' }}>
              {i < step ? '\u2713' : i === step ? '\u25CF' : '\u25CB'}
            </span>
            {s.text}
          </motion.div>
        ))}
      </div>
    </div>
  )
}

// ── Severity Badge ──────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const color = SEV_COLOR[severity] || T.accent.blue
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        padding: `3px ${T.space.sm}`,
        borderRadius: T.radius.sm,
        backgroundColor: `${color}20`,
        color: color,
        border: `1px solid ${color}40`,
        whiteSpace: 'nowrap',
      }}
    >
      {SEV_LABEL[severity] || severity}
    </span>
  )
}

// ── Finding Card ────────────────────────────────────────────────────────────

function FindingCard({ finding, index, isHero }: { finding: DemoFinding; index: number; isHero?: boolean }) {
  const color = SEV_COLOR[finding.severity] || T.accent.blue

  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.1 }}
      style={{
        backgroundColor: T.bg.card,
        border: isHero ? `2px solid ${color}60` : T.border.card,
        borderRadius: T.radius.md,
        padding: isHero ? T.space.lg : T.space.md,
        display: 'flex',
        flexDirection: 'column',
        gap: T.space.sm,
        ...(isHero && {
          gridColumn: '1 / -1',
          background: `linear-gradient(135deg, ${T.bg.card}, ${color}08)`,
        }),
      }}
    >
      {/* Top row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: T.space.sm,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: T.space.sm }}>
          <SeverityBadge severity={finding.severity} />
          <span style={{ fontSize: 12, color: T.text.tertiary }}>{finding.category}</span>
        </div>
        <span
          style={{
            fontSize: isHero ? 24 : 18,
            fontWeight: 700,
            fontFamily: T.font.mono,
            color: color,
          }}
        >
          EUR {finding.eurValue.toLocaleString('es-AR')}
        </span>
      </div>

      {/* Headline */}
      <h3
        style={{
          margin: 0,
          fontSize: isHero ? 20 : 16,
          fontWeight: 600,
          color: T.text.primary,
          lineHeight: 1.3,
        }}
      >
        {finding.icon} {finding.headline}
      </h3>

      {/* Description */}
      <p
        style={{
          margin: 0,
          fontSize: 14,
          color: T.text.secondary,
          lineHeight: 1.6,
        }}
      >
        {finding.description}
      </p>

      {/* Action */}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: T.space.sm,
          marginTop: T.space.xs,
          padding: T.space.sm,
          backgroundColor: `${T.accent.teal}10`,
          borderRadius: T.radius.sm,
          border: `1px solid ${T.accent.teal}20`,
        }}
      >
        <span style={{ fontSize: 14, color: T.accent.teal, flexShrink: 0 }}>{'\u2192'}</span>
        <span style={{ fontSize: 13, color: T.accent.teal, lineHeight: 1.4 }}>
          {finding.action}
        </span>
      </div>
    </motion.div>
  )
}

// ── Stats Bar ───────────────────────────────────────────────────────────────

function StatsBar() {
  const stats = [
    { label: 'Entidades analizadas', value: DEMO_STATS.entitiesFound.toString() },
    { label: 'Patrones detectados', value: DEMO_STATS.patternsDetected.toString() },
    { label: 'Valor en riesgo', value: `EUR ${DEMO_STATS.riskValue.toLocaleString('es-AR')}` },
    { label: 'Tiempo de analisis', value: DEMO_STATS.analysisTime },
  ]

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
        gap: T.space.md,
        padding: T.space.md,
        backgroundColor: T.bg.card,
        borderRadius: T.radius.md,
        border: T.border.card,
      }}
    >
      {stats.map((s, i) => (
        <div key={i} style={{ textAlign: 'center' }}>
          <div
            style={{
              fontSize: 22,
              fontWeight: 700,
              fontFamily: T.font.mono,
              color: T.accent.teal,
            }}
          >
            {s.value}
          </div>
          <div style={{ fontSize: 12, color: T.text.tertiary, marginTop: 4 }}>{s.label}</div>
        </div>
      ))}
    </motion.div>
  )
}

// ── Copy Link Button ────────────────────────────────────────────────────────

function CopyLinkButton() {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback for older browsers
      const input = document.createElement('input')
      input.value = window.location.href
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <button
      onClick={handleCopy}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: T.space.xs,
        padding: `${T.space.sm} ${T.space.md}`,
        backgroundColor: 'transparent',
        color: T.text.secondary,
        fontSize: 13,
        fontFamily: T.font.mono,
        border: `1px solid ${T.text.tertiary}40`,
        borderRadius: T.radius.sm,
        cursor: 'pointer',
        transition: 'all 150ms',
      }}
    >
      {copied ? '\u2713 Link copiado' : '\u{1F517} Copiar link'}
    </button>
  )
}

// ── CTA Section ─────────────────────────────────────────────────────────────

function CTASection() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.8 }}
      style={{
        textAlign: 'center',
        padding: `${T.space.xxl} ${T.space.lg}`,
        backgroundColor: T.bg.card,
        borderRadius: T.radius.lg,
        border: `2px solid ${T.accent.teal}30`,
        background: `linear-gradient(135deg, ${T.bg.card}, ${T.accent.teal}08)`,
      }}
    >
      <h2
        style={{
          margin: 0,
          fontSize: 24,
          fontWeight: 700,
          color: T.text.primary,
          lineHeight: 1.3,
        }}
      >
        Queres saber que esconde
        <br />
        <span style={{ color: T.accent.teal }}>tu base de datos?</span>
      </h2>
      <p
        style={{
          margin: `${T.space.md} auto 0`,
          fontSize: 15,
          color: T.text.secondary,
          maxWidth: 480,
          lineHeight: 1.6,
        }}
      >
        En 15 minutos conectamos tus datos y generamos un analisis ejecutivo completo.
        Sin instalar nada. Sin compromisos.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: T.space.md, marginTop: T.space.lg }}>
        <a
          href="https://wa.me/5491155887741?text=Hola%2C%20vi%20el%20demo%20de%20Delta%204C%20y%20quiero%20saber%20m%C3%A1s"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-block',
            padding: `${T.space.md} ${T.space.xl}`,
            backgroundColor: T.accent.teal,
            color: T.text.inverse,
            fontSize: 16,
            fontWeight: 700,
            borderRadius: T.radius.md,
            textDecoration: 'none',
            transition: 'transform 150ms, box-shadow 150ms',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.transform = 'translateY(-2px)'
            e.currentTarget.style.boxShadow = `0 8px 24px ${T.accent.teal}40`
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.transform = 'translateY(0)'
            e.currentTarget.style.boxShadow = 'none'
          }}
        >
          Contactar por WhatsApp
        </a>
        <CopyLinkButton />
      </div>
      <p style={{ margin: `${T.space.md} 0 0`, fontSize: 12, color: T.text.tertiary }}>
        O escribinos a{' '}
        <a href="mailto:lorenzo@delta4c.com" style={{ color: T.accent.teal, textDecoration: 'none' }}>
          lorenzo@delta4c.com
        </a>
      </p>
    </motion.div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────────

export default function DemoPage() {
  const [loaded, setLoaded] = useState(false)

  return (
    <div
      style={{
        maxWidth: 860,
        margin: '0 auto',
        padding: `${T.space.lg} ${T.space.md}`,
      }}
    >
      <AnimatePresence mode="wait">
        {!loaded ? (
          <motion.div key="loading" exit={{ opacity: 0 }} transition={{ duration: 0.3 }}>
            <LoadingSequence onComplete={() => setLoaded(true)} />
          </motion.div>
        ) : (
          <motion.div
            key="dashboard"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5 }}
            style={{ display: 'flex', flexDirection: 'column', gap: T.space.lg }}
          >
            {/* Title */}
            <div style={{ textAlign: 'center', marginBottom: T.space.sm }}>
              <h1
                style={{
                  margin: 0,
                  fontSize: 28,
                  fontWeight: 700,
                  color: T.text.primary,
                }}
              >
                Analisis ejecutivo{' '}
                <span style={{ color: T.accent.teal }}>Gloria Distribuciones</span>
              </h1>
              <p
                style={{
                  margin: `${T.space.sm} 0 0`,
                  fontSize: 14,
                  color: T.text.tertiary,
                }}
              >
                Generado automaticamente por los agentes Delta 4C
              </p>
            </div>

            {/* Stats */}
            <StatsBar />

            {/* Findings Grid */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                gap: T.space.md,
              }}
            >
              {DEMO_FINDINGS.map((f, i) => (
                <FindingCard key={f.id} finding={f} index={i} isHero={i === 0} />
              ))}
            </div>

            {/* CTA */}
            <CTASection />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
