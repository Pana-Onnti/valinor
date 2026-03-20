/**
 * reportParser.ts
 * Parses the raw markdown executive report into structured data
 * so we can render it with custom JSX instead of raw markdown.
 */

export interface KPI {
  label: string
  value: string
  confidence: 'MEASURED' | 'ESTIMATED' | 'INFERRED'
}

export interface Finding {
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
  id: string
  title: string
  body: string          // plain text, markdown stripped
  bullets: string[]     // extracted bullet points
  sql?: string
}

export interface ContradictionRow {
  contradiction: string
  explanation: string
}

export interface ActionRow {
  num: string
  action: string
  owner: string
  deadline: string
}

export interface ReportSection {
  title: string
  body: string          // plain text, markdown stripped
}

export interface ParsedReport {
  clientName: string
  analysisDate: string
  dataThrough: string
  currency: string
  caveat?: string
  kpis: KPI[]
  findings: Finding[]
  contradictions: ContradictionRow[]
  actions: ActionRow[]
  sections: ReportSection[]
  raw: string
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Strip all common markdown syntax, returning plain text. */
export function stripMd(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '')          // fenced code blocks
    .replace(/`([^`]+)`/g, '$1')             // inline code
    .replace(/\*\*\*(.+?)\*\*\*/g, '$1')    // bold+italic
    .replace(/\*\*(.+?)\*\*/g, '$1')         // bold
    .replace(/\*(.+?)\*/g, '$1')             // italic
    .replace(/~~(.+?)~~/g, '$1')             // strikethrough
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // links
    .replace(/^#{1,6}\s+/gm, '')             // headers
    .replace(/^[>\s]+/gm, '')                // blockquotes / leading >
    .replace(/^[-*+]\s+/gm, '')              // unordered bullets
    .replace(/^\d+\.\s+/gm, '')              // ordered bullets
    .replace(/\|/g, ' ')                     // table pipes
    .replace(/^[-:]+$/gm, '')                // table separator rows
    .replace(/[ \t]{2,}/g, ' ')              // multiple spaces
    .replace(/\n{3,}/g, '\n\n')              // triple+ newlines
    .trim()
}

function confidenceFrom(raw: string): KPI['confidence'] {
  const u = raw.toUpperCase()
  if (u.includes('MEDIDO') || u.includes('MEASURED')) return 'MEASURED'
  if (u.includes('ESTIMADO') || u.includes('ESTIMATED')) return 'ESTIMATED'
  return 'INFERRED'
}

function severityFrom(line: string): Finding['severity'] {
  if (/🔴|CRITICAL/i.test(line)) return 'CRITICAL'
  if (/🟠|HIGH/i.test(line)) return 'HIGH'
  if (/🟡|MEDIUM|WARN/i.test(line)) return 'MEDIUM'
  if (/🟢|LOW/i.test(line)) return 'LOW'
  return 'INFO'
}

/** Parse a markdown table into rows (skipping header and separator). */
function parseTable(lines: string[]): string[][] {
  const rows: string[][] = []
  for (const line of lines) {
    if (!line.trim().startsWith('|')) continue
    // skip separator rows like |---|---|
    if (/^\|[\s\-:|]+\|/.test(line)) continue
    const cells = line
      .split('|')
      .slice(1, -1)
      .map(c => stripMd(c.trim()))
    if (cells.length > 0 && cells.some(c => c)) rows.push(cells)
  }
  return rows
}

/** Extract bullet lines from a body string. */
function extractBullets(body: string): string[] {
  return body
    .split('\n')
    .filter(l => /^[-*•]\s+/.test(l.trim()))
    .map(l => stripMd(l.replace(/^[-*•]\s+/, '')))
    .filter(Boolean)
}

// ── Main parser ───────────────────────────────────────────────────────────────

export function parseReport(raw: string): ParsedReport {
  const lines = raw.split('\n')

  // Client name from first H1
  const h1 = lines.find(l => l.startsWith('# '))
  const clientName = h1
    ?.replace(/^#\s*/, '')
    .replace(/^Executive Summary\s*[—–-]\s*/i, '')
    .trim() ?? 'Cliente'

  // Date metadata line
  const dateLine = lines.find(l => /Analysis Date/i.test(l)) ?? ''
  const analysisDate = dateLine.match(/Analysis Date[:\s]+([^|]+)/i)?.[1]?.trim() ?? ''
  const dataThrough  = dateLine.match(/Data Through[:\s]+([^|]+)/i)?.[1]?.trim() ?? ''
  const currency     = dateLine.match(/Currency[:\s]+(\w+)/i)?.[1]?.trim() ?? 'EUR'

  // Caveat blockquote (⚠️ lines or > lines near top)
  const caveatLine = lines.find(l => /⚠️|⚠|Critical caveat|Nota crítica|Advertencia/i.test(l))
  const caveat = caveatLine
    ? stripMd(caveatLine.replace(/^[>*_⚠️\s]+/, '').trim())
    : undefined

  // ── KPIs — from markdown table rows with [MEASURED]/[MEDIDO] etc. ────────
  const kpis: KPI[] = []
  const tableRowRe = /^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\[.+?\])\s*\|/
  for (const line of lines) {
    const m = line.match(tableRowRe)
    if (!m) continue
    const label = m[1].replace(/\*\*/g, '').trim()
    const value = m[2].replace(/\*\*/g, '').trim()
    const flag  = m[3].trim()
    if (/metric|label|---|Metric/i.test(label)) continue
    kpis.push({ label, value, confidence: confidenceFrom(flag) })
  }

  // ── Findings — sections starting with 🔴/🟡/🟢 SEVERITY-N — Title ──────
  const findings: Finding[] = []
  const findingHeaderRe = /^#{1,3}\s*(🔴|🟠|🟡|🟢|CRITICAL|HIGH|MEDIUM|LOW)[^—–-]*[—–-]+?\s*(.+)/
  let currentFinding: Finding | null = null
  let findingBuffer: string[] = []
  let sqlBuffer: string[] = []
  let inSqlBlock = false

  const flushFinding = () => {
    if (!currentFinding) return
    const sql = sqlBuffer.join('\n').trim() || undefined
    const rawBody = findingBuffer.join('\n').trim()
    currentFinding.body = stripMd(rawBody)
    currentFinding.bullets = extractBullets(rawBody)
    if (sql) currentFinding.sql = sql
    findings.push(currentFinding)
    currentFinding = null
    findingBuffer = []
    sqlBuffer = []
    inSqlBlock = false
  }

  for (const line of lines) {
    if (line.startsWith('```sql') || line.startsWith('```SQL')) { inSqlBlock = true; continue }
    if (line.startsWith('```') && inSqlBlock) { inSqlBlock = false; continue }
    if (inSqlBlock) { sqlBuffer.push(line); continue }

    const fMatch = line.match(findingHeaderRe)
    if (fMatch) {
      flushFinding()
      const severity = severityFrom(fMatch[1])
      const rawTitle = fMatch[2].trim()
      const idMatch = rawTitle.match(/^([\w-]+-\d+)\s*[—–-]?\s*(.*)$/)
      currentFinding = {
        severity,
        id: idMatch?.[1] ?? `F${findings.length + 1}`,
        title: stripMd((idMatch?.[2] ?? rawTitle).trim()),
        body: '',
        bullets: [],
      }
      continue
    }
    if (currentFinding) {
      findingBuffer.push(line)
    }
  }
  flushFinding()

  // ── Collect h2 sections by title ─────────────────────────────────────────
  const sectionMap: Record<string, string[]> = {}
  let curTitle = ''
  for (const line of lines) {
    if (/^## /.test(line)) {
      curTitle = line.replace(/^## /, '').trim()
      sectionMap[curTitle] = []
    } else if (curTitle) {
      sectionMap[curTitle].push(line)
    }
  }

  // ── Contradictions table ─────────────────────────────────────────────────
  const contradictions: ContradictionRow[] = []
  const contrTitle = Object.keys(sectionMap).find(k => /contradict|reconcili/i.test(k))
  if (contrTitle) {
    const rows = parseTable(sectionMap[contrTitle])
    // first row is header — skip if it looks like "Contradiction | Explanation"
    for (const row of rows) {
      if (row.length >= 2 && !/^(contradicti|reconcili|contradicción)/i.test(row[0])) {
        contradictions.push({ contradiction: row[0], explanation: row[1] ?? '' })
      }
    }
  }

  // ── Actions table ────────────────────────────────────────────────────────
  const actions: ActionRow[] = []
  const actTitle = Object.keys(sectionMap).find(k => /action|accion|acciones/i.test(k))
  if (actTitle) {
    const rows = parseTable(sectionMap[actTitle])
    for (const row of rows) {
      if (row.length >= 2 && !/^(#|num|action|acción)/i.test(row[0])) {
        actions.push({
          num: row[0] ?? '',
          action: row[1] ?? '',
          owner: row[2] ?? '',
          deadline: row[3] ?? '',
        })
      }
    }
  }

  // ── Other sections (limitations, etc.) ───────────────────────────────────
  const sections: ReportSection[] = []
  const skipPatterns = /Numbers That Matter|Cifras Clave|Findings|Hallazgos|Executive Summary|Resumen|contradict|reconcili|action|accion/i

  for (const [title, bodyLines] of Object.entries(sectionMap)) {
    if (skipPatterns.test(title)) continue
    const body = bodyLines
      .filter(l => l.trim() && !/^[-:|\s]*$/.test(l))
      .map(l => stripMd(l))
      .filter(Boolean)
      .join('\n')
      .trim()
    if (body) sections.push({ title, body })
  }

  return { clientName, analysisDate, dataThrough, currency, caveat, kpis, findings, contradictions, actions, sections, raw }
}
