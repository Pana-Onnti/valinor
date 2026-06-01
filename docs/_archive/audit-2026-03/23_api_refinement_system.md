# 23. Sistema de Refinamiento — `api/refinement/`

**Fecha**: 2026-03-22
**Archivos analizados**:
- `api/refinement/__init__.py`
- `api/refinement/refinement_agent.py` (176 LOC)
- `api/refinement/query_evolver.py` (105 LOC)
- `api/refinement/prompt_tuner.py` (95 LOC)
- `api/refinement/focus_ranker.py` (34 LOC)
- `shared/memory/client_profile.py` (138 LOC)
- `shared/memory/profile_extractor.py` (265 LOC)
- `api/adapters/valinor_adapter.py` (integrador)
- `tests/test_refinement.py` (715 LOC, 56 tests)
- `tests/test_query_evolver.py` (543 LOC)
- `tests/test_profile_extractor_and_tuner.py` (487 LOC)

---

## Resumen

El sistema de refinamiento es un motor de auto-mejora post-ejecucion que analiza los resultados de cada run de analisis y genera instrucciones adaptativas para el siguiente run. Opera sobre un `ClientProfile` persistente por cliente, acumulando inteligencia a traves de multiples ejecuciones. El sistema tiene cuatro componentes principales (`RefinementAgent`, `QueryEvolver`, `PromptTuner`, `FocusRanker`) que colaboran para crear un ciclo de feedback cerrado: cada run produce datos que refinan el proximo run.

---

## Arquitectura de Refinamiento

### Componentes y Responsabilidades

```
                    +------------------+
                    | valinor_adapter  |  (orquestador)
                    +--------+---------+
                             |
          +------------------+------------------+
          |                  |                  |
   +------v------+   +------v------+   +-------v------+
   | PromptTuner |   | FocusRanker |   | QueryEvolver |
   | (pre-run)   |   | (pre-run)   |   | (post-run)   |
   +-------------+   +-------------+   +--------------+
                             |
                    +--------v---------+
                    | RefinementAgent  |
                    | (post-run, async)|
                    +------------------+
                             |
                    +--------v---------+
                    |  ClientProfile   |  (persistente)
                    +------------------+
```

### Flujo de Datos por Fase

**Pre-run (antes de la ejecucion):**
1. `PromptTuner.build_context_block()` — genera un bloque de texto con contexto historico del cliente (industria, moneda, tablas clave, hallazgos persistentes, hints validados) que se inyecta en los prompts de los agentes LLM. No hace llamadas LLM; es pura construccion de strings desde datos del perfil.
2. `PromptTuner.inject_into_memory()` — inyecta el bloque de contexto y un resumen del perfil en el dict `memory` que usan los agentes del pipeline.
3. `FocusRanker.rerank_entity_map()` — reordena el mapa de entidades por pesos historicos de senal, para que el Query Builder genere mas queries sobre tablas de alto valor.

**Post-run (despues de la ejecucion):**
1. `ProfileExtractor.update_from_run()` — actualiza el perfil con deltas de findings, pesos de tablas, KPIs extraidos de reportes, y estadisticas de run.
2. `QueryEvolver.analyze_query_results()` — trackea queries vacias recurrentes y tablas de alto valor.
3. `RefinementAgent.analyze_run()` — genera un `ClientRefinement` con instrucciones para el proximo run (ejecutado en background via `asyncio.create_task`).

---

## Loop de Auto-mejora

### Ciclo Completo (Run N -> Run N+1)

```
Run N completa
    |
    v
ProfileExtractor.update_from_run()
    - Calcula delta: new / persists / resolved / worsened / improved
    - Actualiza table_weights (normalizado 0.1-1.0 por densidad de findings)
    - Extrae KPIs de reportes ejecutivos via regex
    - Auto-escala severity de findings con 5+ runs abiertos
    - Guarda run_history (cap: 20 entries)
    |
    v
QueryEvolver.analyze_query_results()
    - Registra queries vacias en metadata["empty_query_counts"]
    - Identifica tablas de alto valor (focus_tables que aparecen en SQLs de findings)
    - Agrega hints a preferred_queries (cap: 10)
    |
    v
RefinementAgent.analyze_run() [BACKGROUND]
    - Intenta analisis LLM (Haiku) con prompt estructurado
    - Fallback: heuristica basada en datos del perfil
    - Produce ClientRefinement: table_weights, query_hints, focus_areas, suppress_ids
    - Guarda en profile.refinement y persiste via profile_store
    |
    v
Run N+1 comienza
    |
    v
PromptTuner.build_context_block()
    - Consume profile.get_refinement() para inyectar hints y focus_areas
    - Muestra hallazgos persistentes (3+ runs) y resueltos
    |
    v
FocusRanker.rerank_entity_map()
    - Reordena entidades por table_weights del perfil
    |
    v
Query Builder recibe hints del refinement
    - period_config enriquecido con query_hints y focus_tables
```

### Mecanismo de Convergencia

El loop converge por tres vias:
1. **Poda de queries inutiles**: queries vacias en 2+ runs se marcan como candidatas a reemplazo (visible en `format_context()`).
2. **Amplificacion de senal**: tablas con findings reciben mas peso, generando mas queries sobre ellas en el proximo run.
3. **Supresion de ruido**: findings resueltos entran en `suppress_ids`, evitando que se re-reporten.

---

## Client Memory

### Estructura de `ClientProfile`

El perfil persistente (`shared/memory/client_profile.py`) tiene 18 campos agrupados en 10 categorias:

| Categoria | Campos | Proposito |
|-----------|--------|-----------|
| Identificacion | `client_name`, `created_at`, `updated_at` | Metadata basica |
| Cartographer cache | `entity_map_cache`, `entity_map_updated_at` | Cache de entity map con TTL de 72h |
| Finding tracking | `known_findings`, `resolved_findings` | Estado de hallazgos activos y resueltos |
| Table intelligence | `focus_tables`, `table_weights` | Ranking de tablas por densidad de senal |
| KPI history | `baseline_history` | Series temporales de KPIs (24 puntos max por KPI) |
| Query intelligence | `preferred_queries`, `false_positives` | Queries de alto valor y falsos positivos |
| Refinement | `refinement` | Ultimo `ClientRefinement` serializado como dict |
| Run stats | `run_count`, `last_run_date`, `industry_inferred`, `currency_detected` | Contadores y deteccion automatica |
| History | `run_history` | Ultimos 20 runs resumidos |
| Alertas y segmentacion | `alert_thresholds`, `triggered_alerts`, `segmentation_history`, `dq_history`, `webhooks` | Features avanzadas |

### Persistencia

- Almacenado en PostgreSQL (`client_profiles` table) con fallback a archivo local.
- Serializacion via `to_dict()` / `from_dict()` usando `dataclasses.asdict()`.
- El `ClientRefinement` se almacena como dict plano dentro de `profile.refinement` y se rehidrata via `get_refinement()`.

---

## Iteraciones

### Delta Tracking (`ProfileExtractor`)

Cada run produce un dict delta con 5 categorias:

```python
{
    "new":      [],  # findings vistos por primera vez
    "persists": [],  # findings que repiten sin cambio de severidad
    "resolved": [],  # findings que desaparecieron
    "worsened": [],  # findings cuya severidad subio
    "improved": []   # findings cuya severidad bajo
}
```

La severidad se compara con un ranking numerico: `INFO=0, LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4`.

### Auto-Escalamiento

Findings con `runs_open >= 5` se escalan automaticamente un nivel de severidad (ej: LOW -> MEDIUM). Este mecanismo evita que issues cronicos permanezcan invisibles. Se marca con `auto_escalated: true` en el registro del finding.

### Query Evolution

`QueryEvolver` mantiene un contador persistente (`metadata["empty_query_counts"]`) que acumula runs consecutivos donde una query retorno 0 filas. El umbral para marcar una query como "cronica" es 2 runs vacios. Esto se expone via `format_context()` para que agentes o humanos la reemplacen.

---

## Calidad de Output

### RefinementAgent — Dual Path

1. **Path LLM** (`_llm_analyze`): usa Haiku con un prompt estructurado en espanol. El prompt incluye hallazgos actuales (top 5 por agente), hallazgos persistentes (2+ runs), delta del run, y tablas con mas senal. El output esperado es JSON estricto con 5 campos. Se extrae con regex `\{[\s\S]*\}`.

2. **Path Heuristico** (`_heuristic_analyze`): fallback sin LLM. Copia `table_weights` del perfil, toma `focus_tables[:3]` como focus_areas, genera hints especificos para tablas conocidas de ERP (c_invoice -> DocStatus, c_bpartner -> iscustomer), y usa findings resueltos como suppress_ids (cap: 5).

### PromptTuner — Contexto Adaptativo

Genera un bloque de contexto con formato visual delimitado por `===`. Incluye:
- Nombre de cliente y numero de run
- Industria y moneda detectadas
- Tablas de mayor senal (cap: 5)
- Hallazgos persistentes (3+ runs, cap: 5)
- Anomalias resueltas (ultimas 5)
- Query hints validados (cap: 3)
- Areas de foco (cap: 4)
- IDs a suprimir

En el primer run (`run_count == 0`) retorna string vacio — no hay contexto historico.

---

## Fortalezas

1. **Degradacion elegante**: el sistema funciona sin LLM gracias al fallback heuristico en `RefinementAgent`. Si el LLM falla, el sistema sigue refinando via reglas simples. Log de warning pero sin crash.

2. **No-blocking**: el `RefinementAgent` se ejecuta en background via `asyncio.create_task()`, sin bloquear el pipeline principal. El resultado se persiste asincrono.

3. **Ciclo cerrado real**: los datos fluyen de run a run sin intervencion manual. El sistema aprende que tablas importan (table_weights), que queries son inutiles (empty_query_counts), y que findings son ruido (suppress_ids).

4. **Auto-escalamiento**: el mecanismo de auto-escalamiento de severidad (5+ runs) previene que issues cronicos sean ignorados. Es una politica conservadora pero efectiva.

5. **Cobertura de tests alta**: 56+ tests en `test_refinement.py`, 70+ en `test_query_evolver.py`, 30+ en `test_profile_extractor_and_tuner.py`. Todos pure-logic, sin dependencias externas. Cubren edge cases como None inputs, dicts vacios, y caps.

6. **Separacion de concerns clara**: cada componente tiene responsabilidad unica. `PromptTuner` solo construye strings, `FocusRanker` solo reordena, `QueryEvolver` solo trackea queries, `RefinementAgent` solo genera instrucciones.

7. **Caps defensivos**: multiples limites hardcodeados previenen crecimiento descontrolado: preferred_queries <= 10, run_history <= 20, baseline_history <= 24 por KPI, suppress_ids <= 5, focus_tables <= 10, finding_summary <= 5 por agente.

---

## Debilidades

1. **Sin validacion del output LLM**: `_llm_analyze` extrae JSON con regex generico (`\{[\s\S]*\}`) sin validar tipos ni rangos. Un table_weight de 99.0 o un query_hint de 500 caracteres pasaria sin filtro. No hay schema validation (Pydantic o similar).

2. **Heuristica ERP-especifica**: el fallback heuristico en `_heuristic_analyze` tiene hints hardcodeados para tablas iDempiere/ADempiere (`c_invoice`, `c_bpartner`). No funciona para otros ERPs (SAP, Oracle, Dynamics). No hay abstraccion por tipo de ERP.

3. **Race condition en background save**: `_run_refinement_background` hace `profile_store.save(profile)` en un task async sobre el mismo objeto `profile` que el pipeline principal ya guardo. Si ambos saves ocurren casi simultaneamente, el segundo podria sobreescribir cambios del primero (no hay locking ni merge).

4. **Sin feedback de calidad del refinement**: no hay mecanismo para medir si un `ClientRefinement` realmente mejoro el siguiente run. No hay scoring A/B ni metricas de convergencia. El sistema asume que todo refinement es positivo.

5. **`QueryEvolver` nunca decrementa contadores**: `empty_query_counts` solo crece. Si una query vuelve a tener resultados en un run posterior, su contador no se resetea. Esto puede generar falsos "cronicos" si una query es intermitentemente vacia (ej: datos estacionales).

6. **KPI extraction fragil**: `_extract_kpis_from_report` depende de formato markdown especifico (`**Label**: Value`). Cambios en el formato del reporte ejecutivo rompen la extraccion silenciosamente (retorna lista vacia, sin warning).

7. **`FocusRanker` no considera recencia**: los `table_weights` no decaen con el tiempo. Una tabla que tuvo muchos findings hace 20 runs sigue con peso alto aunque ya no sea relevante. No hay decay factor ni ventana temporal.

8. **Campo `false_positives` no utilizado**: `ClientProfile` declara `false_positives: List[str]` pero ningun componente del sistema de refinamiento lo lee ni lo escribe. Es dead code.

9. **Acoplamiento con `structlog`**: todos los modulos importan `structlog` directamente. Los tests necesitan stubear el modulo a nivel de `sys.modules`, lo cual es fragil.

---

## Recomendaciones 2026

### Prioridad Alta

1. **Validar output LLM con Pydantic**: definir un schema estricto para el JSON del `RefinementAgent`. Validar `table_weights` en rango [0.1, 1.0], `query_hints` con max length, `focus_areas` con max count. Rechazar refinements invalidos y usar fallback heuristico.

2. **Resolver race condition en save**: usar una de estas estrategias:
   - Optimistic locking con version counter en el profile.
   - Mergear solo el campo `refinement` en el background save en vez de guardar el profile completo.
   - Usar una queue para serializar writes al profile.

3. **Resetear `empty_query_counts` cuando query retorna datos**: en `QueryEvolver.analyze_query_results()`, si un query que estaba en `empty_query_counts` ahora tiene rows, setear su count a 0 o eliminarlo del dict.

### Prioridad Media

4. **Decay temporal en `table_weights`**: aplicar un factor de decaimiento (ej: `weight *= 0.95` por run) para que tablas sin findings recientes pierdan prioridad gradualmente.

5. **Metricas de convergencia del refinement**: trackear en `run_history` cuantos findings nuevos aparecen por run. Si el trend es decreciente, el sistema esta convergiendo. Si sube, algo falla. Exponer esto en el bloque de contexto.

6. **Abstraer hints por tipo de ERP**: mover los hints hardcodeados (`DocStatus='CO'`, `iscustomer='Y'`) a un registry de hints por ERP (iDempiere, Odoo, SAP). Cargar el registro correcto segun `industry_inferred` o un nuevo campo `erp_type`.

7. **Implementar `false_positives`**: permitir que el RefinementAgent o un humano marque findings como falsos positivos. El PromptTuner deberia incluirlos en el bloque de contexto para que agentes los ignoren.

### Prioridad Baja

8. **Observabilidad del loop de refinamiento**: emitir metricas (Prometheus/OpenTelemetry) sobre: tiempo de ejecucion del RefinementAgent, ratio LLM vs heuristic fallback, cantidad de suppress_ids generados, y variacion de table_weights entre runs.

9. **Test de integracion del ciclo completo**: crear un test que simule 5 runs consecutivos con datos cambiantes y verifique que el sistema converge (menos findings nuevos, mas resoluciones, weights estabilizados).

10. **Context window management**: el bloque de contexto del `PromptTuner` puede crecer indefinidamente si hay muchos findings persistentes y hints. Establecer un budget de tokens y priorizar la informacion mas relevante.
