#!/usr/bin/env python3
"""
N6 frequent-subset definer (VAL-192).

The N6 hito targets the "frequent subset" of the golden set — the question
classes a distilled model should master. We define it deterministically from the
golden questions' ``seed_entities`` (entity recurrence = frequency proxy): the
FREQUENT subset = questions whose seed_entities are all within the top-K most
recurrent entities. No runtime/usage data, no client data — just the golden set.

(The run-history alternative is rejected: ClientProfile.run_history is run-level,
not question-level, so per-question frequency would need a schema break + history
we don't have.)

Emits evals/distill/frequent_subset.json — the list the future LoRA's baseline is
measured on. Pure CPU.

Refs: VAL-192 (N6)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "evals" / "golden" / "global_questions.yaml"
OUT = ROOT / "evals" / "distill" / "frequent_subset.json"
TOP_K = 8


def main() -> int:
    import yaml
    data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    qs = data["questions"] if isinstance(data, dict) else data
    active = [q for q in qs if q.get("split") in ("train", "test") and not q.get("replaced_by")]

    ent_count: Counter = Counter()
    for q in active:
        for e in q.get("seed_entities", []):
            ent_count[e] += 1
    top = {e for e, _ in ent_count.most_common(TOP_K)}

    frequent = sorted(
        q["id"] for q in active
        if q.get("seed_entities") and set(q["seed_entities"]) <= top
    )

    payload = {
        "definition": f"questions whose seed_entities ⊆ top-{TOP_K} most recurrent entities",
        "top_entities": dict(ent_count.most_common(TOP_K)),
        "n_active": len(active),
        "n_frequent": len(frequent),
        "frequent_question_ids": frequent,
        "note": "The bar the future LoRA must match: current-system accuracy on "
                "these (N3 community arm, gloria-v6 — mostly 1.00 on served-aggregate "
                "classes). Measure with: scripts/eval.py graphrag --split test --csv …, "
                "then filter to these ids.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
