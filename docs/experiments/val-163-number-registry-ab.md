# VAL-163 — Number Registry A/B (control vs treatment)

> **Status: harness complete, AWAITING LIVE RUN.** The two halves of the experiment
> are built and unit-tested offline. The numbers below are filled in by one live
> narrator run (the only LLM-dependent step); until then this file is the runbook +
> decision rubric, not a result. Do not cite the table as measured — it is a template.

## Question

Did wiring the Number Registry / `VerificationEngine` into the narrators (VAL-161)
actually improve anti-hallucination quality, or is it inert? The 2026-04-29 audit
downgraded the claim to "wiring delivered; marginal delta unmeasured" because the PRE→POST
improvement was attributable to VAL-141 (sales_v2 structured output), not VAL-161.
This experiment isolates the registry's contribution with everything else held fixed.

## Design

Same captured pipeline state, narrators run twice:

| Branch | `verification_report` | State |
|---|---|---|
| **control** | `None` | pre-VAL-161 (narrators blind to the registry) |
| **treatment** | populated `VerificationReport` | post-VAL-161 (registry-anchored) |

The treatment report is built **offline** — `build_knowledge_graph(entity_map)` +
`VerificationEngine(query_results, baseline, kg).verify_findings(findings)`. The engine
does not re-query the DB (VAL-163 out-of-scope), so the **only** LLM cost is the narrators.

Holding findings/query_results/baseline fixed across both branches means any metric
delta is attributable to the registry alone, not to sampling or upstream changes.

## Metrics (deterministic, scored offline)

`core/valinor/quality/narrator_metrics.py` scores each narrator's text against the run's
ground truth (registry ∪ findings ∪ query_results, tolerance-matched):

1. **Grounded rate** — share of cited numbers that match a ground-truth value.
2. **Hallucinated rate / count** — numbers cited that match nothing.
3. **Hedging / 100 words** — retracted/conditional phrasing frequency.
4. **Token cost & latency** per narrator (registry overhead) — captured at run time.

## How to run (one live run closes this)

```bash
# 1. Capture a real Gloria pipeline-state fixture once (needs Gloria PG + proxy up):
#    dump {entity_map, query_results, baseline, findings, memory, client_config} → state.json
#    (a thin tap in core/valinor/run.py just before run_narrators; see capture harness docstring)

# 2. Run both branches (LLM; VAL-162 timeout budget). --only avoids timeout-prone narrators:
python scripts/capture_narrator_ab.py \
    --state state.json --out-dir docs/experiments/val-163 \
    --only briefing_ceo,reporte_ejecutivo

# 3. Score offline (no LLM) and emit this report's tables:
python scripts/ab_test_number_registry.py \
    --control   docs/experiments/val-163/control.json \
    --treatment docs/experiments/val-163/treatment.json \
    --dataset   docs/experiments/val-163/dataset.json \
    --report    docs/experiments/val-163-number-registry-ab.md \
    --csv       docs/experiments/val-163/metrics.csv
```

The scorer overwrites this file with the measured tables. VAL-162 workaround: start with
`--only briefing_ceo,reporte_ejecutivo` (the narrators that close), widen once VAL-162 lands.

## Results (template — `[TK]` until the live run)

| Metric | Control | Treatment | Δ (treat − ctrl) |
|---|---|---|---|
| Mean grounded rate | `[TK]` | `[TK]` | `[TK]` |
| Mean hallucinated rate | `[TK]` | `[TK]` | `[TK]` |
| Total hallucinated numbers | `[TK]` | `[TK]` | `[TK]` |
| Mean hedging / 100 words | `[TK]` | `[TK]` | `[TK]` |

## Decision rubric (fill in post-run)

Pick one, justified by the Δ column — this is the DoD deliverable:

- **Keep always-on** — treatment materially lifts grounded rate / cuts hallucinated
  numbers at acceptable token+latency overhead.
- **Opt-in only** — delta is small or the overhead is not worth it for every run.
- **Deprecate** — no measurable delta; the wiring is inert and should be removed.

_Decision: `[TK]`_

---

*Harness: `scripts/capture_narrator_ab.py` (capture) + `scripts/ab_test_number_registry.py`
(score) + `core/valinor/quality/narrator_metrics.py` (metrics). Refs: VAL-163.*
