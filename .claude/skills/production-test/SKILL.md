---
name: production-test
description: Run production-grade pipeline tests against real databases with real Claude agents. Use this skill when the user says "run production test", "test real", "test against Gloria", "test producción", "full pipeline test", "how is the product doing", "test E2E real", "run the real test", "correr test real", "estado del producto", or any reference to testing the pipeline with real agents and real data. Also triggers on "compare findings", "analyze test output", "review pipeline results".
---

# Production Pipeline Test — Valinor

Run the full Valinor pipeline against real databases with real Claude agents. Zero mocks.

## Quick Reference

```bash
# Full production test (Gloria PostgreSQL, ~6 min)
pytest tests/test_pipeline_production.py -v -s

# Parameterized by period (SQLite, ~5 min for 3 periods)
pytest tests/test_pipeline_periods.py -v -s

# Only 1 month (fastest real test, ~2 min)
pytest tests/test_pipeline_periods.py -k "1-month" -v -s

# Deterministic stages only (no LLM, <1s)
pytest tests/test_pipeline_gloria_e2e.py::TestGloriaPipelineStages -v
```

## Prerequisites

Before running production tests, verify:

```bash
# 1. Gloria PostgreSQL is available
PGPASSWORD=tad psql -h localhost -U tad -d gloria -c "SELECT COUNT(*) FROM c_invoice"

# 2. Claude CLI or proxy is available
curl -s http://localhost:8099/health || which claude

# 3. If proxy not running:
python3 scripts/claude_proxy.py &
```

## Test Files

| File | DB | Agents | Narrators | Time |
|------|-----|--------|-----------|------|
| `test_pipeline_production.py` | **Gloria PostgreSQL** (260K invoices) | Real | Real | ~6 min |
| `test_pipeline_periods.py` | SQLite (434 invoices, aligned entity_map) | Real | No | ~5 min (3 periods) |
| `test_pipeline_gloria_e2e.py` | SQLite (25 rows) | Real (skip if no LLM) | No | ~3.5 min |

## What the Production Test Covers

```
Stage 0:    Data Quality Gate (8 checks, score 0-100)
Stage 1.5:  Gate Calibration (SQL COUNTs on base_filters)
Stage 2:    Query Builder (8 queries + 7 skipped for missing columns)
Stage 2.5:  Execute Queries (PostgreSQL — DATE_TRUNC, EXTRACT all work)
Post-2.5:   Compute Baseline (revenue, invoices, customers, provenance)
Stage 3:    3 Analysis Agents in parallel (analyst, sentinel, hunter)
Stage 3.5:  Reconciliation (conflict detection, Haiku arbiter if >2x gap)
Stage 3.75: Narrator Context (verification-aware filtering by role)
Stage 4:    4 Narrators in parallel (CEO, controller, sales, executive)
```

## Output Location

All test outputs are saved with timestamps for comparison:

```
tests/output/
├── production/             ← Gloria PostgreSQL full pipeline
│   ├── gloria_Q1-2025_YYYY-MM-DD_HH-MM-SS.json  (full data)
│   └── reports/            ← Markdown reports per narrator
│       ├── briefing_ceo_*.md
│       ├── reporte_controller_*.md
│       ├── reporte_ventas_*.md
│       └── reporte_ejecutivo_*.md
├── periods/                ← Parameterized period tests
│   ├── pipeline_1_month_*.json
│   ├── pipeline_1_quarter_*.json
│   └── pipeline_1_year_*.json
└── gloria_e2e/             ← Basic E2E outputs
```

## How to Analyze Results

After running the test, check the output JSON:

```python
import json
with open("tests/output/production/gloria_Q1-2025_LATEST.json") as f:
    data = json.load(f)

# Summary
print(data["summary"])
# → queries_executed, baseline_revenue, total_findings, reports_generated

# Findings by agent
for agent in ("analyst", "sentinel", "hunter"):
    findings = data["findings"][agent]["findings"]
    for f in findings:
        print(f"{f['id']} [{f['severity']}] {f['headline'][:100]}")

# Reports (full markdown)
for name, content in data["reports"].items():
    print(f"\n=== {name} ({len(content)} chars) ===")
    print(content[:500])
```

## Key Metrics to Watch

| Metric | Good | Warning | Bad |
|--------|------|---------|-----|
| DQ Score | >80 | 50-80 | <50 or HALT |
| Queries succeeded | 8/8 | 6-7/8 | <6/8 |
| Agents with findings | 3/3 | 2/3 | <2/3 |
| Findings grounded | >90% | 70-90% | <70% |
| Narrators completed | 4/4 | 2-3/4 | <2/4 |
| CEO briefing quality | Specific numbers + actions | Generic | Error/timeout |

## Known Issues

1. **Narrator timeout**: Default 60s is too short for production data. Test uses 180s.
2. **SQLite dialect**: Tests on SQLite skip DATE_TRUNC/EXTRACT queries. Use PostgreSQL for full coverage.
3. **Entity map alignment**: entity_map MUST match the actual DB. Mismatched metadata causes hallucinated findings.

## When to Run

- Before any release or demo
- After changing agent prompts (analyst.py, sentinel.py, hunter.py)
- After changing query templates (query_builder.py)
- After changing reconciliation logic
- After changing narrator prompts
- Weekly: to track agent quality over time
