# Delta 4C — Issue Reference (Epic VAL-9)

> Auto-generated from Linear. Last updated: 2026-03-21.
> Si estás leyendo esto como agente, esta es tu fuente de verdad para qué hacer y en qué orden.

## Dependency Graph

```
VAL-10 (Design System) ──┬──→ VAL-11 (KO Report v2)
                         ├──→ VAL-12 (Demo Mode)
                         │
                         ├──→ VAL-16 (Vairë Agent) ──→ VAL-14 (Onboarding Wizard)
                         │
                         └──→ VAL-13 (Client Portal)
                              VAL-15 (Operator Dashboard)
```

## Execution Order

| Order | Issue  | Priority | Status     | Branch |
|-------|--------|----------|------------|--------|
| 1     | VAL-10 | Urgent   | In Progress | `nicolasbaseggiodev/val-10-design-system-skill-tokens-componentes-reglas-d4c-brand` |
| 2a    | VAL-11 | Urgent   | Backlog    | `nicolasbaseggiodev/val-11-ko-report-v2-redesign-profesional-alineado-con-delta4ccom` |
| 2b    | VAL-12 | Urgent   | Backlog    | `nicolasbaseggiodev/val-12-demo-mode-ui-experiencia-branded-de-venta-con-datos-gloria` |
| 3     | VAL-16 | High     | Backlog    | `nicolasbaseggiodev/val-16-vaire-agent-frontend-rendering-agent-para-ko-reports` |
| 4     | VAL-14 | High     | Backlog    | `nicolasbaseggiodev/val-14-onboarding-wizard-ui-self-serve-db-connection-diagnostico` |
| 5a    | VAL-13 | Medium   | Backlog    | `nicolasbaseggiodev/val-13-client-portal-shell-appdelta4ccom-con-historial-de-reports` |
| 5b    | VAL-15 | Medium   | Backlog    | `nicolasbaseggiodev/val-15-operator-dashboard-monitor-interno-de-clientes-y-swarm` |

(2a/2b and 5a/5b can run in parallel)

---

## VAL-10: Design System Skill

### Files to create
```
.claude/skills/d4c-brand/SKILL.md
.claude/skills/d4c-brand/references/components.md
frontend/src/lib/design-tokens.ts
frontend/src/components/d4c/tokens.ts
frontend/src/components/d4c/HeroNumber.tsx
frontend/src/components/d4c/FindingCard.tsx
frontend/src/components/d4c/StatusBadge.tsx
frontend/src/components/d4c/SectionHeader.tsx
frontend/src/components/d4c/DataTable.tsx
frontend/src/components/d4c/ScoreBar.tsx
frontend/src/components/d4c/NavHeader.tsx
frontend/src/components/d4c/BrandFooter.tsx
frontend/src/components/d4c/CardGrid.tsx
frontend/src/components/d4c/D4CTooltip.tsx
frontend/src/components/d4c/index.ts
```

### Commit plan
```
chore(design-system): create skill directory and SKILL.md              Refs: VAL-10
feat(design-system): add design tokens as TypeScript constants         Refs: VAL-10
feat(design-system): add HeroNumber component with loss framing        Refs: VAL-10
feat(design-system): add FindingCard with expandable evidence          Refs: VAL-10
feat(design-system): add StatusBadge and SectionHeader                 Refs: VAL-10
feat(design-system): add DataTable with monospace numbers              Refs: VAL-10
feat(design-system): add NavHeader, BrandFooter, CardGrid              Refs: VAL-10
feat(design-system): add D4CTooltip for recharts integration           Refs: VAL-10
feat(design-system): add barrel export index.ts                        Refs: VAL-10
docs(design-system): add component reference documentation             Refs: VAL-10
```

### Definition of Done
- [ ] Skill file created and accessible
- [ ] All 11 components implemented as .tsx
- [ ] Tokens exported as TS constants
- [ ] A component generated from scratch using the skill looks consistent with delta4c.com

---

## VAL-11: KO Report v2

### Files to create/modify
```
frontend/src/components/ko-report/KOReportV2.tsx        (main component)
frontend/src/components/ko-report/ExecutiveSummary.tsx   (hero numbers grid)
frontend/src/components/ko-report/FindingsSection.tsx    (expandable findings)
frontend/src/components/ko-report/DataVisualization.tsx  (charts: pareto, aging, revenue, concentration)
frontend/src/components/ko-report/ReportHeader.tsx       (nav + severity summary)
frontend/src/components/ko-report/PrintMode.tsx          (print/PDF styles)
frontend/src/components/ko-report/types.ts               (TypeScript interfaces)
frontend/src/app/report/[id]/page.tsx                    (route)
```

### Data structure (input from Narrador/Vairë)
```typescript
interface KOReportData {
  company: string;
  date: string;
  dataQualityScore: number;
  executiveSummary: {
    headline: string;  // "Tu empresa está perdiendo $X.XX/mes"
    heroNumbers: Array<{
      value: string;
      label: string;
      sublabel?: string;
      severity: 'critical' | 'warning' | 'medium' | 'info';
    }>;
  };
  findings: Array<{
    id: number;
    severity: 'critical' | 'warning' | 'medium' | 'info';
    number: string;
    headline: string;
    evidence: string;
    action: string;
    valueAtStake: string;
    source: string;  // "tabla: c_invoice | query: abc123"
    sparkData?: number[];
  }>;
  charts: {
    revenue: Array<{ month: string; value: number }>;
    pareto: Array<{ segment: string; pct: number; cumulative: number }>;
    aging: Array<{ bucket: string; value: number }>;
    categories: Array<{ name: string; value: number; pct: number }>;
  };
}
```

### Commit plan
```
feat(ko-report): add TypeScript interfaces for report data            Refs: VAL-11
style(ko-report): create ReportHeader with D4C NavHeader              Refs: VAL-11
feat(ko-report): build ExecutiveSummary with HeroNumber grid          Refs: VAL-11
feat(ko-report): build FindingsSection with expandable cards          Refs: VAL-11
feat(ko-report): add DataVisualization with D4C chart theme           Refs: VAL-11
feat(ko-report): compose KOReportV2 main component                   Refs: VAL-11
feat(ko-report): add PrintMode with CSS media queries                 Refs: VAL-11
style(ko-report): add mobile responsive breakpoints                   Refs: VAL-11
feat(ko-report): add report route /report/[id]                        Refs: VAL-11
test(ko-report): render with Gloria sample data                       Refs: VAL-11
```

### Definition of Done
- [ ] Visually indistinguishable in quality from delta4c.com
- [ ] Print/PDF mode functional
- [ ] Mobile responsive (WhatsApp-shareable)
- [ ] Gloria data renders correctly
- [ ] All components from D4C design system used

---

## VAL-12: Demo Mode UI

### Files to create
```
frontend/src/app/demo/page.tsx              (main route)
frontend/src/components/demo/SwarmAnimation.tsx
frontend/src/components/demo/DiscoveryFlow.tsx
frontend/src/components/demo/DemoCTA.tsx
frontend/src/data/gloria-demo-data.ts       (curated Gloria data)
```

### User flow
1. URL loads → SwarmAnimation (5 nodes pulsing, connecting)
2. After 2s → DiscoveryFlow: "Cartógrafo analizando..." → "253 entidades" → "Analizando patrones..."
3. After 5s total → KOReportV2 renders with curated Gloria data
4. Scroll to bottom → DemoCTA: "¿Querés ver esto sobre TUS datos?" → WhatsApp link + form

### Gloria demo data (curate these findings)
1. $3.27M deuda vencida +90 días (CRITICAL)
2. $5.74M pedidos sin facturar (CRITICAL)
3. 8.9% margen bruto (WARNING)
4. 253 clientes = 80% revenue (WARNING)
5. 19,385 pedidos sin convertir a factura (MEDIUM)

### Commit plan
```
feat(demo): create demo route with layout                             Refs: VAL-12
feat(demo): build SwarmAnimation with 5-node pulsing visualization    Refs: VAL-12
feat(demo): add DiscoveryFlow with staged reveals                     Refs: VAL-12
feat(demo): curate Gloria demo data for maximum impact                Refs: VAL-12
feat(demo): compose demo page with KOReportV2                        Refs: VAL-12
feat(demo): add DemoCTA with WhatsApp deep link                      Refs: VAL-12
style(demo): optimize for mobile and <2s load                        Refs: VAL-12
```

---

## VAL-16: Vairë Agent

### Files to create
```
backend/agents/vaire/agent.py           (main agent class)
backend/agents/vaire/template_engine.py (Jinja2 template selection)
backend/agents/vaire/pdf_renderer.py    (WeasyPrint PDF generation)
backend/agents/vaire/loss_framing.py    (enforce loss framing on numbers)
backend/agents/vaire/chart_config.py    (recharts config generator)
backend/agents/vaire/templates/
    ko_report.html.j2
    executive_summary.html.j2
    whatsapp_card.txt.j2
```

### Agent responsibilities
1. Template Selection → choose correct template
2. Data Binding → map findings/metrics to components
3. Loss Framing Enforcement → verify hero numbers use negative framing
4. Chart Config Generation → generate recharts-compatible JSON
5. PDF Export → WeasyPrint with D4C dark theme
6. WhatsApp Summary → plain text card with top 3 findings

---

## VAL-14: Onboarding Wizard

### 4-step flow
1. **Company info** — name, industry dropdown, system (Tango/Bejerman/Etendo/Excel/Otro)
2. **Connect data** — DB string / Excel upload / "help me" → call scheduler
3. **Analysis** — swarm progress animation (WebSocket real-time)
4. **Results** — KOReportV2 + CTA retainer

---

## VAL-13: Client Portal + VAL-15: Operator Dashboard

Lower priority. Shell implementations. See Linear issues for full spec.
