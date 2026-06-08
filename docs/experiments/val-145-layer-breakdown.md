# VAL-145 — Discovery Engine per-layer latency/cost breakdown (paper §7)

Determinism: MockLLMClient (reproducible, $0). Per-layer SHARE and LLM-call placement are citable; absolute wall-clock and real-LLM latency are pending a live run.

Variants: gloria_full, gloria_no_fks, gloria_obfuscated (mean across variants).

## Per-layer breakdown (L0-L5)

| Layer | Stage | Mean latency (ms) | Share % | LLM calls (real) | Cost (USD, real proj.) |
|---|---|---|---|---|---|
| L0 | Schema extraction | 3.344 | 46.8% | 0 | 0.0 |
| L1 | Structural profiling | 2.3839 | 33.4% | 0 | 0.0 |
| L2 | IND / FK candidates | 0.8801 | 12.3% | 0 | 0.0 |
| L3 | ERP Hint Pack | 0.2551 | 3.6% | 0 | 0.0 |
| L4 | Knowledge graph | 0.1285 | 1.8% | 0 | 0.0 |
| L5 | LLM semantic validation | 0.15 | 2.1% | 2 | 0.016 |

## Totals

- Mean end-to-end (deterministic, MockLLM): **7.1415 ms**
- Real-LLM calls per analysis: **2** (all in L5)
- Projected real-LLM cost per analysis: **$0.016**

## Reading this table

- Only **L5** touches the LLM — L0-L4 are deterministic, so the moat work (structural + hint pack, L2-L3) carries **zero per-call cost**.
- Under MockLLM absolute latency is sub-millisecond and not representative; the **share %** column is the citable structure. Absolute wall-clock under a real LLM is the remaining live-run step.
