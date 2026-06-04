# VAL-145 — Discovery scalability sweep (paper §7)

Structural FK discovery (deterministic, no LLM) over synthetic star schemas; latency target < 30s.

| N tables | Golden FKs | Predicted | Recall | Precision | F1 | Latency (s) | < target |
|---|---|---|---|---|---|---|---|
| 50 | 61 | 61 | 1.0 | 1.0 | 1.0 | 1.856 | ✅ |
| 200 | 244 | 244 | 1.0 | 1.0 | 1.0 | 34.521 | ❌ |
| 500 | 663 | 663 | 1.0 | 1.0 | 1.0 | 199.983 | ❌ |

## Scaling behavior

- 50→200 tables (×4.0): latency ×18.6 (super-linear)
- 200→500 tables (×2.5): latency ×5.8 (super-linear)

## Notes

- Precision is decoupled from synthetic naming by disjoint PK value ranges, so an inclusion dependency holds only for the true target.
- The dominant cost is the O(N²) structural candidate matching (name similarity + inclusion checks), not data volume (rows per table are small and constant).
