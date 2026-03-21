---
name: d4c-brand
description: Delta 4C brand design system. Use this skill whenever creating ANY visual output for Delta 4C — React artifacts, HTML reports, dashboards, presentations, PDFs, or UI components. Also use when the user mentions KO report, Valinor report, Narzil report, demo mode, client portal, operator dashboard, or any Delta 4C branded deliverable. Triggers on any request involving D4C visual identity, design tokens, component styling, or brand consistency. Always use this skill BEFORE the frontend-design skill when both are relevant — this skill provides the brand constraints that frontend-design executes.
---

# Delta 4C — Brand Design System

This skill ensures every visual artifact produced for Delta 4C is brand-consistent with [delta4c.com](https://delta4c.com). The goal: a prospect should not be able to tell where the website ends and the product begins.

## When to Use

- Creating or editing React artifacts (.jsx) for D4C
- Generating HTML reports (KO Reports, SEO audits, diagnostics)
- Building dashboards (client portal, operator, YC metrics)
- Designing UI flows (onboarding wizard, demo mode)
- Any visual output branded as Delta 4C, Valinor, or Narzil

## Design Philosophy

Delta 4C's visual language communicates three things:

1. **Seriousness** — We handle real business data. The design must feel like a financial terminal, not a SaaS toy.
2. **Urgency** — KO Reports provoke decisions. Loss framing, red accents on critical numbers, action-oriented copy.
3. **Simplicity** — PyME owners are not designers. Information hierarchy must be ruthlessly clear.

**The reference is delta4c.com.** Dark void backgrounds, teal primary accent, numbered stepped sections, card-based layouts, monospace for data, Inter for prose.

## Quick Start

For any D4C artifact, begin with this CSS foundation:

```css
:root {
  /* Backgrounds — 3-level hierarchy */
  --bg-primary: #0A0A0F;      /* base layer — deep void */
  --bg-card: #111116;          /* card surface */
  --bg-elevated: #1A1A22;      /* hover, tooltips, nested elements */
  --bg-hover: #222230;         /* active/pressed state */
  
  /* Text — 3-level hierarchy */
  --text-primary: #F0F0F5;     /* headings, hero numbers */
  --text-secondary: #8A8A9A;   /* body text, descriptions */
  --text-tertiary: #5A5A6A;    /* labels, captions, metadata */
  --text-inverse: #0A0A0F;     /* text on light/accent backgrounds */
  
  /* Accents — semantic colors */
  --accent-teal: #2A9D8F;      /* Valinor brand, success, primary CTA */
  --accent-red: #E63946;       /* CRITICAL severity, loss framing, danger */
  --accent-yellow: #E9C46A;    /* WARNING severity, secondary highlights */
  --accent-orange: #F4845F;    /* MEDIUM severity */
  --accent-blue: #85B7EB;      /* INFO, neutral data, secondary actions */
  --accent-purple: #9B5DE5;    /* dev/internal, epics */
  
  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 48px;
  
  /* Radius */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  
  /* Typography */
  --font-display: 'Inter', 'DM Sans', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace;
  
  /* Borders */
  --border-subtle: 1px solid #1A1A22;
  --border-card: 1px solid #222230;
}
```

## Typography Rules

| Element | Font | Weight | Size | Color |
|---------|------|--------|------|-------|
| Page title | display | 700 | 20-24px | text-primary |
| Section header | display | 700 | 15-18px | text-primary |
| Body text | display | 400 | 13-14px | text-secondary |
| Labels, captions | mono | 400-500 | 10-11px | text-tertiary |
| Section number (01, 02) | mono | 700 | 28-32px | accent-teal @ 30% opacity |
| Hero numbers | mono | 700 | 28-36px | severity color |
| Data in tables | mono | 400 | 12-13px | text-primary |
| Status badges | mono | 600 | 10px | severity color |
| Metadata/provenance | mono | 400 | 10px | text-tertiary |

**Rule: ALL numbers use `font-mono`.** Revenue, percentages, counts, dates, IDs — everything numeric is monospace. No exceptions.

## Layout Rules

- **Max width**: 960-1200px centered
- **Card padding**: 16-24px
- **Card gap**: 10-16px
- **Background hierarchy**: primary → card → elevated (never skip levels)
- **Severity border**: 3px left border on cards, color = severity
- **Section headers**: numbered steps (01, 02, 03...) in large faded mono + title + description — matching delta4c.com "El Proceso" section

## Component Reference

For detailed component specs and React code, read `references/components.md`.

## Color Usage — Severity Mapping

```
CRITICAL  → accent-red (#E63946)    — immediate action required
WARNING   → accent-yellow (#E9C46A) — attention needed
MEDIUM    → accent-orange (#F4845F) — monitor closely
INFO      → accent-blue (#85B7EB)   — informational
OK/SUCCESS→ accent-teal (#2A9D8F)   — healthy, target met
INTERNAL  → accent-purple (#9B5DE5) — dev-only, not client-facing
```

Use at 20% opacity (`color + "20"`) for badge backgrounds. Use at 100% for text and borders.

## KO Report — Special Rules

The KO Report is the primary product output. Additional rules:

1. **Minto Pyramid structure**: Conclusion first → Evidence → Action
2. **Loss framing on hero numbers**: "Estás perdiendo $X/mes" NOT "Podrías ganar $X"
3. **Hero numbers above the fold**: The 3-4 most impactful numbers must be visible without scrolling
4. **Provenance on every finding**: Source table + query hash in monospace at the bottom
5. **Expandable findings**: Severity badge → Hero number → Headline → (expandable: evidence + action)
6. **Charts**: Dark background, D4C palette only, no gridlines, minimal axis labels in mono

## Anti-Patterns — Things to NEVER Do

- ❌ Colors outside the palette (no random blues, greens, or grays)
- ❌ Inter weight 300 (too thin for dark backgrounds)
- ❌ Borders thicker than 1px (except the 3px severity left-border on cards)
- ❌ Gradients (except teal→blue on primary CTAs)
- ❌ Emojis in report headings (use ⬥ ◈ ◎ ▸ for iconography)
- ❌ White backgrounds (always dark — even print mode should be dark unless explicitly requested)
- ❌ Generic chart colors (always use the D4C accent palette)
- ❌ Lorem ipsum or placeholder data (always use realistic Argentine business data)
- ❌ "Podrías ganar" framing (always "Estás perdiendo")
- ❌ Informational tone (always decision-provoking)

## Recharts Theme

When using recharts in React artifacts:

```jsx
const CHART_THEME = {
  colors: ['#2A9D8F', '#E63946', '#E9C46A', '#F4845F', '#85B7EB'],
  background: '#111116',
  grid: '#1A1A2240',
  text: '#5A5A6A',
  tooltip: { bg: '#1A1A22', border: '#222230', text: '#F0F0F5' },
};

// Tooltip component
const D4CTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: '#1A1A22', border: '1px solid #222230',
      borderRadius: 8, padding: '8px 12px',
      fontFamily: "'JetBrains Mono', monospace", fontSize: 12,
    }}>
      <div style={{ color: '#8A8A9A', marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toLocaleString('es-AR') : p.value}
        </div>
      ))}
    </div>
  );
};
```

## Branding Footer

Every client-facing output includes:

```
Generado por Valinor · Delta 4C · {date}
```

Or for Narzil outputs:
```
Generado por Narzil · Delta 4C · {date}
```

In monospace, text-tertiary color, at the bottom of the artifact.

## Google Fonts Import

For HTML artifacts, include:
```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
```

For React artifacts, these fonts are typically available via CDN already.

## File Naming

- KO Reports: `ko-report-{company}-{date}.jsx`
- Dashboards: `d4c-dashboard-{name}.jsx`
- HTML reports: `d4c-{type}-{company}.html`
- Design artifacts: `d4c-{name}.jsx`
