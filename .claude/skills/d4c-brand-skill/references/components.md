# Delta 4C — Component Reference

Reusable React components for all D4C artifacts. Copy-paste ready.

## Table of Contents
1. [Design Tokens Object](#tokens)
2. [HeroNumber](#heronumber)
3. [FindingCard](#findingcard)
4. [StatusBadge](#statusbadge)
5. [SectionHeader](#sectionheader)
6. [DataTable](#datatable)
7. [ScoreBar](#scorebar)
8. [D4CTooltip](#tooltip)
9. [NavHeader](#navheader)
10. [BrandFooter](#brandfooter)
11. [CardGrid](#cardgrid)

---

## Tokens

Always define this object at the top of every D4C artifact:

```jsx
const T = {
  bg: { primary: "#0A0A0F", card: "#111116", elevated: "#1A1A22", hover: "#222230" },
  text: { primary: "#F0F0F5", secondary: "#8A8A9A", tertiary: "#5A5A6A", inverse: "#0A0A0F" },
  accent: {
    teal: "#2A9D8F", red: "#E63946", yellow: "#E9C46A",
    orange: "#F4845F", blue: "#85B7EB", purple: "#9B5DE5",
  },
  radius: { sm: 8, md: 12, lg: 16 },
  font: {
    display: "'Inter', 'DM Sans', system-ui, sans-serif",
    mono: "'JetBrains Mono', 'Fira Code', monospace",
  },
};
```

---

## HeroNumber

Large metric with loss framing. Used in KO Report executive summary and dashboard cards.

```jsx
const HeroNumber = ({ value, label, sublabel, color = T.accent.red, borderTop = true }) => (
  <div style={{
    background: T.bg.primary,
    borderRadius: T.radius.sm,
    padding: "16px 20px",
    borderTop: borderTop ? `3px solid ${color}` : "none",
  }}>
    <div style={{
      fontFamily: T.font.mono,
      fontSize: 32,
      fontWeight: 700,
      color,
      marginBottom: 4,
      lineHeight: 1.1,
    }}>{value}</div>
    <div style={{
      fontSize: 12,
      fontWeight: 600,
      color: T.text.primary,
      marginBottom: 2,
    }}>{label}</div>
    {sublabel && (
      <div style={{
        fontSize: 11,
        color: T.text.tertiary,
      }}>{sublabel}</div>
    )}
  </div>
);
```

**Usage:**
```jsx
<HeroNumber
  value="$3.27M"
  label="Deuda vencida +90 días"
  sublabel="Acción inmediata requerida"
  color={T.accent.red}
/>
```

**Rules:**
- Value is ALWAYS formatted in the local currency/format
- Label uses LOSS framing: "perdiendo", "sin cobrar", "bloqueado"
- Color maps to severity: red=critical, yellow=warning, orange=medium, blue=info, teal=positive

---

## FindingCard

Expandable card for each diagnostic finding. Core component of KO Reports.

```jsx
const FindingCard = ({ severity, number, headline, evidence, action, value, source, expanded, onToggle }) => {
  const severityConfig = {
    critical: { color: T.accent.red, label: "CRITICAL" },
    warning: { color: T.accent.yellow, label: "WARNING" },
    medium: { color: T.accent.orange, label: "MEDIUM" },
    info: { color: T.accent.blue, label: "INFO" },
  };
  const s = severityConfig[severity] || severityConfig.info;

  return (
    <div style={{
      background: T.bg.card,
      borderRadius: T.radius.sm,
      borderLeft: `3px solid ${s.color}`,
      padding: "16px 20px",
      cursor: "pointer",
      transition: "background 0.15s ease",
    }} onClick={onToggle}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{
          fontFamily: T.font.mono, fontSize: 10, letterSpacing: "0.08em",
          padding: "2px 8px", borderRadius: 4,
          background: s.color + "20", color: s.color, fontWeight: 600,
        }}>{s.label}</span>
        <span style={{
          fontFamily: T.font.mono, fontSize: 20, fontWeight: 700, color: s.color,
        }}>{number}</span>
      </div>

      {/* Headline */}
      <div style={{
        fontSize: 14, fontWeight: 600, color: T.text.primary, marginBottom: expanded ? 8 : 0,
      }}>{headline}</div>

      {/* Expandable content */}
      {expanded && (
        <>
          <div style={{
            fontSize: 12, color: T.text.secondary, marginBottom: 10,
            lineHeight: 1.6, paddingTop: 4,
          }}>{evidence}</div>

          {/* Action box */}
          <div style={{
            background: T.bg.elevated, borderRadius: 6, padding: "8px 12px",
            display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 8,
          }}>
            <span style={{
              fontFamily: T.font.mono, fontSize: 10, color: T.accent.teal,
              flexShrink: 0, marginTop: 2,
            }}>▸ ACCIÓN</span>
            <span style={{ fontSize: 12, color: T.text.secondary, lineHeight: 1.5 }}>
              {action}
            </span>
          </div>

          {/* Value at stake */}
          {value && (
            <div style={{
              fontFamily: T.font.mono, fontSize: 11, color: s.color,
              marginBottom: 6,
            }}>Valor en juego: {value}</div>
          )}

          {/* Source provenance */}
          {source && (
            <div style={{
              fontFamily: T.font.mono, fontSize: 10, color: T.text.tertiary,
            }}>Fuente: {source}</div>
          )}
        </>
      )}
    </div>
  );
};
```

---

## StatusBadge

Compact status indicator. Used in tables, lists, and card headers.

```jsx
const StatusBadge = ({ status, custom }) => {
  const map = {
    critical: { bg: T.accent.red + "20", color: T.accent.red, label: "CRITICAL" },
    warning: { bg: T.accent.yellow + "20", color: T.accent.yellow, label: "WARNING" },
    info: { bg: T.accent.blue + "20", color: T.accent.blue, label: "INFO" },
    ok: { bg: T.accent.teal + "20", color: T.accent.teal, label: "OK" },
    active: { bg: T.accent.teal + "15", color: T.accent.teal, label: "ACTIVE" },
    error: { bg: T.accent.red + "15", color: T.accent.red, label: "ERROR" },
    pending: { bg: T.bg.elevated, color: T.text.tertiary, label: "PENDING" },
  };
  const s = map[status] || { bg: T.bg.elevated, color: T.text.tertiary, label: custom || status };
  return (
    <span style={{
      fontFamily: T.font.mono, fontSize: 10, letterSpacing: "0.08em",
      padding: "3px 8px", borderRadius: 4,
      background: s.bg, color: s.color, fontWeight: 600,
      display: "inline-block",
    }}>{custom || s.label}</span>
  );
};
```

---

## SectionHeader

Numbered section header matching delta4c.com "El Proceso" style.

```jsx
const SectionHeader = ({ number, title, description, color = T.accent.teal }) => (
  <div style={{ display: "flex", alignItems: "flex-start", gap: 16, padding: "16px 0" }}>
    <div style={{
      fontFamily: T.font.mono,
      fontSize: 32,
      fontWeight: 700,
      color: color + "30",
      lineHeight: 1,
      minWidth: 50,
      userSelect: "none",
    }}>{String(number).padStart(2, "0")}</div>
    <div>
      <div style={{ fontSize: 16, fontWeight: 700, color: T.text.primary, marginBottom: 4 }}>
        {title}
      </div>
      {description && (
        <div style={{ fontSize: 13, color: T.text.secondary, lineHeight: 1.5 }}>
          {description}
        </div>
      )}
    </div>
  </div>
);
```

---

## DataTable

Styled table for financial/business data.

```jsx
const DataTable = ({ columns, rows, monoColumns = [] }) => (
  <div style={{ overflowX: "auto" }}>
    <table style={{
      width: "100%",
      borderCollapse: "collapse",
      fontSize: 12,
    }}>
      <thead>
        <tr>
          {columns.map((col, i) => (
            <th key={i} style={{
              textAlign: "left",
              padding: "8px 12px",
              fontFamily: T.font.mono,
              fontSize: 10,
              letterSpacing: "0.08em",
              color: T.text.tertiary,
              borderBottom: `1px solid ${T.bg.elevated}`,
              fontWeight: 500,
            }}>{col.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} style={{
            background: i % 2 === 0 ? "transparent" : T.bg.elevated + "40",
          }}>
            {columns.map((col, j) => (
              <td key={j} style={{
                padding: "8px 12px",
                fontFamily: monoColumns.includes(col.key) ? T.font.mono : T.font.display,
                color: T.text.primary,
                borderBottom: `1px solid ${T.bg.elevated}40`,
              }}>{row[col.key]}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);
```

---

## ScoreBar

Horizontal progress bar for data quality scores and percentages.

```jsx
const ScoreBar = ({ score, max = 100, width = 80, height = 4 }) => {
  const pct = Math.min(100, (score / max) * 100);
  const color = pct > 70 ? T.accent.teal : pct > 40 ? T.accent.yellow : T.accent.red;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{
        width, height, borderRadius: height / 2,
        background: T.bg.elevated, overflow: "hidden",
      }}>
        <div style={{
          width: `${pct}%`, height: "100%",
          borderRadius: height / 2, background: color,
          transition: "width 0.6s ease",
        }} />
      </div>
      <span style={{
        fontFamily: T.font.mono, fontSize: 11, color: T.text.tertiary,
      }}>{Math.round(pct)}%</span>
    </div>
  );
};
```

---

## NavHeader

Top navigation bar for D4C applications.

```jsx
const NavHeader = ({ product = "Valinor", subtitle, rightContent }) => (
  <div style={{
    padding: "16px 24px",
    borderBottom: `1px solid ${T.bg.elevated}`,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 12,
  }}>
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      {/* Logo mark */}
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        background: `linear-gradient(135deg, ${T.accent.teal}, ${T.accent.blue})`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: T.font.mono, fontSize: 12, fontWeight: 700,
        color: T.text.inverse,
      }}>D4</div>
      <div>
        <div style={{
          fontSize: 14, fontWeight: 700, color: T.text.primary,
          fontFamily: T.font.display,
        }}>{product} Intelligence Report</div>
        {subtitle && (
          <div style={{
            fontFamily: T.font.mono, fontSize: 11, color: T.text.tertiary,
          }}>{subtitle}</div>
        )}
      </div>
    </div>
    {rightContent}
  </div>
);
```

---

## BrandFooter

Standard footer for all D4C outputs.

```jsx
const BrandFooter = ({ product = "Valinor", date }) => (
  <div style={{
    padding: "16px 24px",
    borderTop: `1px solid ${T.bg.elevated}`,
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 8,
    marginTop: 32,
  }}>
    <div style={{
      fontFamily: T.font.mono, fontSize: 10, color: T.text.tertiary,
    }}>Generado por {product} · Delta 4C · {date || new Date().toISOString().slice(0, 10)}</div>
    <div style={{
      fontFamily: T.font.mono, fontSize: 10, color: T.text.tertiary,
    }}>delta4c.com</div>
  </div>
);
```

---

## CardGrid

Responsive grid for hero numbers and summary cards.

```jsx
const CardGrid = ({ children, columns = 3, gap = 12 }) => (
  <div style={{
    display: "grid",
    gridTemplateColumns: `repeat(${columns}, 1fr)`,
    gap,
  }}>{children}</div>
);
```

---

## Complete Example: Mini KO Report Shell

```jsx
export default function KOReport() {
  return (
    <div style={{ background: T.bg.primary, color: T.text.primary, fontFamily: T.font.display, minHeight: "100vh" }}>
      <NavHeader product="Valinor" subtitle="Distribuidora Gloria · 21 Mar 2026" />
      
      <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px" }}>
        <SectionHeader number={1} title="Resumen Ejecutivo" description="Los 3 hallazgos más críticos de tu operación." />
        
        <CardGrid>
          <HeroNumber value="$3.27M" label="Deuda sin cobrar +90 días" color={T.accent.red} />
          <HeroNumber value="8.9%" label="Margen bruto" sublabel="Sin colchón" color={T.accent.yellow} />
          <HeroNumber value="253" label="Clientes = 80% revenue" color={T.accent.orange} />
        </CardGrid>
        
        <div style={{ marginTop: 24 }}>
          <SectionHeader number={2} title="Hallazgos" description="Cada hallazgo incluye evidencia y acción recomendada." />
          {/* FindingCards here */}
        </div>
      </div>
      
      <BrandFooter product="Valinor" />
    </div>
  );
}
```
