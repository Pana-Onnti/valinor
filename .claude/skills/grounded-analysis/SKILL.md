---
name: grounded-analysis
description: Anti-hallucination system for Valinor analysis pipeline. Use this skill when improving analysis accuracy, debugging wrong numbers in reports, adding new data sources, fixing query templates, evolving the Knowledge Graph or Verification Engine, or running calibration tests. Also triggers on "hallucination", "wrong number", "fabricated", "accuracy", "grounding", "verification", "overfitting", "generalization". This is the core quality moat of the product.
---

# Grounded Analysis — Anti-Hallucination System

## Purpose

Make Valinor **structurally incapable** of presenting fabricated numbers to clients, regardless of data source (PostgreSQL, MySQL, Excel, CSV, any ERP).

The principle: **numbers come from deterministic systems, LLMs only narrate verified facts.**

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 0.5: Schema Knowledge Graph                                  │
│  ├── Built 100% from Cartographer's entity_map (zero hardcode)     │
│  ├── BFS shortest-path for JOIN reasoning                           │
│  ├── Filter columns from base_filter (Cartographer's decision)     │
│  └── Ambiguous column detection for multi-table queries             │
├─────────────────────────────────────────────────────────────────────┤
│  STAGE 2: Query Builder (enhanced)                                  │
│  ├── Templates auto-qualify columns with table aliases              │
│  ├── Filters injected with table-qualification per entity           │
│  └── KG can validate generated SQL before execution                 │
├─────────────────────────────────────────────────────────────────────┤
│  STAGE 3.25: Verification Engine (post-agents, pre-narrators)       │
│  ├── Number Registry: only verified values reach narrators          │
│  ├── Claim decomposition: findings → atomic verifiable facts        │
│  ├── 4-strategy verification: exact → derived → raw → approximate   │
│  └── Cross-validation: ratio checks, math consistency               │
└─────────────────────────────────────────────────────────────────────┘
```

## Core Files

| File | Role | Hardcoded ERP knowledge? |
|------|------|--------------------------|
| `core/valinor/knowledge_graph.py` | Schema graph, JOIN paths, filter reasoning | **NO** — 100% from entity_map |
| `core/valinor/verification.py` | Number registry, claim verification, cross-validation | **NO** — 100% from query results |
| `core/valinor/agents/query_builder.py` | SQL template generation with auto-qualified filters | Templates are parameterized, not ERP-specific |
| `tests/test_knowledge_graph.py` | Unit tests including cross-ERP generalization | Tests SAP/Odoo schemas too |
| `tests/test_verification.py` | Hallucination detection tests | Tests both correct and fabricated values |
| `scripts/test_gloria_queries.py` | E2E test against real database | Ground truth comparison |

## The Anti-Overfitting Principle

> If you know the answer, you're not testing the system — you're teaching it the test.

### What IS allowed (generalizable)
- Graph algorithms (BFS, shortest-path) — work on any schema
- Statistical detection (low cardinality = likely discriminator) — work on any data
- Cross-validation ratios (debt/customer > 3x = suspicious) — work on any business
- Filter extraction from base_filter strings — work on any SQL dialect
- Ambiguous column detection — work on any multi-table query

### What is NOT allowed (overfitting)
- Hardcoded table names (`c_invoice`, `account_move`, `vbak`)
- Hardcoded column semantics (`issotrx='Y' means sales`)
- Hardcoded ERP knowledge (`fin_payment_schedule needs invoice JOIN`)
- Hardcoded business rules (`AR must exclude purchase invoices`)
- Mapping specific column values to business meanings

### Where domain knowledge SHOULD live
- **Cartographer's entity_map** — discovered dynamically per client
- **Client config overrides** (e.g., `clients/gloria/overrides.md`) — human-curated
- **Probed values** — the Cartographer samples real data
- **NEVER in the Knowledge Graph or Verification Engine code**

## How to Improve the System

### The Calibration Loop

```
1. RUN analysis against a client database
2. COMPARE output against manual SQL verification (ground truth)
3. IDENTIFY discrepancies:
   a. Wrong number? → Find which query/template produced it
   b. Missing data? → Find which query failed or was skipped
   c. Hallucinated claim? → Find which agent invented it
4. CLASSIFY the root cause:
   a. QUERY BUG → Fix the SQL template (parameterized, not hardcoded)
   b. MISSING FILTER → Cartographer needs better base_filter discovery
   c. WRONG JOIN → KG needs the relationship in entity_map
   d. AGENT FABRICATION → Verification Engine needs to catch this pattern
   e. STRUCTURAL → Architecture change needed
5. IMPLEMENT fix at the LOWEST layer possible:
   - Prefer: fix Cartographer > fix template > fix KG > fix agent prompt
   - Avoid: hardcoding the answer for this specific client
6. TEST against MULTIPLE schemas (not just the one that failed)
7. VERIFY no regression on other clients
```

### The Ground Truth Test (offline — no Docker needed)

```bash
# Run E2E test against Gloria DB directly (requires psql access)
python3 scripts/test_gloria_queries.py

# The test:
# 1. Builds KG from entity_map
# 2. Generates all queries from templates
# 3. Executes against real DB
# 4. Computes baseline
# 5. Runs Verification Engine
# 6. Compares against known-correct values
# 7. Reports: X/Y checks passed
#
# Expected output: 8/8 ground truth checks passed
```

### Full Pipeline E2E Test (Docker — production path)

After any code change that touches the pipeline, rebuild and re-test:

```bash
# 1. Rebuild containers with new code
docker compose build api worker

# 2. Restart
docker compose up -d api worker

# 3. Wait for healthy
sleep 5 && curl -s http://localhost:8000/health | python3 -m json.tool

# 4. Launch analysis
JOB_ID=$(curl -s -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "gloria_grounded_test",
    "period": "2024-12",
    "db_config": {
      "host": "localhost", "port": 5432,
      "database": "gloria", "type": "postgresql",
      "user": "tad", "password": "tad"
    }
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "Job: $JOB_ID"

# 5. Poll until complete
while true; do
  sleep 20
  STATUS=$(curl -s http://localhost:8000/api/jobs/$JOB_ID/status)
  echo "$STATUS" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'{d[\"status\"]} | {d[\"stage\"]} | {d[\"progress\"]}%')"
  echo "$STATUS" | python3 -c "
import sys,json; sys.exit(0 if json.load(sys.stdin)['status'] in ('completed','failed') else 1)" && break
done

# 6. Check results
curl -s http://localhost:8000/api/jobs/$JOB_ID/results | python3 -c "
import sys,json; d=json.load(sys.stdin)
qe=d['stages']['query_execution']
print(f'Queries: {qe[\"executed\"]} OK, {qe[\"failed\"]} errors')
print(f'Time: {d[\"execution_time_seconds\"]:.0f}s')
print(f'Agents: {d[\"stages\"][\"analysis_agents\"][\"agents_completed\"]}')"

# Expected: 14 queries OK, 0 errors
# If queries fail → code in container is stale, rebuild
```

### Unit Test Suite

```bash
# Run all grounded-analysis tests (143 tests, <1s)
python3 -m pytest tests/test_knowledge_graph.py tests/test_verification.py \
  tests/test_grounded_v2_integration.py tests/test_active_verification.py \
  tests/test_discovery.py tests/test_query_generator.py tests/test_calibration.py -v

# Quick smoke test (just KG + verification, 33 tests)
python3 -m pytest tests/test_knowledge_graph.py tests/test_verification.py -v
```

### Calibration Test (full stack, no LLM needed)

```bash
# Run KG + queries + verification + calibration against Gloria
python3 -c "
import sys; sys.path.insert(0, 'core')
from valinor.agents.query_builder import build_queries
from valinor.knowledge_graph import build_knowledge_graph
from valinor.verification import VerificationEngine
from valinor.calibration.evaluator import CalibrationEvaluator
from sqlalchemy import create_engine, text

# ... (see scripts/test_gloria_queries.py for full example)
# Expected: Calibration score >= 70/100, 0 critical issues
"
```

### Adding a New Data Source Type

When connecting a new ERP type (SAP, Dynamics, custom DB):

1. **DO NOT** add ERP-specific code to `knowledge_graph.py` or `verification.py`
2. **DO** ensure the Cartographer discovers the schema correctly:
   - Does it find the right discriminator columns via `probe_column_values`?
   - Does it set appropriate `base_filter` values?
   - Does it map relationships correctly?
3. **DO** add a ground truth test for the new source
4. **DO** add the client config in `clients/<name>/config.json` + `overrides.md`

### Improving Verification Coverage

The Verification Engine catches hallucinations post-facto. To improve:

1. **More cross-validation rules** in `_cross_validate()`:
   - Example: `SUM(aging_buckets) should equal total_ar`
   - Example: `top_customer_revenue <= total_revenue`
   - Keep rules as MATHEMATICAL TRUTHS, not domain assumptions

2. **Better claim decomposition** in `_decompose_finding()`:
   - Extract more numeric patterns from agent headlines
   - Handle localized number formats (1.234,56 vs 1,234.56)

3. **Derived value checking** in `_check_derived_value()`:
   - Add more derivation patterns (weighted averages, percentages of subgroups)

## Research Foundation

See `references/research.md` for the full bibliography. Key patterns implemented:

| Pattern | Source | Where in Valinor |
|---------|--------|-----------------|
| Graph pathfinding for JOINs | SchemaGraphSQL (arXiv:2505.18363) | `knowledge_graph.py:find_join_path()` |
| Chain-of-Verification | CoVe (Meta, ACL 2024) | `verification.py:verify_findings()` |
| Fact decomposition | SAFE (DeepMind, NeurIPS 2024) | `verification.py:_decompose_finding()` |
| Tool-interactive verification | CRITIC (ICLR 2024) | `verification.py:_verify_claim()` |
| Number registry | Palantir Foundry ontology | `verification.py:NumberRegistryEntry` |
| Data-driven discriminators | GAIT (PAKDD 2024) | `knowledge_graph.py:is_low_cardinality` |
| Reflexion self-correction | Reflexion (NeurIPS 2023) | Calibration loop (human-in-the-loop) |

## Metrics to Track

| Metric | Target | How to measure |
|--------|--------|----------------|
| Ground truth pass rate | 100% | `test_gloria_queries.py` result |
| Query execution rate | >90% of templates | Queries executed / total templates |
| Verification rate | >80% of claims | `report.verification_rate` |
| Cross-validation issues | 0 critical | `report.issues` with severity=critical |
| Hardcoded ERP refs in KG | 0 | `grep -c 'issotrx\|docstatus' knowledge_graph.py` |
| Cross-schema test pass | 100% | `test_works_with_non_openbravo_schema` |

## Reference Documents

| Document | Content |
|----------|---------|
| `references/research.md` | Full bibliography — 30+ papers/tools organized by domain with applicability assessment |
| `references/roadmap.md` | 6-phase implementation plan with branch strategy, dependency graph, and success metrics |

### Key Research to Revisit Before Each Phase

| Phase | Must-read research |
|-------|-------------------|
| v2 (pipeline integration) | Palantir Foundry ontology pattern, Bloomberg retrieval-first |
| v3 (active verification) | CRITIC (ICLR 2024), VerifiAgent (EMNLP 2025) |
| v4 (auto-discovery) | **LLM-FK (arXiv:2603.07278)**, **RIGOR (arXiv:2506.01232)**, ZOES (EACL 2026) |
| v5 (adaptive templates) | QueryWeaver (FalkorDB), MAC-SQL, TAG (Berkeley) |
| v6 (self-calibration) | Reflexion (NeurIPS 2023), DSPy, Constitutional AI |

### Before Starting Any Phase

1. **Re-search the web** for newer papers on the phase's topic — field moves fast
2. Check if any open-source tool now does what we were going to build
3. Run the ground truth test to establish the pre-change baseline
4. Create the branch from `develop` following the naming in `references/roadmap.md`

## When This Skill Triggers

- "The report shows wrong numbers" → Run calibration loop
- "Adding a new client/ERP" → Verify Cartographer + run ground truth
- "Improving analysis accuracy" → Enhance verification, not hardcode answers
- "The AR/revenue/customer count is off" → Trace through KG → query → results
- "How do we prevent hallucinations?" → This is the system — read the architecture
- "This feels like overfitting" → Audit: count hardcoded refs, run cross-schema test
- "What's the latest research?" → Read `references/research.md` then search web for updates
- "What's next?" → Read `references/roadmap.md` for the next unstarted phase
