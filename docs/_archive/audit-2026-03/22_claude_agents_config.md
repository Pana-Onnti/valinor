# Investigacion: Configuracion de Agentes Claude en Valinor SaaS

**Fecha:** 2026-03-22
**Ruta investigada:** `/home/nicolas/Documents/delta4/valinor-saas/.claude/`
**Alcance:** Agentes, comandos, skills, workflow, settings

---

## 1. Resumen Ejecutivo

El directorio `.claude/` contiene un sistema completo de orquestacion de desarrollo agentico construido sobre Claude Code. Se compone de **6 agentes especializados**, **8 comandos de workflow**, y **3 skills** que en conjunto implementan un ciclo cerrado Linear -> Git -> Code -> Linear. El sistema esta disenado para que un equipo de 3 personas (Nico/AI+producto, Pedro/infra, Lorenzo/comercial) pueda operar un producto de BI agentico (Valinor) con trazabilidad total entre issues de Linear y commits de Git.

La arquitectura de agentes sigue un patron de "swarm especializado": cada agente tiene un rol unico, herramientas permitidas especificas, modelo de LLM asignado (Haiku para tareas simples, Sonnet para razonamiento complejo), y reglas explicitas de activacion/desactivacion. Los skills funcionan como conocimiento inyectable que se carga bajo demanda segun el tipo de tarea.

---

## 2. Agentes Definidos (6)

Todos residen en `.claude/agents/`. Cada archivo define: rol, contexto, reglas, tools permitidos, modelo, condiciones de activacion/desactivacion.

### 2.1 swarm-architect.md
- **Rol:** Validar el pipeline multi-agente Cartografo -> QueryBuilder -> [Analista+Centinela+Cazador] -> Narrador.
- **Modelo:** Sonnet (razonamiento sobre arquitectura).
- **Tools:** Solo lectura (Read, Grep, Glob). No puede escribir.
- **Responsabilidades:** Revisar harnesses, token budgets, validar que outputs sean Pydantic, verificar fallbacks.
- **Token budgets definidos:** Cartografo <8K, QueryBuilder <12K, Analistas <20K, Narrador <30K.
- **Activacion:** Disenar/revisar agentes del swarm, `/project:review-code`.

### 2.2 backend-dev.md
- **Rol:** Implementar features en FastAPI + Celery + Redis + PostgreSQL.
- **Modelo:** Sonnet.
- **Tools:** Completo (Read, Write, Edit, Bash, Grep, Glob).
- **Reglas clave:** Preservar Valinor v0 (wrapper, no rewrite), SSH tunneling obligatorio, nunca almacenar datos de clientes.
- **Flujo:** Domain layer primero -> Application layer -> Infrastructure layer -> Tests -> Commit.
- **Puertos:** API:8000, PostgreSQL:5450, Redis:6380, Claude Proxy:8099.

### 2.3 agent-engineer.md
- **Rol:** Escribir y refinar harnesses (system prompts) para los Valar del swarm.
- **Modelo:** Sonnet ("disenar prompts requiere razonamiento sobre razonamiento").
- **Tools:** Completo.
- **Valar del swarm:** Cartografo, QueryBuilder, Analista, Centinela, Cazador, Narrador, Vaire.
- **Regla clave:** Output siempre Pydantic-validable, token budget estricto.
- **Template de harness definido:** Rol, contexto, output format, restricciones, ejemplos.
- **Tabla de calibracion Haiku vs Sonnet:** Routing/clasificacion=Haiku, analisis numerico/narrativa=Sonnet.

### 2.4 infra-ops.md
- **Rol:** Docker Compose, monitoring (Prometheus+Grafana+Loki), deploy (Cloudflare Workers, GitHub Actions).
- **Modelo:** Haiku (operaciones bien definidas, bajo razonamiento).
- **Tools:** Completo.
- **Referencia de puertos completa:** 9 servicios mapeados (API, Frontend, PostgreSQL, Redis, Prometheus, Grafana, Loki, Promtail, Claude Proxy).
- **Regla critica:** Claude Proxy (8099) corre en el HOST, no en Docker.

### 2.5 pm-linear.md
- **Rol:** Sincronizar Linear con Git/Code. Lee/actualiza issues, session log, decision log.
- **Modelo:** Haiku.
- **Tools:** Read, Write, Glob + todos los tools de Linear MCP.
- **Linear workspace:** delta4c, team Valinor (key VAL).
- **Proyectos:** "Valinor Core -- Swarm E2E", "Knowledge Base", "Gloria -- Proving Ground".
- **Regla critica:** Un issue = una tarea = un branch. Nunca duplicar en markdown lo que esta en Linear.
- **Flujos definidos:** start-session (5 pasos), end-session (6 pasos).

### 2.6 test-writer.md
- **Rol:** Escribir y mantener tests (unit, integration, E2E).
- **Modelo:** Haiku (escritura repetitiva de tests, bajo costo).
- **Tools:** Read, Write, Bash, Grep, Glob (no Edit).
- **Suite actual:** ~2481 tests.
- **Regla critica:** NO mockear la DB, integration tests contra DB real. Consolidar con @pytest.mark.parametrize.

---

## 3. Comandos Disponibles (8)

Residen en `.claude/commands/`. Son slash commands invocables como `/project:<nombre>`.

| Comando | Proposito | Modifica estado? |
|---------|-----------|-----------------|
| `start-session` | "Git pull cognitivo" -- lee Linear + plan tactico, presenta estado | No (solo lectura) |
| `end-session` | "Git push cognitivo" -- actualiza Linear con progreso, session log, decision log | Si (Linear + plan local) |
| `status` | Dashboard del proyecto: issues, % completado, blockers | No (solo lectura) |
| `plan-task` | Investiga codebase, crea issue estructurado en Linear | Si (crea issue en Linear) |
| `implement-feature` | Lee issue, crea branch, implementa, commitea, actualiza Linear | Si (codigo + Linear) |
| `fix-bug` | Reproduce, diagnostica root cause, implementa fix, testea | Si (codigo + Linear) |
| `run-tests` | Ejecuta pytest, reporta resultados, diagnostica fallos | No (solo lectura) |
| `review-code` | Revision dual: swarm-architect (arquitectura) + infra-ops (seguridad) | No (solo lectura) |

### Detalles destacados

**start-session / end-session** forman un par simetrico que actua como "memoria de sesion":
- start-session lee issues In Progress + Backlog urgentes + plan tactico local.
- end-session genera resumen, actualiza comments por issue, mueve estados, actualiza Session Log y Decision Log en Linear, actualiza plan tactico local, verifica git.

**implement-feature** define un flujo completo en 8 pasos: leer issue -> crear branch -> leer contexto tecnico -> cargar brand skill si es UI -> implementar Domain->App->Infra -> commits atomicos -> mover issue -> crear sub-issues si se descubre trabajo adicional.

**review-code** ejecuta revision dual con checklists explicitos:
- Arquitectura: 7 checks (domain limpio, output tipado, fallbacks, token budget, logging, DQ Gate, adapter pattern).
- Seguridad: 7 checks (credenciales, puertos, localhost, datos clientes, SSH keys, REPEATABLE READ, cleanup SSH).
- Tests: 3 checks (coverage, regresion, duplicados).

---

## 4. Skills (3)

### 4.1 d4c-linear-workflow
**Ruta:** `.claude/skills/d4c-linear-workflow/`
**Archivos:** SKILL.md, CLAUDE.md, references/commit-msg.hook, references/d4c-commit.sh, references/issues-val9.md

Es el skill mas extenso. Define el ciclo completo PICK -> BRANCH -> READ -> CODE -> COMMIT -> UPDATE -> PUSH -> NEXT.

**Componentes clave:**
- **SKILL.md:** Loop de 8 pasos con ejemplos, tipos de commit (7), scopes (11), reglas de decomposicion atomica.
- **CLAUDE.md:** Version extendida con contexto de negocio (target YC Fall/Winter 2026, $8-12K MRR), design tokens inline, issues activos del epic VAL-9, anti-patterns (10 reglas).
- **commit-msg.hook:** Script bash que valida formato `tipo(scope): desc` + `Refs: VAL-XX`. Soporta prefijos VAL, NAR, GRO.
- **d4c-commit.sh:** Helper que simplifica commits: `./d4c-commit.sh feat ko-report "add hero numbers" VAL-11`.
- **issues-val9.md:** Referencia del epic VAL-9 con dependency graph, execution order, files to create, commit plans, y DoD para cada issue (VAL-10 a VAL-16).

**Trigger conditions:** "pick up an issue", "work on VAL-XX", "what's next", "commit this", "push this", o cualquier referencia al workflow.

### 4.2 d4c-brand-skill
**Ruta:** `.claude/skills/d4c-brand-skill/`
**Archivos:** SKILL.md, references/components.md

Define el sistema de diseno visual de Delta 4C. Filosofia: "un prospecto no deberia distinguir donde termina delta4c.com y donde empieza el producto."

**Contenido:**
- **Paleta completa:** 4 backgrounds (#0A0A0F -> #111116 -> #1A1A22 -> #222230), 4 textos, 6 acentos semanticos (teal, red, yellow, orange, blue, purple).
- **Tipografia:** Inter + JetBrains Mono. Regla: TODOS los numeros en monospace.
- **Layout:** Max 960-1200px, 3 niveles de background, severity border 3px left.
- **KO Report rules:** Minto Pyramid, loss framing ("Estas perdiendo" no "Podrias ganar"), hero numbers above the fold, provenance en cada hallazgo.
- **Anti-patterns:** 10 prohibiciones explicitas (colores fuera de paleta, Inter weight 300, borders >1px, gradients excepto CTAs, emojis en headers, white backgrounds, etc.).
- **Recharts theme:** Colores, tooltip custom con formato es-AR.
- **components.md:** 11 componentes React copy-paste ready: HeroNumber, FindingCard, StatusBadge, SectionHeader, DataTable, ScoreBar, D4CTooltip, NavHeader, BrandFooter, CardGrid + ejemplo completo de mini KO Report.

### 4.3 grounded-analysis
**Ruta:** `.claude/skills/grounded-analysis/`
**Archivos:** SKILL.md, references/research.md, references/roadmap.md

El skill mas sofisticado. Define el sistema anti-alucinacion de Valinor. Principio core: "los numeros vienen de sistemas deterministas, los LLMs solo narran hechos verificados."

**Arquitectura en 3 capas:**
1. **Schema Knowledge Graph** (Stage 0.5): Grafo construido 100% desde entity_map del Cartographer. BFS shortest-path para JOINs.
2. **Query Builder mejorado** (Stage 2): Auto-calificacion de columnas, inyeccion de filtros con table-qualification.
3. **Verification Engine** (Stage 3.25): Number Registry (solo valores verificados llegan a narradores), claim decomposition (findings -> hechos atomicos), 4 estrategias de verificacion (exact -> derived -> raw -> approximate), cross-validation.

**Anti-overfitting principle:** "Si sabes la respuesta, no estas testeando el sistema, le estas ensenando el test." Zero hardcoded ERP knowledge en KG o verification.

**Calibration loop definido:** RUN -> COMPARE con ground truth -> IDENTIFY discrepancias -> CLASSIFY root cause -> IMPLEMENT fix en la capa mas baja posible -> TEST contra multiples schemas -> VERIFY no regression.

**references/research.md** -- Bibliografia de 30+ papers organizados en 7 dominios:
1. Anti-hallucination: CoVe, SAFE, CRITIC, Reflexion, Multi-Agent Debate, VerifiAgent.
2. Schema understanding: SchemaGraphSQL, LLM-FK, RIGOR, AutoSchemaKG, QueryWeaver, Cognee, SchemaCrawler-AI.
3. Text-to-SQL: MAC-SQL, CHESS, BIRD Benchmark, Vanna AI (integrado).
4. Data profiling: ydata-profiling, GAIT, Sherlock/SATO/TASTE, ZOES.
5. Industry patterns: Palantir Foundry, Bloomberg retrieval-first, Kensho confidence scoring.
6. Data governance: DataHub, OpenMetadata, Atlan.
7. Neurosymbolic: patron Deterministic + Probabilistic alternado, IBM EDBT 2026.

**references/roadmap.md** -- Plan de implementacion en 6 fases:
- v1-foundation: DONE (33 tests + 8/8 E2E).
- v2-pipeline-integration: Cablear KG + Verification en pipeline live.
- v3-active-verification: Re-query DB para verificar claims (CRITIC pattern).
- v4-auto-discovery: LLM-FK + RIGOR para eliminar configuracion manual.
- v5-adaptive-templates: Reemplazar templates SQL estaticos con generacion KG-guided.
- v6-self-calibration: Loop automatizado evaluator -> memory -> adjuster.

Grafo de dependencias: v3 y v4 pueden correr en paralelo, v5 necesita ambos, v6 necesita todo.

---

## 5. Workflow Linear -> Git -> Code -> Linear

El workflow es un ciclo cerrado de 8 pasos que garantiza trazabilidad total:

```
1. PICK     -- Leer Linear: issues In Progress, luego Backlog por prioridad
2. BRANCH   -- Usar gitBranchName pre-generado por Linear (nunca inventar)
3. READ     -- Leer issue completo: spec, DoD, dependencias
4. CODE     -- Implementar (cargar brand skill si es UI)
5. COMMIT   -- tipo(scope): desc + Refs: VAL-XX (hook valida)
6. UPDATE   -- Mover issue en Linear (Backlog -> In Progress -> Done)
7. PUSH     -- Push branch, crear PR con titulo "VAL-XX: titulo"
8. NEXT     -- Volver al paso 1
```

**Mecanismos de enforcement:**
- `commit-msg.hook`: Rechaza commits sin formato correcto o sin `Refs: VAL-XX`.
- `d4c-commit.sh`: Helper que arma el commit con formato correcto.
- Agente pm-linear: Sincroniza automaticamente estado entre git y Linear.
- Comandos start-session/end-session: "Memoria de sesion" que persiste contexto entre sesiones.

**Reglas de prioridad dentro del epic VAL-9:**
```
VAL-10 -> VAL-11 + VAL-12 (paralelo) -> VAL-16 -> VAL-14 -> VAL-13 + VAL-15 (paralelo)
```

---

## 6. Brand Skill -- Analisis Detallado

El brand skill codifica la identidad visual completa de Delta 4C como conocimiento inyectable para cualquier agente que produzca output visual.

**Tres principios de diseno:**
1. **Seriedad** -- Aspecto de terminal financiero, no SaaS toy.
2. **Urgencia** -- Loss framing, rojos en numeros criticos, copy orientado a accion.
3. **Simplicidad** -- Jerarquia de informacion implacablemente clara para duenos de PyMEs.

**Cobertura de componentes:** 11 componentes React listos para copiar, con un ejemplo integrado de KO Report shell que muestra como componer NavHeader + SectionHeader + CardGrid + HeroNumber + FindingCards + BrandFooter.

**Integacion con workflow:** El comando `implement-feature` carga automaticamente el brand skill cuando detecta trabajo visual (paso 4).

---

## 7. Grounded Analysis Skill -- Analisis Detallado

Este es el diferenciador tecnico del producto. Implementa un patron neurosimbolico donde:
- Los LLMs manejan la **intencion** (que analizar) y la **narracion** (como presentarlo).
- Los sistemas deterministas manejan el **computo** (SQL) y la **verificacion** (matching numerico).

**Metricas target:**
| Metrica | Target |
|---------|--------|
| Ground truth pass rate | 100% |
| Query execution rate | >90% |
| Verification rate | >80% |
| Cross-validation issues criticos | 0 |
| Hardcoded ERP refs en KG | 0 |
| Cross-schema test pass | 100% |

**Estado actual (2026-03-22):** Fases v1 a v6 completadas segun commits recientes (grounded/v5 y grounded/v6 mergeados a develop). El roadmap contempla 6 fases con esfuerzo estimado y metricas de exito por fase.

---

## 8. Settings y Permisos

`settings.local.json` define un modelo de permisos granular:
- **89 comandos Bash permitidos explicitamente** (docker, pip, psql, curl a endpoints especificos, etc.).
- **Linear MCP tools habilitados:** list_issues, get_issue, save_issue.
- **Plugin GitHub habilitado.**
- **Ningun deny explicito.**
- **Patron de seguridad:** Los permisos son whitelisted por comando exacto, no por patron amplio. Esto refleja un approach conservador.

---

## 9. Fortalezas

### 9.1 Trazabilidad total
Cada linea de codigo tiene trazabilidad hacia un issue de Linear via `Refs: VAL-XX`. El hook de commit lo enforce a nivel de git. No hay trabajo invisible.

### 9.2 Separacion de concerns entre agentes
Cada agente tiene un dominio acotado con reglas explicitas de cuando se activa y cuando NO. El swarm-architect solo puede leer (no escribir codigo), el test-writer no implementa features, el pm-linear no toca codigo. Esto previene "agent sprawl" donde un agente hace de todo.

### 9.3 Modelo de costos consciente
La asignacion Haiku vs Sonnet esta pensada por tipo de tarea: pm-linear y test-writer usan Haiku (tareas repetitivas), backend-dev y agent-engineer usan Sonnet (razonamiento complejo). El token budget por agente del swarm esta definido explicitamente.

### 9.4 Anti-hallucination como skill de primera clase
El grounded-analysis skill no es un afterthought: tiene bibliografia de 30+ papers, roadmap de 6 fases, tests E2E, y un principio anti-overfitting explicito. Esto es infraestructura de calidad real, no marketing.

### 9.5 Brand como constraint, no como guideline
El brand skill no dice "intenta usar estos colores" -- dice "si usas un color fuera de paleta, esta mal". Las 10 prohibiciones explicitas son mas utiles que 100 sugerencias.

### 9.6 Workflow simetrico start/end session
El par start-session / end-session actua como un "contexto de sesion" que sobrevive entre invocaciones de Claude Code. El plan tactico local (active-plan.md) es la memoria de corto plazo, Linear es la memoria de largo plazo.

### 9.7 Decision Log como practica institucional
Las decisiones tecnicas se registran en Linear (no en markdown suelto), con formato: Decision + Razon + Alternativas descartadas + Consecuencias. Esto construye memoria organizacional.

---

## 10. Debilidades

### 10.1 Duplicacion entre SKILL.md y CLAUDE.md en d4c-linear-workflow
El skill `d4c-linear-workflow` tiene dos archivos casi identicos: `SKILL.md` (269 lineas) y `CLAUDE.md` (326 lineas). Ambos definen el loop de 8 pasos, los commit types, los scopes, y ejemplos. La version CLAUDE.md agrega contexto de negocio e issues activos, pero el core del workflow esta duplicado. Ademas, el archivo `d4c-linear-workflow-SKILL.md` en la raiz de skills/ es una copia exacta de `d4c-linear-workflow/SKILL.md`.

### 10.2 No hay agente de frontend
Los 6 agentes cubren backend, infra, tests, PM, swarm, y prompt engineering. No hay un agente dedicado a frontend (React/Next.js). El `backend-dev.md` dice explicitamente "Componentes React/Next.js -- escalar a humano". Para un producto que tiene 7 issues de UI (VAL-10 a VAL-16), esta es una brecha significativa.

### 10.3 Permisos demasiado granulares y fragiles
El archivo `settings.local.json` tiene 89 comandos Bash whitelisted individualmente, incluyendo UUIDs especificos de jobs (`curl -s http://localhost:8000/api/jobs/78061cff-...`). Estos permisos se acumulan sesion a sesion y no se limpian. Varios son one-time-use que nunca se necesitaran de nuevo.

### 10.4 No hay versionado de harnesses
El agent-engineer define un template de harness, pero no hay un sistema de versionado para los system prompts de los Valar. Si un cambio de prompt degrada calidad, no hay rollback automatico. El roadmap v6 (self-calibration) lo contempla pero no esta implementado a nivel de skill.

### 10.5 Tests del brand skill inexistentes
El brand skill define 11 componentes React con especificaciones detalladas, pero no hay tests que validen que un componente generado cumple con la paleta, los constraints de tipografia, o los anti-patterns. La validacion es puramente visual/humana.

### 10.6 Linear MCP como single point of failure
Todo el workflow depende de la disponibilidad de Linear via MCP. Si Linear esta caido o el MCP falla, start-session no puede presentar estado, end-session no puede guardar progreso, plan-task no puede crear issues. El unico fallback mencionado es "leer active-plan.md primero y mostrar eso mientras carga."

### 10.7 Scope de issues-val9.md probablemente desactualizado
El archivo `references/issues-val9.md` muestra VAL-10 como "In Progress" y VAL-11 a VAL-16 como "Backlog", pero los commits recientes sugieren trabajo en areas diferentes (grounded/v5, grounded/v6). Este archivo no se auto-actualiza desde Linear.

### 10.8 No hay mecanismo de evaluacion cruzada entre agentes
El review-code combina swarm-architect + infra-ops, pero no hay un mecanismo general de "debate" entre agentes. Si backend-dev y swarm-architect tienen opiniones contradictorias sobre una implementacion, no hay un protocolo de resolucion definido.

---

## 11. Recomendaciones 2026

### 11.1 Crear un agente frontend-dev
Definir un agente dedicado a React/Next.js/Tailwind con el brand skill pre-cargado. Modelo Sonnet. Tools completo. Reglas: usar tokens T.*, no emojis, dark mode always. Activacion: cualquier cambio en `web/` o `frontend/`. Esto cierra la brecha mas critica dado el roadmap UI-heavy.

### 11.2 Consolidar la duplicacion en d4c-linear-workflow
Eliminar `CLAUDE.md` del skill y mover el contexto de negocio unico (target YC, equipo, stack) al `CLAUDE.md` del proyecto raiz. El archivo `d4c-linear-workflow-SKILL.md` suelto en la raiz de skills/ deberia eliminarse. Un solo archivo canonico por concepto.

### 11.3 Implementar linting automatico del brand skill
Crear un script que parsee JSX/TSX y valide:
- Colores usados estan en la paleta D4C.
- Numeros usan font-mono.
- No hay emojis en headers.
- BrandFooter presente en componentes client-facing.
Esto convierte los anti-patterns de "reglas para humanos" a "checks automaticos."

### 11.4 Rotar permisos en settings.local.json
Implementar una limpieza periodica de `settings.local.json` para eliminar permisos one-time-use (UUIDs de jobs, URLs especificas). Considerar patrones glob en lugar de comandos exactos donde sea seguro (ej: `Bash(curl -s http://localhost:8000/api/jobs/*/status)`).

### 11.5 Versionar harnesses con diff tracking
Almacenar cada version de system prompt de los Valar como archivos versionados en `core/valinor/harnesses/v{N}/`. Antes de cambiar un harness, guardar la version anterior. El calibration loop (v6) deberia comparar metricas pre/post cambio de harness.

### 11.6 Agregar fallback offline para el workflow
Definir un modo degradado cuando Linear MCP no esta disponible:
- start-session: leer solo active-plan.md.
- end-session: guardar resumen en `.claude/session-log-offline.md`.
- plan-task: crear issue como markdown temporal en `.claude/pending-issues/`.
- Al reconectar: sincronizar automaticamente.

### 11.7 Definir protocolo de resolucion de conflictos entre agentes
Cuando review-code detecta tension entre perspectivas (ej: swarm-architect quiere refactorizar pero infra-ops dice que es riesgoso para deploy), aplicar un protocolo: 1) Ambos agentes presentan argumentos, 2) Se registra en Decision Log, 3) El humano decide. Actualmente esto es implicito.

### 11.8 Automatizar la actualizacion de issues-val9.md
El archivo de referencia de issues deberia regenerarse desde Linear via MCP al inicio de cada sesion (o eliminarse en favor de consultas directas a Linear). Tener una snapshot estatica que diverge de la realidad genera confusion.

### 11.9 Considerar MCP tools adicionales para el ciclo completo
El agente pm-linear tiene Linear MCP habilitado pero no tiene GitHub MCP para crear PRs automaticamente. Agregar `mcp__github__create_pull_request` al flujo del paso 7 (PUSH) permitiria cerrar el loop sin intervencion manual.

### 11.10 Agregar metricas de uso de agentes
Instrumentar cuantas veces se activa cada agente, cuantos tokens consume por sesion, y cuantas veces un agente se activa fuera de su scope definido. Esto permite evaluar si la separacion de concerns funciona en la practica y optimizar la asignacion de modelos (Haiku vs Sonnet).

---

## Archivos Investigados

| Archivo | Lineas | Proposito |
|---------|--------|-----------|
| `.claude/agents/swarm-architect.md` | 47 | Agente de arquitectura de pipeline |
| `.claude/agents/backend-dev.md` | 59 | Agente de desarrollo backend |
| `.claude/agents/agent-engineer.md` | 68 | Agente de ingenieria de prompts |
| `.claude/agents/infra-ops.md` | 62 | Agente de infraestructura |
| `.claude/agents/pm-linear.md` | 59 | Agente de project management |
| `.claude/agents/test-writer.md` | 55 | Agente de testing |
| `.claude/commands/start-session.md` | 56 | Comando inicio de sesion |
| `.claude/commands/end-session.md` | 90 | Comando fin de sesion |
| `.claude/commands/status.md` | 56 | Comando dashboard de estado |
| `.claude/commands/plan-task.md` | 68 | Comando planificacion de tareas |
| `.claude/commands/implement-feature.md` | 84 | Comando implementacion de features |
| `.claude/commands/fix-bug.md` | 75 | Comando correccion de bugs |
| `.claude/commands/run-tests.md` | 58 | Comando ejecucion de tests |
| `.claude/commands/review-code.md` | 81 | Comando revision de codigo |
| `.claude/skills/d4c-linear-workflow/SKILL.md` | 269 | Skill de workflow Linear-Git |
| `.claude/skills/d4c-linear-workflow/CLAUDE.md` | 326 | Contexto extendido del workflow |
| `.claude/skills/d4c-linear-workflow/references/commit-msg.hook` | 30 | Git hook de validacion |
| `.claude/skills/d4c-linear-workflow/references/d4c-commit.sh` | 41 | Helper de commits |
| `.claude/skills/d4c-linear-workflow/references/issues-val9.md` | 224 | Referencia de issues del epic |
| `.claude/skills/d4c-brand-skill/SKILL.md` | 206 | Skill del sistema de diseno |
| `.claude/skills/d4c-brand-skill/references/components.md` | 437 | Componentes React del brand |
| `.claude/skills/grounded-analysis/SKILL.md` | 281 | Skill anti-alucinacion |
| `.claude/skills/grounded-analysis/references/research.md` | 202 | Bibliografia de investigacion |
| `.claude/skills/grounded-analysis/references/roadmap.md` | 305 | Roadmap de implementacion |
| `.claude/settings.local.json` | 98 | Permisos y plugins |
| `.claude/skills/d4c-linear-workflow-SKILL.md` | 269 | Duplicado de SKILL.md |
