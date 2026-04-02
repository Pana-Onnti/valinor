# VAL-35: Refactorización UI/UX — Valinor SaaS v2

**Linear**: [VAL-35](https://linear.app/delta4c/issue/VAL-35/refactorizacion-uiux-densidad-sidebar-expandible-tokens-lightening)
**Branch**: `nicolasbaseggiodev/val-35-refactorizacion-uiux-densidad-sidebar-expandible-tokens`
**Estado**: Planificado
**Prioridad**: High

---

## Context

La UI actual tiene buena estructura y paleta de colores, pero se siente **vacía, oscura y sin contexto**. Problemas concretos:
- Fondo casi negro (#0A0A0F) con contraste mínimo entre capas
- Sidebar de solo 64px con iconos unicode sin labels
- PipelineSidebar del wizard oculto con `display: none`
- Páginas con mucho whitespace y sin descripciones/tips contextuales
- Sin breadcrumbs, sin paneles de información secundaria

**Objetivo**: Dar vida a la UI sin romper nada — backward compatible, incremental, testeable.

---

## Fase 1: Tokens + CSS (Foundation)

**Archivos**: `web/components/d4c/tokens.ts`, `web/app/globals.css`

### 1.1 Subir fondos ligeramente (mejor contraste entre capas)

| Token | Actual | Nuevo | Delta |
|-------|--------|-------|-------|
| `bg.primary` | `#0A0A0F` | `#0F0F16` | +5 |
| `bg.card` | `#111116` | `#181820` | +7 |
| `bg.elevated` | `#1A1A22` | `#22222E` | +8 |
| `bg.hover` | `#222230` | `#2C2C3A` | +10 |

### 1.2 Nuevos tokens

```typescript
bg.sidebar: '#141420'       // fondo sidebar específico
text.hint: '#6A6A7A'        // tips y hints (entre secondary y tertiary)

layout: {
  sidebarCollapsed: '64px',
  sidebarExpanded: '220px',
  contentMaxWidth: '1200px',
  headerHeight: '52px',
}
```

### 1.3 CSS nuevos

- Actualizar `:root` vars para reflejar nuevos valores
- Agregar `.d4c-pipeline-sidebar`: `display: none` default, `display: flex` en `@media (min-width: 1024px)`
- Agregar `.d4c-nav-label`: transición de opacity para labels del sidebar
- Agregar transición de width en sidebar

---

## Fase 2: Sidebar Expandible

**Archivo**: `web/components/Sidebar.tsx`

- Estado `expanded` (default: `true`, persistido en `localStorage`)
- Width: `expanded ? 220px : 64px` con `transition: width 200ms ease`
- Mostrar `label` de cada `NAV_ITEM` como `<span>` con opacity animada
- Brand: "D4" colapsado → "Delta 4C" expandido
- Footer: reemplazar "v2" con botón toggle (ChevronLeft/ChevronRight)
- Auto-collapse en `< 768px` viewport

`layout.tsx` no necesita cambios — `flex: 1` en main se adapta automáticamente.

---

## Fase 3: Componentes Compartidos Nuevos

**Directorio**: `web/components/d4c/`

### 3.1 `PageHeader.tsx`
```
Props: title, subtitle?, actions?, breadcrumbs?
```
Header consistente con título, subtítulo descriptivo, breadcrumbs opcionales, acciones a la derecha. Borde inferior.

### 3.2 `ContextualTip.tsx`
```
Props: text, variant ('info' | 'security' | 'tip'), dismissible?, icon?
```
Callout inline con borde izquierdo coloreado, fondo tintado al 6%, dismissible con localStorage.

### 3.3 `InfoPanel.tsx`
```
Props: title, items[], style?
```
Panel lateral sticky (260px) para tips, stats de resumen, ayuda contextual. Fondo `bg.card`.

### 3.4 `SectionHeader.tsx`
```
Props: title, description?, actions?
```
Heading de sección estandarizado con descripción secundaria.

### 3.5 `Breadcrumbs.tsx`
```
Props: items: { label, href? }[]
```
Trail de navegación con separadores, usa `next/link`.

---

## Fase 4: Página New Analysis

**Archivo**: `web/app/new-analysis/page.tsx`

1. **Restaurar PipelineSidebar**: cambiar `display: 'none'` → `className="d4c-pipeline-sidebar"` (responsive via CSS)
2. **Tips por paso del wizard**:
   - Paso 0: "Seleccionamos el tipo de ERP para optimizar las consultas SQL y detectar tablas clave."
   - Paso 1: "La conexión es efímera: leemos, analizamos, y desconectamos. Nunca almacenamos credenciales."
   - Paso 2: "El análisis toma ~15 min. Tres agentes AI trabajan en paralelo."
3. Reducir `maxWidth` de 1200 → 1100, el sidebar llena el espacio

---

## Fase 5: Densidad de Contenido por Página

### 5.1 Home (`web/app/page.tsx`)
- **Returning users**: agregar strip de QuickActions (Nuevo Análisis, Dashboard, API Docs)
- **New users**: agregar sección "Cómo funciona" (3 pasos: Conectar → Analizar → Reportar)
- Subtítulo descriptivo bajo el hero

### 5.2 Dashboard (`web/app/dashboard/page.tsx`)
- Agregar subtítulo: "Vista global del estado de todos los clientes y métricas del sistema."
- Stat cards: agregar `borderLeft: 3px solid {stat.color}` para visual pop
- Agregar `SectionHeader` con descripción en cada sección
- Opcional: InfoPanel lateral con tips de Valinor

### 5.3 Clients (`web/app/clients/page.tsx`)
- Agregar subtítulo descriptivo
- Agregar input de búsqueda/filtro sobre el grid

### 5.4 Client Detail (`web/app/clients/[clientId]/page.tsx`)
- Agregar `Breadcrumbs`: Home > Clientes > {nombre}
- Descripciones contextuales en cada stat card

### 5.5 Docs (`web/app/docs/page.tsx`)
- Opcional: navegación sticky lateral con categorías como anchor links

---

## Orden de Implementación

| # | Fase | Riesgo | Impacto | Archivos |
|---|------|--------|---------|----------|
| 1 | Tokens + CSS | Bajo | Alto | 2 archivos |
| 2 | Sidebar expandible | Medio | Alto | 1 archivo |
| 3 | Componentes nuevos | Bajo | Medio | 5 archivos nuevos |
| 4 | New Analysis page | Bajo | Alto | 1 archivo |
| 5 | Content density | Bajo | Medio | 5-6 archivos |

Cada fase es independiente y deployable por separado.

---

## Verificación

1. `npm run build` — sin errores TypeScript
2. Navegación visual de TODAS las páginas después de cada fase
3. Verificar contraste WCAG AA con nuevos colores
4. Toggle sidebar en todas las páginas — sin overflow
5. Wizard new-analysis: recorrer los 3 pasos, verificar sidebar y tips
6. Responsive: verificar en 768px, 1024px, 1440px

---

## Investigación Frontend — Hallazgos

### Inventario de Páginas (21 total)

| Página | Líneas | Estado | Notas |
|--------|--------|--------|-------|
| `/` (home) | 172 | Completo | Hero + client cards + features + demo mode |
| `/new-analysis` | 199 | **PipelineSidebar oculto** | Wizard 3 pasos, sidebar display:none |
| `/dashboard` | 430+ | Completo | System health, jobs, client comparison |
| `/clients` | 235 | Completo | Grid de cards con DQ badges |
| `/clients/[id]` | 881 | Completo | Overview + 9 sub-tabs |
| `/clients/[id]/history` | 565 | Completo | Run history paginado |
| `/clients/[id]/findings` | 661 | Completo | Timeline con severity filter |
| `/clients/[id]/alerts` | 707 | Completo | Threshold editor + triggered alerts |
| `/clients/[id]/segmentation` | 317 | Completo | RFM segments + revenue chart |
| `/clients/[id]/costs` | 501 | Completo | Cost tracking + bar charts |
| `/clients/[id]/kpis` | 311 | Completo | KPI trends + mini charts |
| `/clients/[id]/dq-history` | 362 | Completo | DQ score history + trend |
| `/clients/[id]/quality/[jobId]` | 359 | Sparse | DQ gate report — necesita refresh |
| `/clients/[id]/reports` | 552 | Completo | Jobs list + PDF export |
| `/clients/[id]/settings` | 659 | Completo | Full form + webhooks + danger zone |
| `/clients/[id]/compare` | 206 | Sparse | Run comparison básico |
| `/results/[jobId]` | 15 | Delegado | Wrapper → KOReportLoader |
| `/onboarding` | 1200+ | Completo | Multi-step form complejo |
| `/docs` | 283 | Completo | 64 endpoints, category badges |

### Arquitectura Frontend

- **Framework**: Next.js 14.1.0 App Router + TypeScript + React 18.2.0
- **Styling**: Inline styles via `T` tokens + Tailwind CSS 3.4.0 (mínimo uso)
- **State**: Zustand 4.4.0 + TanStack React Query 5.0.0
- **Forms**: React Hook Form + Zod validation
- **Animation**: Framer Motion 10.16.0
- **HTTP**: Axios 1.6.0
- **Icons**: Lucide React (24px monochrome)
- **Charts**: Recharts

### Design System

- **Tokens**: `web/components/d4c/tokens.ts` (92 líneas)
- **CSS**: `web/app/globals.css` (122 líneas, vars + utilities)
- **Brand skill**: `.claude/skills/d4c-brand-skill/SKILL.md`
- **Component refs**: `.claude/skills/d4c-brand-skill/references/components.md`

### Componentes (18 total)

| Componente | Archivo | KB |
|------------|---------|-----|
| AnalysisForm | `web/components/AnalysisForm.tsx` | 34KB |
| ResultsDisplay | `web/components/ResultsDisplay.tsx` | 33KB |
| NLQueryWidget | `web/components/nl-query/NLQueryWidget.tsx` | 18KB |
| AnalysisProgress | `web/components/AnalysisProgress.tsx` | 10KB |
| DemoMode | `web/components/DemoMode.tsx` | 8KB |
| DeltaPanel | `web/components/DeltaPanel.tsx` | 6KB |
| FindingTimeline | `web/components/FindingTimeline.tsx` | 4KB |
| KPITrendChart | `web/components/KPITrendChart.tsx` | 2KB |
| EmptyState | `web/components/EmptyState.tsx` | 1.7KB |
| SkeletonCard | `web/components/SkeletonCard.tsx` | 1.5KB |
| ConnectionStatusBadge | `web/components/ConnectionStatusBadge.tsx` | 1.5KB |
| ErrorBoundary | `web/components/ErrorBoundary.tsx` | 1.3KB |
| Sidebar | `web/components/Sidebar.tsx` | 3KB |
| DQScoreBadge | `web/components/DQScoreBadge.tsx` | ~1KB |
| ProvenanceBadge | `web/components/ProvenanceBadge.tsx` | ~1KB |
| KOReportLoader | `web/components/ko-report/KOReportLoader.tsx` | ~2KB |
| KOReportV2 | `web/components/ko-report/KOReportV2.tsx` | ~5KB |
| tokens | `web/components/d4c/tokens.ts` | ~2KB |
