# 05 — Investigacion Web Frontend

**Fecha:** 2026-03-22
**Scope:** `/home/nicolas/Documents/delta4/valinor-saas/web/`
**LOC totales:** ~14,990 lineas TypeScript/TSX

---

## 1. Resumen

El frontend de Valinor SaaS es una aplicacion Next.js 14.1 (App Router) con React 18 que funciona como plataforma de Business Intelligence. Permite a los usuarios conectar bases de datos ERP (Openbravo, Odoo, SAP, MySQL, PostgreSQL), lanzar analisis AI multi-agente, y visualizar reportes ejecutivos con hallazgos, KPIs, data quality scores, y deltas entre ejecuciones.

La aplicacion tiene 22 paginas (routes), 19 componentes, y 4 modulos de libreria. Usa un design system propio ("D4C tokens") con tema dark-first, Tailwind CSS para helpers puntuales, y comunicacion real-time via WebSocket/SSE/polling con fallback progresivo.

Coexiste un `index.html` legacy (vanilla JS, ~616 lineas) que fue el frontend original pre-Next.js — actualmente inactivo pero no eliminado.

---

## 2. Stack Tecnologico

| Capa | Tecnologia | Version |
|------|-----------|---------|
| Framework | Next.js (App Router) | 14.1.0 |
| UI | React | 18.2 |
| Lenguaje | TypeScript | 5.3 |
| Styling | Tailwind CSS + CSS vars + inline styles (tokens) | 3.4 |
| Estado servidor | TanStack React Query | 5.0 |
| Estado local | Zustand (declarado en deps, no usado activamente) | 4.4 |
| Formularios | React Hook Form + Zod | 7.48 / 3.22 |
| Animaciones | Framer Motion | 10.16 |
| Charts | Recharts + SVG sparklines custom | 2.10 |
| Iconos | Lucide React | 0.300 |
| HTTP | Axios + fetch nativo | 1.6 |
| Markdown | react-markdown | 10.1 |
| Notificaciones | react-hot-toast | 2.4 |
| Merge classes | clsx + tailwind-merge | 2.1 / 2.2 |
| Fechas | date-fns | 3.0 |
| Tipografia | Inter (display) + JetBrains Mono (mono) | Google Fonts |
| Container | Docker (node:20-alpine) | Dev only |

---

## 3. Estructura de Componentes

### 3.1 Layout global (`app/layout.tsx`)

```
<html>
  <body>
    <ErrorBoundary>
      <Suspense>
        <Providers>  <!-- QueryClientProvider + Toaster -->
          <div flex>
            <Sidebar />       <!-- Nav lateral 64px sticky -->
            <main>{children}</main>
          </div>
        </Providers>
      </Suspense>
    </ErrorBoundary>
    <ConnectionStatusBadge />  <!-- Fixed bottom-right, health polling -->
  </body>
</html>
```

### 3.2 Arbol de componentes

| Componente | Tipo | Responsabilidad |
|-----------|------|----------------|
| `Sidebar` | Layout | Nav lateral colapsada (64px), 5 links, brand "D4" |
| `AnalysisForm` | Feature | Wizard 3 pasos: ERP selection, conexion DB/SSH, periodo/confirmacion. Zod validation, test connection |
| `AnalysisProgress` | Feature | Tracker de pipeline 7 etapas con WebSocket > SSE > polling fallback |
| `ResultsDisplay` | Feature | Reporte completo: KPIs, findings expandibles, contradicciones, acciones, DQ badge, delta panel |
| `KOReportV2` | Feature | Vista alternativa de reporte ejecutivo con Recharts, hero numbers, secciones numeradas |
| `KOReportLoader` | Container | Carga reporte por jobId y parsea markdown via `reportParser.ts` |
| `DQScoreBadge` | UI | Circular SVG score ring + pill compacta para Data Quality |
| `ProvenanceBadge` | UI | Pill inline con score/source/tag de proveniencia |
| `DeltaPanel` | UI | Panel de delta vs run anterior (NEW/PERSISTS/WORSENED/IMPROVED/RESOLVED) |
| `FindingTimeline` | UI | Timeline vertical de hallazgos activos y resueltos con dots de severidad |
| `KPITrendChart` | UI | Sparkline SVG custom + trend direction con mini-chart |
| `NLQueryWidget` | Feature | Input NL -> SQL generado automaticamente (VAL-32), tabla de resultados |
| `DemoMode` | Feature | Modo demo con datos sinteticos (Gloria Pet Distribution) |
| `ConnectionStatusBadge` | UI | Fixed badge con health check cada 30s |
| `ErrorBoundary` | Utility | Class component, fallback con retry |
| `EmptyState` | UI | Placeholder generico con symbol + title + CTA |
| `SkeletonCard` | UI | Loading skeleton con shimmer animation |

### 3.3 Design System Tokens (`components/d4c/tokens.ts`)

Fuente unica de verdad para el sistema visual:

- **Backgrounds:** primary (#0A0A0F deep void), card (#111116), elevated (#1A1A22), hover (#222230)
- **Text:** primary (#F0F0F5), secondary (#8A8A9A), tertiary (#5A5A6A), inverse (#0A0A0F)
- **Accents:** teal (#2A9D8F brand), red (#E63946 critical), yellow (#E9C46A warning), orange (#F4845F medium), blue (#85B7EB info), purple (#9B5DE5 interno)
- **Radius:** sm (8px), md (12px), lg (16px)
- **Spacing:** xs-xxl (4px-48px)
- **Fonts:** Inter display, JetBrains Mono
- **Severity maps:** SEV_COLOR, SEV_LABEL (espanol)
- **Chart theme:** CHART_THEME para Recharts

---

## 4. Routing

Next.js App Router con las siguientes rutas:

| Ruta | Pagina | Descripcion |
|------|--------|-------------|
| `/` | `page.tsx` | Landing adaptativo: hero CTA (new users) o grid de clientes recientes (returning) |
| `/dashboard` | `dashboard/page.tsx` | Dashboard operador: system health bar, summary KPIs, client cards con sort, comparison table, recent jobs |
| `/clients` | `clients/page.tsx` | Grid de clientes con DQ badges, trend badges, critical counts |
| `/clients/[clientId]` | `clients/[clientId]/page.tsx` | Perfil de cliente: run history, DQ trend, known findings, sub-nav tabs |
| `/clients/[clientId]/history` | `.../history/page.tsx` | Historial de ejecuciones del cliente |
| `/clients/[clientId]/findings` | `.../findings/page.tsx` | Findings activos y resueltos con timeline |
| `/clients/[clientId]/kpis` | `.../kpis/page.tsx` | KPIs con trend charts |
| `/clients/[clientId]/costs` | `.../costs/page.tsx` | Analisis de costos |
| `/clients/[clientId]/alerts` | `.../alerts/page.tsx` | Configuracion de alertas y thresholds |
| `/clients/[clientId]/reports` | `.../reports/page.tsx` | Reportes PDF generados |
| `/clients/[clientId]/segmentation` | `.../segmentation/page.tsx` | Segmentacion de clientes |
| `/clients/[clientId]/dq-history` | `.../dq-history/page.tsx` | Historial de Data Quality scores |
| `/clients/[clientId]/settings` | `.../settings/page.tsx` | Configuracion del cliente |
| `/clients/[clientId]/compare` | `.../compare/page.tsx` | Comparacion entre periodos |
| `/clients/[clientId]/quality/[jobId]` | `.../quality/[jobId]/page.tsx` | Data Quality report detallado de un job |
| `/new-analysis` | `new-analysis/page.tsx` | Wizard 3 pasos + pipeline sidebar + progress + results |
| `/onboarding` | `onboarding/page.tsx` | Flujo guiado SSH > DB > test > launch (1200 LOC) |
| `/results/[jobId]` | `results/[jobId]/page.tsx` | Vista KO Report V2 para un job |
| `/docs` | `docs/page.tsx` | API Reference estatica (39 endpoints documentados) |

**Total: 22 rutas** con dynamic segments `[clientId]` y `[jobId]`.

---

## 5. Estado Global

### 5.1 Server State (TanStack React Query)

- `QueryClientProvider` wrappea toda la app en `providers.tsx`
- Configuracion default (sin staleTime, gcTime, retry customizado)
- Sin uso de `useQuery`/`useMutation` directos en las paginas -- la mayoria usa `useEffect` + `useState` manual con `fetch`/`axios`

### 5.2 Custom Hooks (`lib/hooks.ts`)

3 hooks custom que NO usan React Query:

- `useJobStatus(jobId)` — polling cada 3s hasta estado terminal
- `useClientProfile(name)` — fetch on mount/change
- `useAlertThresholds(name)` — fetch on mount/change

Todos retornan `{ data, loading, error, refetch }`.

### 5.3 Client State

- Zustand esta declarado como dependencia pero no se encontro ningun store definido
- Estado local con `useState` en cada componente/pagina
- No hay context providers custom mas alla de QueryClientProvider

### 5.4 Patron dominante

**El patron predominante es `useEffect` + `useState` + `fetch`/`axios` directo**, sin aprovechar React Query. Esto genera:
- Codigo repetitivo en cada pagina (loading/error/data states)
- Sin cache entre rutas
- Sin deduplicacion de requests
- Sin optimistic updates

---

## 6. Styling / Design System

### 6.1 Capas de estilo (en orden de prevalencia)

1. **Inline styles con tokens** (`style={{ backgroundColor: T.bg.card }}`) — ~70% del CSS
2. **CSS custom classes** (`globals.css`: `.d4c-input`, `.d4c-btn-primary`, `.d4c-btn-ghost`, `.d4c-nav-link`) — ~15%
3. **Tailwind utility classes** (en `ResultsDisplay.tsx`, `ErrorBoundary.tsx`, `NLQueryWidget.tsx`) — ~15%

### 6.2 Problemas de consistencia

- **Mezcla de 3 paradigmas de styling** en el mismo codebase: inline tokens, CSS classes, Tailwind utilities
- `ResultsDisplay.tsx` usa Tailwind classes extensivamente (`className="bg-white dark:bg-gray-900 rounded-2xl"`) mientras el resto usa tokens inline
- `NLQueryWidget.tsx` usa CSS classes sin definicion (`.nl-query-widget`, `.nl-query-header`, etc.) — estilos no encontrados en globals.css
- `ErrorBoundary.tsx` usa Tailwind pero con colores light-mode (`border-red-200 bg-red-50`) que rompen en el tema dark actual

### 6.3 Tailwind config

Configuracion minima: solo `content` paths + darkMode 'class' + plugin `@tailwindcss/typography`. Sin custom theme extensions, sin colores del design system registrados en Tailwind.

### 6.4 Dark mode

El tema es dark-only por defecto (backgrounds #0A0A0F). Pero varios componentes incluyen clases `dark:` de Tailwind que no aplican porque no hay toggle de dark mode -- `<html>` no recibe clase `dark`.

---

## 7. API Integration

### 7.1 Cliente API (`lib/api.ts`)

- Wrapper generico `apiFetch<T>()` con error handling
- 8 funciones: fetchJobStatus, fetchJobResults, startAnalysis, fetchClientProfile, fetchClientKPIs, fetchAlertThresholds, createAlertThreshold, deleteAlertThreshold, testConnection
- Base URL: `NEXT_PUBLIC_API_URL || http://localhost:8000`
- Sin autenticacion (no tokens, no auth headers)

### 7.2 Comunicacion real-time (`AnalysisProgress.tsx`)

Fallback progresivo de 3 niveles:
1. **WebSocket** (`/api/jobs/{id}/ws`) — 3s timeout para conectar
2. **SSE** (`/api/jobs/{id}/stream`) — fallback si WS falla
3. **HTTP Polling** (`/api/jobs/{id}/status`) — cada 3s, fallback final

### 7.3 Patrones de fetch en paginas

- Dashboard: 5 fetches independientes (clients, stats per client, dq-history per client, comparison, system metrics)
- Client detail: 3-4 fetches por pagina
- **No hay batching ni agrupacion de requests**
- Muchas paginas repiten `const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'` localmente en lugar de importar de `lib/api.ts`

### 7.4 Report parsing (`lib/reportParser.ts`)

Parser sofisticado de markdown a datos estructurados:
- Extrae KPIs de tablas markdown con confidence tags (MEASURED/ESTIMATED/INFERRED)
- Parsea findings por severidad con header patterns (emoji + severity + ID)
- Extrae contradictions tables, action tables, sections
- Strip markdown utility (`stripMd`)

---

## 8. Fortalezas

1. **Design system tokens centralizado** — `tokens.ts` como fuente unica de verdad para colores, spacing, tipografia. Consistente en ~85% de la app.

2. **Fallback de conectividad robusto** — WebSocket > SSE > Polling con timeouts y cleanup correcto. Produccion-ready.

3. **Report parser sofisticado** — Convierte markdown del backend en datos estructurados para render custom. Maneja bilinguismo (ES/EN), emojis de severidad, tablas, SQL blocks.

4. **Buena cobertura funcional** — 22 paginas cubren el ciclo completo: onboarding, analisis, resultados, historial, DQ, alertas, segmentacion, comparacion, settings, API docs.

5. **Componentes de visualizacion bien hechos** — DQScoreBadge (SVG ring), KPITrendChart (sparkline custom), DeltaPanel, FindingTimeline. Visualmente consistentes con el tema dark.

6. **Wizard de analisis bien diseñado** — 3 pasos con validacion Zod, seleccion de ERP, test de conexion, seleccion de periodo adaptativa.

7. **Modo demo integrado** — Permite onboarding sin conexion real, con datos sinteticos realistas.

8. **Tipos TypeScript** — Interfaces bien definidas en `lib/types.ts` para todas las entidades API.

9. **Error boundaries y loading states** — Skeletons, empty states, error boundary con retry.

---

## 9. Debilidades

1. **React Query declarado pero no usado** — TanStack React Query esta instalado y el provider configurado, pero el 95% de los fetches son `useEffect + useState + fetch/axios` manuales. No hay cache, deduplicacion, ni refetch automtico.

2. **Zustand fantasma** — Declarado como dependencia, sin ningun store definido. No hay estado global compartido entre paginas.

3. **3 paradigmas de styling en conflicto:**
   - Inline styles con tokens (mayoria)
   - Tailwind classes (ResultsDisplay, ErrorBoundary)
   - CSS classes custom sin stylesheet (NLQueryWidget)
   - Dark mode classes `dark:` que no funcionan (no hay clase `dark` en html)

4. **Codigo repetitivo en paginas** — Cada pagina de `/clients/[clientId]/` replica el mismo patron: API_URL const, useEffect, loading/error/data state, layout wrapper. Sin abstraccion compartida.

5. **Sin autenticacion** — No hay auth flow, no hay tokens, no hay proteccion de rutas. Cualquier usuario accede a todo.

6. **`index.html` legacy** — 616 lineas de vanilla JS duplicando funcionalidad. Confuso para nuevos devs, potencial vector de confusion.

7. **`strict: false` en tsconfig** — TypeScript esta en modo lax. Multiples `any` explicitos en types (`Promise<any>`, `Record<string, any>`).

8. **Sin tests** — No hay tests unitarios ni de integracion para el frontend. No hay setup de Jest/Vitest/Playwright.

9. **Responsive fragil** — Layout con `PipelineSidebar` oculto via `display: none` en inline style. Sin breakpoints, sin media queries en Tailwind. Features grid de 4 columnas sin collapse.

10. **Duplicacion de definiciones** — `ClientComparison`, `ClientSummary`, y variantes se definen inline en multiples paginas en lugar de centralizar en `lib/types.ts`.

11. **Waterfall de requests en Dashboard** — `Promise.all` per-client para stats y DQ history causa N+1 requests. Con 50 clientes = 100+ requests paralelos.

12. **Axios y fetch mezclados** — `AnalysisProgress` y `KOReportLoader` usan axios, `api.ts` usa fetch nativo, paginas usan fetch directo. Sin capa unificada.

---

## 10. Recomendaciones 2026

### P0 — Critico

| # | Recomendacion | Impacto |
|---|--------------|---------|
| 1 | **Migrar fetches a React Query** — Reemplazar los ~40 `useEffect+useState+fetch` por `useQuery`/`useMutation`. Activar cache, staleTime, deduplicacion. | Elimina ~60% del boilerplate, mejora UX (instant navigation), reduce carga al backend |
| 2 | **Unificar styling a tokens + Tailwind** — Registrar tokens de D4C en `tailwind.config.js` como colores custom. Migrar inline styles a clases Tailwind. Eliminar CSS classes huerfanas. | Consistencia visual, DX mejorada, eliminacion de conflictos dark/light |
| 3 | **Implementar auth** — NextAuth.js o Clerk. Proteger rutas con middleware. Pasar token JWT en headers API. | Seguridad basica imprescindible para produccion |

### P1 — Alto

| # | Recomendacion | Impacto |
|---|--------------|---------|
| 4 | **Eliminar `index.html` legacy** | Reduce confusion, elimina codigo muerto |
| 5 | **Activar `strict: true` en tsconfig** — Corregir errores de tipo, eliminar `any` explicitos | Prevencion de bugs, mejor IDE support |
| 6 | **Crear layout compartido para `/clients/[clientId]/`** — Layout con sub-nav tabs, fetch de profile, estado compartido | Elimina ~3000 LOC repetitivas |
| 7 | **Consolidar tipos en `lib/types.ts`** — Mover todas las interfaces inline a un archivo central | Reduce duplicacion, mejora mantenibilidad |
| 8 | **Unificar HTTP client** — Estandarizar en fetch nativo (ya usado en api.ts) o axios, no ambos. Eliminar API_URL duplicado. | Consistencia, un solo punto de configuracion |

### P2 — Medio

| # | Recomendacion | Impacto |
|---|--------------|---------|
| 9 | **Agregar tests** — Vitest + React Testing Library para componentes criticos (AnalysisForm, ResultsDisplay, reportParser). Playwright para E2E del wizard. | Confianza en deploys, prevencion de regresiones |
| 10 | **Implementar Zustand store o eliminarlo** — Si no se necesita estado global, quitar la dependencia. Si si, crear stores para: current client, user preferences, sidebar state. | Limpieza de deps o mejora de UX |
| 11 | **Responsive design** — Agregar breakpoints Tailwind (`sm:`, `md:`, `lg:`). Sidebar colapsable. Grids adaptativos. | Mobile/tablet usable |
| 12 | **Next.js 15 + React 19** — Migrar a Server Components donde aplique (docs, layouts). Usar Server Actions para mutations. | Performance, SEO, menos JS enviado al cliente |
| 13 | **Backend-for-frontend aggregation** — Crear API routes en Next.js para agregar los N+1 requests del dashboard en un solo call. | Mejora dramatica en dashboard con muchos clientes |
| 14 | **i18n** — La app mezcla espanol (UI) e ingles (API, types). Formalizar con next-intl. | Preparacion para multi-idioma |

### P3 — Nice to have

| # | Recomendacion | Impacto |
|---|--------------|---------|
| 15 | **Upgrade Next.js font loading** — Mover de Google Fonts a next/font/local con archivos descargados | Elimina dependencia externa, mejora TTFB |
| 16 | **Design system como paquete** — Extraer tokens + componentes UI base a un paquete NPM interno | Reutilizacion en otros productos D4C |
| 17 | **Storybook** — Documentar componentes UI aislados | DX, design review async |

---

## Archivos clave

| Archivo | Descripcion |
|---------|-------------|
| `web/package.json` | Dependencias y scripts |
| `web/app/layout.tsx` | Root layout con Sidebar + ErrorBoundary |
| `web/app/providers.tsx` | QueryClientProvider + Toaster |
| `web/app/globals.css` | CSS vars + helpers (.d4c-input, .d4c-btn-*, .d4c-nav-link) |
| `web/components/d4c/tokens.ts` | Design system tokens (fuente de verdad) |
| `web/lib/api.ts` | API client (apiFetch wrapper) |
| `web/lib/types.ts` | Interfaces TypeScript compartidas |
| `web/lib/hooks.ts` | Custom hooks (useJobStatus, useClientProfile, useAlertThresholds) |
| `web/lib/reportParser.ts` | Markdown -> ParsedReport parser |
| `web/components/AnalysisForm.tsx` | Wizard 3 pasos (~450 LOC) |
| `web/components/AnalysisProgress.tsx` | Real-time progress tracker (~330 LOC) |
| `web/components/ResultsDisplay.tsx` | Visualizacion de resultados (~400+ LOC) |
| `web/components/ko-report/KOReportV2.tsx` | Vista alternativa de reporte ejecutivo |
| `web/app/onboarding/page.tsx` | Flujo de onboarding completo (1200 LOC) |
| `web/index.html` | Legacy vanilla JS frontend (ELIMINAR) |
