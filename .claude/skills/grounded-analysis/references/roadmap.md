# Grounded Analysis — Implementation Roadmap

## Branch Strategy

Cada fase es un branch separado que se mergea a `develop` cuando pasa tests.
Los branches son incrementales — cada uno construye sobre el anterior.

```
main
 └── develop
      ├── grounded/v1-foundation          ← DONE (this session)
      ├── grounded/v2-pipeline-integration ← Wire KG + Verification into pipeline
      ├── grounded/v3-active-verification  ← Re-query verification (not just registry match)
      ├── grounded/v4-auto-discovery       ← LLM-FK + RIGOR for auto schema understanding
      ├── grounded/v5-adaptive-templates   ← KG-guided query generation (replace static templates)
      └── grounded/v6-self-calibration     ← Automated calibration loop
```

---

## Phase 1: Foundation (DONE)
**Branch**: `grounded/v1-foundation`
**Status**: COMPLETE — 33 unit tests + 8/8 E2E ground truth

### What was built
- `knowledge_graph.py` — data-driven schema graph (BFS JOINs, filter awareness, ambiguous columns)
- `verification.py` — number registry, claim decomposition, cross-validation
- Fixed 6 query templates (AR, aging, top_debtors, dormant, concentration, seasonality)
- Auto table-qualification of filters in query builder
- E2E test against Gloria DB

### Anti-overfitting guarantee
- Zero hardcoded ERP knowledge in KG or verification
- Tested with Openbravo AND Odoo AND SAP-like schemas
- Everything derived from Cartographer's entity_map

---

## Phase 2: Pipeline Integration
**Branch**: `grounded/v2-pipeline-integration`
**Goal**: Wire KG + Verification into the live pipeline so every run uses them

### Tasks
1. **`pipeline.py`**: After `gate_calibration()`, build KG from entity_map
   ```python
   from valinor.knowledge_graph import build_knowledge_graph
   kg = build_knowledge_graph(entity_map)
   ```

2. **`pipeline.py`**: After `reconcile_swarm()`, run Verification Engine
   ```python
   from valinor.verification import VerificationEngine
   verifier = VerificationEngine(query_results, baseline, kg)
   verification_report = verifier.verify_findings(findings)
   ```

3. **Agent prompts**: Inject `kg.to_prompt_context()` into Analyst/Sentinel/Hunter
   - Replace raw `entity_map` JSON dump with semantically enriched KG context
   - Agents see filter requirements, JOIN paths, low-cardinality columns

4. **Narrator prompts**: Inject `verification_report.to_prompt_context()`
   - Narrators see the Number Registry as ONLY source of EUR values
   - Unverified claims marked with `[NO VERIFICADO]`

5. **`deliver.py`**: Save verification report alongside other artifacts
   ```python
   verification_path = output_dir / "verification_report.json"
   ```

6. **`gates.py`**: Add `gate_verification()` — warn if verification rate < 80%

### Tests needed
- Integration test: full pipeline with KG + verification
- Regression test: existing reports don't break
- Performance test: KG build + verification adds < 5s to pipeline

### Definition of Done
- `python -m valinor.run --client gloria --period 2024-12` completes with KG + verification
- Verification report saved alongside other artifacts
- Narrators use Number Registry values

---

## Phase 3: Active Verification
**Branch**: `grounded/v3-active-verification`
**Goal**: Verification Engine can RE-QUERY the database to check claims (CRITIC pattern)

### Why this matters
Currently verification matches claims against existing query results. If an agent claims something that wasn't in any query, we mark it UNVERIFIABLE. Active verification would GENERATE a verification query, execute it, and compare.

### Tasks
1. **`verification.py`**: Add `_generate_verification_query()` method
   - Given a claim like "ISKAY PET revenue is €237K", generate:
     ```sql
     SELECT SUM(grandtotal) FROM c_invoice
     WHERE c_bpartner_id = (SELECT c_bpartner_id FROM c_bpartner WHERE name LIKE '%ISKAY%')
     AND issotrx='Y' AND docstatus='CO' AND isactive='Y'
     AND dateinvoiced BETWEEN '2024-12-01' AND '2024-12-31'
     ```
   - Use KG for correct JOIN paths and filters

2. **`verification.py`**: Add `_execute_verification()` method
   - Takes a connection_string + SQL, executes, returns result
   - Read-only, timeout-limited, row-limited

3. **`verification.py`**: Update `_verify_claim()` strategy chain:
   ```
   exact_registry → derived → raw_results → active_requery → approximate → UNVERIFIABLE
   ```

4. **KG integration**: Use KG to build verification queries
   - `kg.get_required_filters()` for correct WHERE clauses
   - `kg.find_join_path()` for correct JOINs

### Risks
- Active re-querying adds latency (1-2s per claim × ~20 claims = 20-40s)
- Mitigation: only re-query claims marked UNVERIFIABLE after passive strategies
- Connection pooling to avoid repeated connection overhead

### Tests needed
- Unit test: verification query generation produces valid SQL
- E2E test: active verification catches a fabricated value
- Performance test: total verification time < 60s

---

## Phase 4: Auto-Discovery (LLM-FK + RIGOR)
**Branch**: `grounded/v4-auto-discovery`
**Goal**: Eliminate manual entity_map configuration — auto-discover everything

### Research basis
- **LLM-FK** (arXiv:2603.07278): 4-agent FK discovery, F1 0.93-1.00
- **RIGOR** (arXiv:2506.01232): Iterative ontology generation with judge-LLM
- **ydata-profiling**: Statistical fingerprinting
- **ZOES** (arXiv:2506.04458): Zero-shot entity structure discovery

### Tasks
1. **New module: `core/valinor/discovery/fk_discovery.py`**
   - Implement LLM-FK's 4-agent pattern:
     - Profiler: Discover MinUCCs + INDs (statistical, no LLM)
     - Interpreter: LLM extracts domain semantics from names
     - Refiner: Multi-perspective CoT reasoning on FK candidates
     - Verifier: Build schema graph, resolve conflicts
   - Output: list of discovered FK relationships

2. **New module: `core/valinor/discovery/ontology_builder.py`**
   - Implement RIGOR-inspired pipeline:
     - Traverse schema table-by-table following discovered FKs
     - For each table: LLM generates "what this table represents" + business concepts
     - Judge-LLM validates each description
     - Accumulate into growing ontology
   - Output: business ontology (replaces manual business concepts)

3. **New module: `core/valinor/discovery/profiler.py`**
   - Integrate ydata-profiling (or lightweight equivalent):
     - Auto-detect column types (monetary, temporal, categorical, identifier)
     - Detect discriminators by cardinality (<=10 distinct = likely filter)
     - Detect outliers and data quality issues
   - Output: column profiles with semantic types

4. **Update `cartographer.py`**: Use discovery modules
   - Phase 1: Statistical profiling + FK discovery (no LLM)
   - Phase 2: LLM ontology generation with discovered FKs
   - Phase 3: Entity map generation from ontology
   - Remove dependency on manual entity hints

### Anti-overfitting guardrail
- The discovery modules must NEVER reference specific ERP table/column names
- All semantics discovered from data, not from code
- Test with at least 3 different DB schemas (Openbravo, Odoo-style, generic)

### Tests needed
- FK discovery on Gloria DB → compare with known relationships
- FK discovery on Hardis DB → compare with known relationships
- Ontology generation produces valid business concepts without hardcoded hints
- Full pipeline with auto-discovered entity_map produces same quality results

---

## Phase 5: Adaptive Templates (KG-Guided Query Generation)
**Branch**: `grounded/v5-adaptive-templates`
**Goal**: Replace static SQL templates with KG-guided dynamic query generation

### Why this matters
Current `query_builder.py` has static templates with hardcoded column references (`c_invoice_id`, `grandtotal`, etc.). When a new ERP uses different names, the templates break. KG-guided generation builds queries from the graph.

### Research basis
- **QueryWeaver** (FalkorDB): KG → SQL via graph traversal
- **MAC-SQL**: Multi-agent decomposition of complex queries
- **TAG** (Berkeley): Table-Augmented Generation

### Tasks
1. **`core/valinor/agents/query_generator.py`** (replaces query_builder)
   - Input: KG + analysis question (e.g., "total revenue by customer")
   - Process:
     a. Identify required tables from KG (which entities have amount columns?)
     b. Find JOIN paths via `kg.find_join_path()`
     c. Get required filters via `kg.get_required_filters()`
     d. Get ambiguous columns via `kg.get_ambiguous_columns()`
     e. Build SQL from components (not from template string interpolation)
   - Output: validated SQL with provenance metadata

2. **SQL builder DSL** (not string templates):
   ```python
   query = (SQLBuilder(kg)
       .select("SUM", entity="invoices", column="amount_col", alias="total_revenue")
       .select("COUNT", entity="invoices", alias="num_invoices")
       .from_entity("invoices")
       .join_to("customers")  # KG resolves the JOIN path
       .where_period("invoice_date", period)
       .with_required_filters()  # KG injects base_filter
       .group_by("customers", "customer_pk", "customer_name")
       .build())
   ```

3. **Keep static templates as fallback** — don't delete query_builder.py, keep it as backup for when dynamic generation fails

### Tests needed
- Dynamic generation produces same SQL as static templates for Gloria
- Dynamic generation works for Odoo schema without any code changes
- Performance: generation < 500ms per query

---

## Phase 6: Self-Calibration Loop
**Branch**: `grounded/v6-self-calibration`
**Goal**: After each run, automatically evaluate accuracy and adjust

### Research basis
- **Reflexion** (NeurIPS 2023): Store verbal critiques, retry with critique
- **DSPy**: Automated prompt optimization
- **Constitutional AI**: Self-critique against principles

### Tasks
1. **`core/valinor/calibration/evaluator.py`**
   - After pipeline completes, run ground truth queries:
     - `SELECT SUM(amount) FROM invoices WHERE <base_filter>` → compare with baseline
     - `SELECT COUNT(DISTINCT customer) FROM invoices` → compare with baseline
     - For each finding, generate a verification query
   - Score the run: % of claims verified

2. **`core/valinor/calibration/memory.py`**
   - Store calibration results per client per run
   - Track accuracy trends over time
   - Detect regressions: "last run was 95% accurate, this run is 70%"

3. **`core/valinor/calibration/adjuster.py`**
   - If a query consistently fails, adjust the template/generation
   - If a filter is consistently missing, update the entity_map
   - If an agent consistently fabricates, adjust its prompt
   - All adjustments stored as versioned diffs, not in-place edits

4. **Feedback loop**:
   ```
   Run N → Evaluate → Score → Store → Adjust → Run N+1 → Compare
   ```

### Anti-overfitting guardrail
- Adjustments must improve accuracy on ALL clients, not just the one that failed
- Track accuracy per-client AND cross-client
- Any adjustment that helps client A but hurts client B is REJECTED
- Version control all adjustments — can rollback

---

## Dependency Graph

```
v1-foundation (DONE)
    │
    v
v2-pipeline-integration ← First real value (live pipeline uses KG + verification)
    │
    ├──────────────────┐
    v                  v
v3-active-verify    v4-auto-discovery ← Can run in parallel
    │                  │
    └────────┬─────────┘
             v
    v5-adaptive-templates ← Needs both active verify + auto-discovery
             │
             v
    v6-self-calibration ← Final layer, needs everything below it
```

## Effort Estimates

| Phase | Complexity | New modules | Tests needed | Depends on |
|-------|-----------|-------------|--------------|------------|
| v2 | Low | 0 (wiring) | ~10 integration | v1 |
| v3 | Medium | 1 (active verify) | ~15 | v2 |
| v4 | High | 3 (FK, ontology, profiler) | ~30 | v2 |
| v5 | High | 1 (query generator) | ~20 | v3 + v4 |
| v6 | Medium | 3 (evaluator, memory, adjuster) | ~15 | v5 |

## Success Metrics (per phase)

| Phase | Key metric | Target |
|-------|-----------|--------|
| v2 | Pipeline runs with KG + verification | 100% completion |
| v3 | Unverifiable claims → actively verified | <5% remain unverifiable |
| v4 | New client setup time | <5 min (vs ~30 min manual) |
| v5 | Queries work on unseen schema | >90% execution rate |
| v6 | Cross-run accuracy trend | Monotonically improving |
