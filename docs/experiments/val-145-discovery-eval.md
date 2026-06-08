# VAL-145 — Discovery Engine empirical eval (paper §7)

Determinism: MockLLMClient (reproducible); real-LLM agent contribution pending.

Baseline mapping: `fk_only` → Structural-only, `ensemble` → Ours (no hint pack), `ensemble_hinted` → Ours (full)

## FK inference

| Variant | Baseline | Recall | Precision | F1 | Pred | Gold |
|---|---|---|---|---|---|---|
| gloria_full | Structural-only | 1.0 | 0.1127 | 0.2025 | 71 | 8 |
| gloria_full | Ours (no hint pack) | 0.875 | 1.0 | 0.9333 | 7 | 8 |
| gloria_full | Ours (full) | 0.875 | 1.0 | 0.9333 | 7 | 8 |
| gloria_no_fks | Structural-only | 1.0 | 0.1127 | 0.2025 | 71 | 8 |
| gloria_no_fks | Ours (no hint pack) | 0.0 | 0.0 | 0.0 | 0 | 8 |
| gloria_no_fks | Ours (full) | 0.125 | 1.0 | 0.2222 | 1 | 8 |
| gloria_obfuscated | Structural-only | 1.0 | 0.1127 | 0.2025 | 71 | 8 |
| gloria_obfuscated | Ours (no hint pack) | 0.0 | 0.0 | 0.0 | 0 | 8 |
| gloria_obfuscated | Ours (full) | 0.0 | 0.0 | 0.0 | 0 | 8 |

## ERP hint-pack ablation (Ours full − Ours no-hint) — the contribution

| Variant | ΔRecall | ΔPrecision | ΔF1 | recall (no-hint → hint) |
|---|---|---|---|---|
| gloria_full | 0.0 | 0.0 | 0.0 | 0.875 → 0.875 |
| gloria_no_fks | 0.125 | 1.0 | 0.2222 | 0.0 → 0.125 |
| gloria_obfuscated | 0.0 | 0.0 | 0.0 | 0.0 → 0.0 |

## Entity classification accuracy (Ours full)

| Variant | Accuracy |
|---|---|
| gloria_full | 0.4 |
| gloria_no_fks | 0.4 |
| gloria_obfuscated | 0.4 |

## Latency / cost

| Baseline | Variant | Latency (s) | LLM calls | Cost (USD) |
|---|---|---|---|---|
| Structural-only | gloria_full | 0.09 | 0 | 0.0 |
| Ours (no hint pack) | gloria_full | 0.01 | 0 | 0.0 |
| Ours (full) | gloria_full | 0.0 | 0 | 0.0 |
| Structural-only | gloria_no_fks | 0.08 | 0 | 0.0 |
| Ours (no hint pack) | gloria_no_fks | 0.0 | 0 | 0.0 |
| Ours (full) | gloria_no_fks | 0.0 | 0 | 0.0 |
| Structural-only | gloria_obfuscated | 0.08 | 0 | 0.0 |
| Ours (no hint pack) | gloria_obfuscated | 0.0 | 0 | 0.0 |
| Ours (full) | gloria_obfuscated | 0.0 | 0 | 0.0 |

## Targets (§7)

| Metric | Measured | Target | Met | Note |
|---|---|---|---|---|
| FK recall (no-constraint schemas) | 0.0 | 0.85 | ❌ | deterministic structural+hint only — real-LLM agents pending |
| FK precision (Ours full) | 1.0 | 0.9 | ✅ |  |
| Entity classification accuracy | 0.4 | 0.9 | ❌ | deterministic ontology builder |
| Discovery latency (s) | 0.0 | 30.0 | ✅ | MockLLM; real-LLM adds agent round-trips |
| Cost per analysis (USD) | 0.0 | 0.5 | ✅ | MockLLM = $0; real-LLM ensemble ~2 Haiku calls/variant |

## Remaining experiments

- Real-LLM run: semantic + business-process agent FK contribution and a true LLM-only baseline (needs the proxy/API up; the golden set is tiny so the run is cheap — ~Haiku calls — but non-deterministic). This is the last open item; everything below is DONE.
- DONE — Scalability sweep (50 / 200 / 500 tables): scripts/discovery_scalability_eval.py → docs/experiments/val-145-scalability.md.
- DONE — Cross-pilot generalization (2nd ERP family, Retail POS): scripts/discovery_cross_family_eval.py → docs/experiments/val-145-cross-family-generalization.md.
- DONE — Per-layer (L0-L5) latency/cost breakdown: scripts/discovery_layer_profile.py → docs/experiments/val-145-layer-breakdown.md.
