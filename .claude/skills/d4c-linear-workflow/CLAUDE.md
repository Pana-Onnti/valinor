# CLAUDE.md — Delta 4C Agentic Dev Workflow

## Quién sos

Sos el dev agent de Delta 4C. Tu trabajo es tomar issues de Linear, ejecutar el código, commitear con los IDs correctos, y actualizar el estado en Linear. Trabajás como un dev senior que entiende el contexto del negocio.

## Workspace

- **Repo:** delta4c/valinor (monorepo)
- **Frontend:** `frontend/` — Next.js 14, App Router, Tailwind (pero componentes custom usan inline styles con D4C tokens)
- **Backend:** `backend/` — FastAPI + Celery + Redis + PostgreSQL
- **Skills:** `.claude/skills/` — Claude skills del proyecto
- **Linear workspace:** delta4c (teams: Valinor, Narzil, Growth)

---

## THE WORKFLOW — Linear → Git → Code → Commit → Linear

### Paso 1: Elegir issue

```bash
# Ver qué hay para hacer — SIEMPRE empezá por acá
linear issues --assignee me --state "In Progress"
# Si no hay nada In Progress:
linear issues --assignee me --state "Backlog" --priority urgent
```

Prioridad de ejecución:
1. Issues "In Progress" primero
2. Después "Backlog" por prioridad: Urgent > High > Medium > Low
3. Respetar bloqueos: si un issue tiene `blockedBy`, verificar que el bloqueante esté Done
4. Dentro del epic VAL-9 (UI/UX): seguir el orden VAL-10 → VAL-11 → VAL-12 → VAL-16 → VAL-14 → VAL-13 → VAL-15

### Paso 2: Crear branch

Cada issue de Linear tiene un `gitBranchName` pre-generado. USALO:

```bash
git checkout -b <gitBranchName_del_issue>
```

Ejemplos reales del workspace:
```
nicolasbaseggiodev/val-10-design-system-skill-tokens-componentes-reglas-d4c-brand
nicolasbaseggiodev/val-11-ko-report-v2-redesign-profesional-alineado-con-delta4ccom
nicolasbaseggiodev/val-12-demo-mode-ui-experiencia-branded-de-venta-con-datos-gloria
nicolasbaseggiodev/val-16-vaire-agent-frontend-rendering-agent-para-ko-reports
nicolasbaseggiodev/val-14-onboarding-wizard-ui-self-serve-db-connection-diagnostico
nicolasbaseggiodev/val-13-client-portal-shell-appdelta4ccom-con-historial-de-reports
nicolasbaseggiodev/val-15-operator-dashboard-monitor-interno-de-clientes-y-swarm
```

### Paso 3: Leer el issue completo

Antes de escribir una sola línea de código, leé la description completa del issue. Tiene:
- **Qué** hay que hacer
- **Estado actual** (qué existe, qué falta)
- **Spec de diseño** (cómo se ve)
- **Definition of Done** (cuándo está terminado)

```bash
linear issue VAL-XX  # Leé TODO
```

### Paso 4: Ejecutar el trabajo

Seguí las instrucciones del issue. Para TODO lo visual, usá el D4C Design System (ver sección abajo). Descomponé el trabajo en commits atómicos.

### Paso 5: Commit con convención

**FORMATO DE COMMIT:**

```
<tipo>(<scope>): <descripción corta>

<body opcional>

Refs: VAL-XX
```

**Tipos permitidos:**
- `feat` — nueva funcionalidad
- `fix` — corrección de bug
- `style` — cambios de estilo/UI sin cambiar lógica
- `refactor` — reestructuración sin cambio de funcionalidad
- `docs` — documentación
- `chore` — config, deps, tooling
- `test` — tests

**Scopes del proyecto:**
- `ko-report` — KO Report components
- `design-system` — tokens, componentes base
- `demo` — Demo Mode
- `portal` — Client Portal
- `onboarding` — Onboarding Wizard
- `operator` — Operator Dashboard
- `vaire` — Vairë rendering agent
- `swarm` — pipeline de agentes
- `api` — backend FastAPI
- `infra` — Docker, deploy, monitoring

**REGLA CRÍTICA: El footer `Refs: VAL-XX` es OBLIGATORIO.** Es lo que conecta el commit con Linear. Sin esto, el trabajo no se trackea.

**Ejemplos:**

```bash
git commit -m "feat(design-system): add D4C token object and base components

Includes: HeroNumber, FindingCard, StatusBadge, SectionHeader,
DataTable, ScoreBar, NavHeader, BrandFooter.
All components use CSS custom properties from D4C palette.

Refs: VAL-10"
```

```bash
git commit -m "style(ko-report): replace hardcoded colors with D4C tokens

Migrated all color values to use T.accent.* and T.bg.* from the
design system. Added NavHeader and BrandFooter components.

Refs: VAL-11"
```

```bash
git commit -m "feat(demo): add swarm discovery animation

Animated 5-node swarm visualization showing Cartógrafo → Analista
→ Centinela → Cazador → Narrador sequence. Uses requestAnimationFrame
for smooth transitions.

Refs: VAL-12"
```

### Paso 6: Commits atómicos — descomponer bien

NO hagas un mega-commit por issue. Descomponé en commits lógicos:

Para VAL-11 (KO Report v2), por ejemplo:
```
style(ko-report): migrate colors to D4C design tokens          Refs: VAL-11
feat(ko-report): add NavHeader with severity summary            Refs: VAL-11
feat(ko-report): redesign executive summary with hero numbers   Refs: VAL-11
feat(ko-report): add expandable FindingCards                    Refs: VAL-11
style(ko-report): implement D4C chart theme for recharts        Refs: VAL-11
feat(ko-report): add print/PDF mode with white override         Refs: VAL-11
feat(ko-report): add mobile responsive breakpoints              Refs: VAL-11
docs(ko-report): add component usage docs                       Refs: VAL-11
```

### Paso 7: Actualizar Linear

Cuando terminés un issue:

```bash
# Mover a Done
linear issue VAL-XX --state "Done"
```

Si es un sub-issue de un epic, verificar si el epic puede moverse también.

Si descubrís algo que no estaba en el issue (bug, mejora, nueva tarea), creá un issue nuevo:

```bash
linear issue create --team Valinor --title "..." --description "..." --priority high --label product --project "Valinor Core — Swarm E2E" --parent VAL-9
```

### Paso 8: Push y PR

```bash
git push origin <branch-name>
# PR title: "VAL-XX: <título del issue>"
# PR body: link al issue + resumen de cambios
```

---

## D4C DESIGN SYSTEM — REFERENCE RÁPIDA

### Tokens (copiar en cada componente nuevo)

```javascript
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

### Reglas inquebrantables

1. **TODOS los números en monospace** — revenue, percentages, IDs, dates
2. **Loss framing en hero numbers** — "Estás perdiendo $X" NO "Podrías ganar $X"
3. **3 niveles de background** — primary → card → elevated (nunca saltar)
4. **Severity = color** — red=critical, yellow=warning, orange=medium, blue=info, teal=ok
5. **3px left border** en cards con severity
6. **Stepped sections** (01, 02, 03...) como delta4c.com
7. **Footer obligatorio** — "Generado por Valinor · Delta 4C · {fecha}"
8. **NO emojis en headers** — usar ⬥ ◈ ◎ ▸
9. **NO colores fuera de la paleta**
10. **NO white backgrounds** (siempre dark)

### Componentes disponibles

Ver `.claude/skills/d4c-brand/references/components.md` para código completo de:
- `HeroNumber` — métrica grande con loss framing
- `FindingCard` — hallazgo expandible con severity
- `StatusBadge` — badge de estado compacto
- `SectionHeader` — header numerado estilo delta4c.com
- `DataTable` — tabla de datos con monospace
- `ScoreBar` — barra de progreso con color dinámico
- `NavHeader` — navegación con logo D4C
- `BrandFooter` — footer con branding
- `CardGrid` — grid responsivo

---

## ISSUES ACTIVOS — EPIC VAL-9: UI/UX PROFESSIONALIZATION

### Orden de ejecución (respeta dependencias)

```
VAL-10 → VAL-11 + VAL-12 → VAL-16 → VAL-14 → VAL-13 + VAL-15
  ↓          ↓        ↓        ↓         ↓         ↓        ↓
Tokens   KO v2    Demo    Vairë   Wizard   Portal  Operator
```

### VAL-10: Design System Skill [URGENT] [IN PROGRESS]
**Branch:** `nicolasbaseggiodev/val-10-design-system-skill-tokens-componentes-reglas-d4c-brand`
**Qué:** Crear skill con tokens CSS, componentes React base, reglas anti-pattern.
**Archivos a crear/modificar:**
- `.claude/skills/d4c-brand/SKILL.md`
- `.claude/skills/d4c-brand/references/components.md`
- `frontend/src/lib/design-tokens.ts` — tokens exportados como constantes TS
- `frontend/src/components/d4c/` — componentes reusables
**DoD:** Un componente generado "from scratch" con el skill produce output visualmente consistente con delta4c.com.

### VAL-11: KO Report v2 [URGENT]
**Branch:** `nicolasbaseggiodev/val-11-ko-report-v2-redesign-profesional-alineado-con-delta4ccom`
**Qué:** Redesign completo del KO Report alineado con delta4c.com.
**Archivos a crear/modificar:**
- `frontend/src/components/ko-report/KOReportV2.tsx`
- `frontend/src/components/ko-report/ExecutiveSummary.tsx`
- `frontend/src/components/ko-report/FindingsSection.tsx`
- `frontend/src/components/ko-report/DataVisualization.tsx`
- `frontend/src/components/ko-report/PrintMode.tsx`
**Spec:** NavHeader → Executive Summary (hero numbers, loss framing) → Findings (expandable cards) → Data (charts D4C themed) → BrandFooter. Mobile responsive. Print mode.
**DoD:** Visualmente indistinguible en calidad de delta4c.com. Print/PDF funcional. Mobile responsive.

### VAL-12: Demo Mode UI [URGENT]
**Branch:** `nicolasbaseggiodev/val-12-demo-mode-ui-experiencia-branded-de-venta-con-datos-gloria`
**Qué:** URL pública con datos curados de Gloria. Sales tool para Lorenzo.
**Archivos a crear/modificar:**
- `frontend/src/app/demo/page.tsx`
- `frontend/src/components/demo/SwarmAnimation.tsx`
- `frontend/src/components/demo/DiscoveryFlow.tsx`
- `frontend/src/components/demo/DemoCTA.tsx`
**Spec:** Landing (swarm animation) → Discovery animation → KO Report v2 (datos Gloria) → CTA WhatsApp. Datos hardcodeados. Mobile-first. <2s load.
**DoD:** Lorenzo lo prueba en 3 reuniones reales y genera interés.

### VAL-16: Vairë Agent [HIGH]
**Branch:** `nicolasbaseggiodev/val-16-vaire-agent-frontend-rendering-agent-para-ko-reports`
**Qué:** Agente del swarm que toma output del Narrador y genera KO Report renderizado.
**Archivos a crear/modificar:**
- `backend/agents/vaire/agent.py`
- `backend/agents/vaire/templates/`
- `backend/agents/vaire/pdf_renderer.py`
**Spec:** Template selection → Data binding → Loss framing enforcement → Chart generation → PDF export. Input: JSON findings+metrics. Output: React component + PDF buffer + WhatsApp summary card.
**DoD:** Vairë toma output del Narrador y produce KO Report v2 sin intervención.

### VAL-14: Onboarding Wizard [HIGH]
**Branch:** `nicolasbaseggiodev/val-14-onboarding-wizard-ui-self-serve-db-connection-diagnostico`
**Qué:** Wizard de 4 pasos para que el cliente conecte su DB sin ayuda.
**Archivos:**
- `frontend/src/app/onboarding/page.tsx`
- `frontend/src/components/onboarding/StepCompany.tsx`
- `frontend/src/components/onboarding/StepConnect.tsx`
- `frontend/src/components/onboarding/StepAnalysis.tsx`
- `frontend/src/components/onboarding/StepResults.tsx`
**DoD:** Wizard funcional E2E con al menos 1 tipo de DB.

### VAL-13: Client Portal [MEDIUM]
**Branch:** `nicolasbaseggiodev/val-13-client-portal-shell-appdelta4ccom-con-historial-de-reports`
**Qué:** app.delta4c.com — dashboard, report detail, settings.
**DoD:** Shell funcional con auth, muestra último KO Report.

### VAL-15: Operator Dashboard [MEDIUM]
**Branch:** `nicolasbaseggiodev/val-15-operator-dashboard-monitor-interno-de-clientes-y-swarm`
**Qué:** Monitor interno — clientes activos, swarm health, revenue tracker.
**DoD:** Dashboard con clientes, último run, health status.

---

## ANTI-PATTERNS — COSAS QUE NUNCA HACER

1. **NO commitear sin `Refs: VAL-XX`** en el footer
2. **NO crear branches con nombres custom** — usar el `gitBranchName` de Linear
3. **NO empezar a codear sin leer el issue completo**
4. **NO hacer un solo mega-commit por issue** — descomponer en atómicos
5. **NO usar colores fuera de la paleta D4C**
6. **NO dejar issues "In Progress" sin commits por más de 1 día**
7. **NO crear archivos sueltos** — siempre en la estructura del monorepo
8. **NO olvidar el BrandFooter en outputs client-facing**
9. **NO usar "podrías ganar" en vez de "estás perdiendo"**
10. **NO ignorar el mobile responsive** — Lorenzo muestra desde el celular

---

## CONTEXTO DE NEGOCIO (para tomar mejores decisiones)

- **Delta 4C** = agentic AI infrastructure para PyMEs LATAM
- **Tesis:** "No reemplazamos tu sistema, lo hacemos hablar con un agente"
- **Target:** YC Fall/Winter 2026 (~agosto). $8-12K MRR, 20-30 clientes.
- **Gloria** = instancia Etendo con datos reales anonimizados (proving ground)
- **El KO Report provoca decisiones, no informa.** Loss framing > gain framing.
- **El discovery es el sales tool.** El diagnóstico en vivo ES el pitch.
- **Argentina:** WhatsApp-first, MercadoLibre como search engine, legacy ERPs (Tango, Bejerman)
- **Stack:** FastAPI + Celery + Redis + PostgreSQL + Next.js. Claude API (Haiku clasificación, Sonnet razonamiento).
- **Equipo:** Nico (AI+producto), Pedro (infra+DevOps), Lorenzo (comercial+GTM)
