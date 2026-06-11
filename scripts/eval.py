#!/usr/bin/env python3
"""
Eval harness — narrator grounding instrument + A/B configs (VAL-192 N1).

The N1 thesis: sin eval, cada cambio es un refactor a ciegas; con eval, cada
cambio tiene veredicto. Two modes:

  golden  Meta-eval of the measurement instrument against the versioned golden
          set (evals/narrator_grounding/golden.yaml): for each hand-labeled
          case, every extracted number must land in its expected bucket
          (grounded / hallucinated / declared), per config (default, +derived
          within-column crediting). Prints the per-config × split table.

          --gate: compares test-split accuracy against the committed baseline
          (evals/narrator_grounding/baseline.json) and exits non-zero on
          regression — this is the build gate (exercised by
          tests/test_eval_gate.py, so plain `pytest` fails on regressions).
          The TRAIN split is for tuning; nobody tunes looking at TEST.

          --update-baseline: rewrite the baseline after a deliberate change.

  ab      Aggregate a captured Number Registry A/B (control vs treatment,
          N reps for confidence intervals) and emit the VAL-163 report tables.
          Consumes docs/experiments/val-163/rep*/{control,treatment,dataset}.json
          produced by scripts/run_capture_ab_live.py. Outputs mean ± std per
          branch, per narrator, and flags corrupted captures (CLI errors /
          timeouts / stubs) instead of silently averaging them.

Utility ("utilidad") is NOT measured here — it needs LLM-as-judge and lands
with the N3 harness. Documented limitation, not an oversight.

Usage:
    python scripts/eval.py golden [--gate] [--update-baseline]
    python scripts/eval.py ab --dir docs/experiments/val-163 \
        [--report docs/experiments/val-163-number-registry-ab.md] [--csv PATH]

Refs: VAL-192 (N1), VAL-163
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from valinor.quality.narrator_metrics import (  # noqa: E402
    audit_hedging,
    collect_derived_candidates,
    collect_ground_truth,
    audit_numbers,
)

GOLDEN_PATH = ROOT / "evals" / "narrator_grounding" / "golden.yaml"
BASELINE_PATH = ROOT / "evals" / "narrator_grounding" / "baseline.json"

CONFIGS = ("default", "derived")

# Markers of a corrupted capture (today's lesson: CLI exit-1s and stubs must
# never be silently averaged into the A/B).
_BROKEN_MARKERS = ("Error: claude CLI error", "Narrator timed out", "*stubbed in live A/B")


# ═══════════════════════════════════════════════════════════════════════════
# GOLDEN MODE — instrument meta-eval
# ═══════════════════════════════════════════════════════════════════════════


def _buckets_match(actual: list[float], expected: list[float]) -> bool:
    if len(actual) != len(expected):
        return False
    a = sorted(round(float(v), 2) for v in actual)
    e = sorted(round(float(v), 2) for v in expected)
    return all(abs(x - y) <= max(0.01, abs(y) * 1e-6) for x, y in zip(a, e))


def _score_case(case: dict, config: str) -> tuple[bool, str]:
    """Run one golden case under one config. Returns (passed, detail)."""
    ctx = case.get("context") or {}
    registry = ctx.get("registry")
    vr = {"number_registry": registry} if registry else None
    findings = ctx.get("findings")
    query_results = ctx.get("query_results")

    truth = collect_ground_truth(vr, findings, query_results)
    derived = collect_derived_candidates(query_results) if config == "derived" else None
    audit = audit_numbers(case["text"], truth, derived_truth=derived)

    expect = case.get("expect", {})
    if config == "derived" and "expect_derived" in case:
        expect = case["expect_derived"]

    problems = []
    for bucket, actual in (
        ("grounded", audit.grounded_values),
        ("hallucinated", audit.ungrounded_values),
        ("declared", audit.declared_values),
    ):
        if not _buckets_match(actual, expect.get(bucket, [])):
            problems.append(f"{bucket}: got {sorted(actual)} want {sorted(expect.get(bucket, []))}")

    if "expect_hedging" in case:
        got = audit_hedging(case["text"]).count
        if got != case["expect_hedging"]:
            problems.append(f"hedging: got {got} want {case['expect_hedging']}")

    return (not problems, "; ".join(problems))


def run_golden(golden_path: Path = GOLDEN_PATH) -> dict:
    """Score the full golden set. Returns {config: {split: {passed, total, failures}}}."""
    cases = yaml.safe_load(golden_path.read_text(encoding="utf-8"))["cases"]
    results: dict = {}
    for config in CONFIGS:
        per_split: dict = {}
        for case in cases:
            split = case.get("split", "train")
            slot = per_split.setdefault(split, {"passed": 0, "total": 0, "failures": []})
            ok, detail = _score_case(case, config)
            slot["total"] += 1
            if ok:
                slot["passed"] += 1
            else:
                slot["failures"].append(f"{case['id']} [{detail}]")
        results[config] = per_split
    return results


def _accuracy(slot: dict) -> float:
    return slot["passed"] / slot["total"] if slot["total"] else 0.0


def print_golden_table(results: dict) -> None:
    print(f"{'config':10s} {'split':7s} {'passed':>7s} {'accuracy':>9s}")
    for config, per_split in results.items():
        for split in sorted(per_split):
            slot = per_split[split]
            print(f"{config:10s} {split:7s} {slot['passed']:4d}/{slot['total']:<3d} {_accuracy(slot):8.3f}")
    for config, per_split in results.items():
        for split, slot in per_split.items():
            for f in slot["failures"]:
                print(f"  FAIL [{config}/{split}] {f}")


def golden_main(args) -> int:
    results = run_golden(Path(args.golden))
    print_golden_table(results)

    gate_value = _accuracy(results["default"].get("test", {"passed": 0, "total": 0}))

    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps({
            "gate_metric": "case_accuracy/test/default",
            "value": round(gate_value, 4),
            "note": "updated deliberately via eval.py golden --update-baseline",
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nbaseline updated → {BASELINE_PATH} (value={gate_value:.4f})")
        return 0

    if args.gate:
        if not BASELINE_PATH.exists():
            print("\nGATE: no baseline committed — run --update-baseline first", file=sys.stderr)
            return 2
        baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        floor = baseline["value"]
        if gate_value < floor:
            print(f"\nGATE FAILED: test accuracy {gate_value:.4f} < baseline {floor:.4f}", file=sys.stderr)
            return 1
        print(f"\nGATE OK: test accuracy {gate_value:.4f} ≥ baseline {floor:.4f}")
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# AB MODE — multi-rep Number Registry A/B aggregation (VAL-163)
# ═══════════════════════════════════════════════════════════════════════════


def _is_broken(text: str) -> bool:
    # Empty/near-empty captures are corrupt too (seen live: CLI returned "" with
    # exit 0 on one rep) — averaging a 0-char output poisons the aggregate.
    return len(text.strip()) < 50 or any(marker in text for marker in _BROKEN_MARKERS)


def _score_branch_outputs(outputs: dict, dataset: dict) -> dict:
    """Score one branch of one rep → {narrator: metrics_dict}. Skips broken outputs."""
    from valinor.quality.narrator_metrics import score_narrator_output

    registry = {"number_registry": dataset.get("number_registry", {})}
    scored = {}
    for narrator, text in outputs.items():
        if _is_broken(text):
            continue
        m = score_narrator_output(
            text, registry, dataset.get("findings"), dataset.get("query_results")
        )
        scored[narrator] = {**m.to_dict(), "chars": len(text)}
    return scored


def run_ab(ab_dir: Path) -> dict:
    """Score every rep dir. Returns {rep: {branch: {narrator: metrics}}, ...}."""
    rep_dirs = sorted(d for d in ab_dir.glob("rep*") if d.is_dir())
    if not rep_dirs and (ab_dir / "control.json").exists():
        rep_dirs = [ab_dir]
    if not rep_dirs:
        raise SystemExit(f"no rep*/ dirs (or control.json) under {ab_dir}")

    reps: dict = {}
    dropped: list[str] = []
    for rd in rep_dirs:
        dataset = json.loads((rd / "dataset.json").read_text(encoding="utf-8"))
        rep_scores = {}
        for branch in ("control", "treatment"):
            outputs = json.loads((rd / f"{branch}.json").read_text(encoding="utf-8"))
            for narrator, text in outputs.items():
                if _is_broken(text) and "stubbed" not in text:
                    dropped.append(f"{rd.name}/{branch}/{narrator}")
            rep_scores[branch] = _score_branch_outputs(outputs, dataset)
        reps[rd.name] = rep_scores
    return {"reps": reps, "dropped": dropped}


def _collect_metric(reps: dict, branch: str, metric: str) -> dict[str, list[float]]:
    """{narrator: [value per rep]} for narrators present in every usable rep."""
    out: dict[str, list[float]] = {}
    for rep_scores in reps.values():
        for narrator, m in rep_scores.get(branch, {}).items():
            out.setdefault(narrator, []).append(m[metric])
    return out


def _mean_std(values: list[float]) -> str:
    if not values:
        return "—"
    if len(values) == 1:
        return f"{values[0]:.4f}"
    return f"{statistics.mean(values):.4f} ± {statistics.stdev(values):.4f}"


def build_ab_report(data: dict, n_reps: int) -> str:
    reps = data["reps"]
    lines = [
        "# VAL-163 — Number Registry A/B (control vs treatment)",
        "",
        f"Measured: {n_reps} reps per branch, narrators via local CLI "
        "(`scripts/run_capture_ab_live.py`), scored offline with the N1-fixed "
        "instrument (`scripts/eval.py ab`). Same captured pipeline state across "
        "branches and reps — the only varying factor is `verification_report`.",
        "",
        "## Aggregate (mean ± std across reps, per-narrator means)",
        "",
        "| Metric | Control | Treatment |",
        "|---|---|---|",
    ]
    for metric, label in (
        ("grounded_rate", "Grounded rate"),
        ("hallucinated_rate", "Hallucinated rate"),
        ("numbers_ungrounded", "Hallucinated numbers (count)"),
        ("numbers_declared", "Declared estimates (count)"),
        ("hedging_per_100_words", "Hedging / 100 words"),
        ("word_count", "Word count"),
    ):
        cells = []
        for branch in ("control", "treatment"):
            per_narr = _collect_metric(reps, branch, metric)
            per_rep_means: list[float] = []
            for i in range(n_reps):
                vals = [v[i] for v in per_narr.values() if len(v) > i]
                if vals:
                    per_rep_means.append(sum(vals) / len(vals))
            cells.append(_mean_std(per_rep_means))
        lines.append(f"| {label} | {cells[0]} | {cells[1]} |")

    lines += ["", "## Per narrator — grounded rate (mean ± std across reps)", "",
              "| Narrator | Control | Treatment |", "|---|---|---|"]
    narrators = sorted(
        set(_collect_metric(reps, "control", "grounded_rate"))
        | set(_collect_metric(reps, "treatment", "grounded_rate"))
    )
    for narrator in narrators:
        c = _collect_metric(reps, "control", "grounded_rate").get(narrator, [])
        t = _collect_metric(reps, "treatment", "grounded_rate").get(narrator, [])
        lines.append(f"| {narrator} | {_mean_std(c)} | {_mean_std(t)} |")

    if data["dropped"]:
        lines += ["", "## Dropped captures (corrupted — excluded from aggregates)", ""]
        lines += [f"- `{d}`" for d in data["dropped"]]

    lines.append("")
    return "\n".join(lines)


def write_ab_csv(path: str, data: dict) -> None:
    rows = []
    for rep, branches in data["reps"].items():
        for branch, scored in branches.items():
            for narrator, m in scored.items():
                rows.append({"rep": rep, "branch": branch, "narrator": narrator, **m})
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def ab_main(args) -> int:
    data = run_ab(Path(args.dir))
    n_reps = len(data["reps"])
    report = build_ab_report(data, n_reps)
    print(report)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
        print(f"\nreport → {args.report}", file=sys.stderr)
    if args.csv:
        write_ab_csv(args.csv, data)
        print(f"csv → {args.csv}", file=sys.stderr)
    return 0


# ═══════════════════════════════════════════════════════════════════════════
# GRAPHRAG MODE — N3 global-questions eval (VAL-192 N3)
# ═══════════════════════════════════════════════════════════════════════════


def graphrag_main(args) -> int:
    """Score the arm answers produced by scripts/graphrag_answer.py.

    Layer 0 (deterministic) always; --judge adds LLM-as-judge (reps, needs the
    console_cli bootstrap → only with --judge, CI runs layer 0 only). Gate per
    the N3 milestone: community ≥0.8 on ≥min-wins questions where flat <0.5,
    zero forbidden hits in the community arm.
    """
    import asyncio

    from valinor.quality.global_judge import evaluate_gate, judge_layer0, judge_layer1

    questions = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    active = {q["id"]: q for q in questions if q.get("status") != "replaced"}
    if args.split:
        active = {qid: q for qid, q in active.items() if q.get("split", "train") == args.split}
    references = json.loads(Path(args.references).read_text(encoding="utf-8"))
    base = Path(args.dir)
    arms = {}
    for arm in ("flat", "flat_narrator", "community"):
        p = base / f"{arm}.json"
        if p.exists():
            arms[arm] = json.loads(p.read_text(encoding="utf-8"))
    if "flat" not in arms or "community" not in arms:
        raise SystemExit(f"need flat.json + community.json under {base}")

    if args.judge:
        sys.path.insert(0, str(ROOT / "scripts"))
        from run_capture_ab_live import bootstrap
        bootstrap(args.judge_model, args.cli_path)

    rows = []
    per_question: dict[str, dict] = {}
    for qid, q in active.items():
        entry: dict = {}
        for arm, answers in arms.items():
            ans = answers.get(qid, "")
            l0 = judge_layer0(ans, q, references)
            score, forbidden = l0.score, l0.forbidden_hits
            if args.judge:
                # median over reps for BOTH splits — single-rep forbidden counts
                # oscillate ±1 (measured on train) and poison the gate margin.
                l1 = asyncio.run(judge_layer1(ans, q, references, reps=args.judge_reps))
                if l1["max_points"]:
                    score = l1["points"] / l1["max_points"]
                    forbidden = max(forbidden, l1["forbidden_hits"])
            rows.append({"question": qid, "split": q.get("split", "train"), "arm": arm,
                         "score": round(score, 3), "forbidden": forbidden,
                         "layer0": round(l0.score, 3), "detail": "; ".join(l0.details)[:120]})
            entry[arm] = score
            if arm == "community":
                entry["community_forbidden"] = forbidden
        per_question[qid] = entry

    print(f"{'question':28s} {'split':6s} {'flat':>6s} {'flat_nar':>8s} {'community':>9s} {'forb':>4s}")
    for qid, q in active.items():
        e = per_question[qid]
        fn = e.get("flat_narrator")
        print(f"{qid:28s} {q.get('split','train'):6s} {e['flat']:6.2f} "
              f"{(f'{fn:8.2f}' if fn is not None else '       —')} "
              f"{e['community']:9.2f} {e.get('community_forbidden', 0):4d}")

    gate = evaluate_gate(per_question, min_wins=args.min_wins)
    print(f"\nflat fails (<0.5): {gate['flat_fails']}")
    print(f"community wins (≥0.8, sin forbidden): {gate['wins']}")
    print(f"GATE ({'≥'+str(gate['min_wins'])} wins): {'PASSED' if gate['gate_passed'] else 'NOT PASSED'}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"csv → {args.csv}", file=sys.stderr)
    return 0 if (gate["gate_passed"] or not args.gate) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-192 eval harness (N1 golden/ab + N3 graphrag)")
    sub = ap.add_subparsers(dest="mode", required=True)

    g = sub.add_parser("golden", help="instrument meta-eval on the golden set")
    g.add_argument("--golden", default=str(GOLDEN_PATH))
    g.add_argument("--gate", action="store_true")
    g.add_argument("--update-baseline", action="store_true")

    a = sub.add_parser("ab", help="aggregate captured Number Registry A/B reps")
    a.add_argument("--dir", required=True)
    a.add_argument("--report", default=None)
    a.add_argument("--csv", default=None)

    r = sub.add_parser("graphrag", help="score N3 global-question arms (VAL-192 N3)")
    r.add_argument("--dir", required=True, help="dir with flat/flat_narrator/community.json")
    r.add_argument("--references", required=True)
    r.add_argument("--questions", default=str(ROOT / "evals" / "golden" / "global_questions.yaml"))
    r.add_argument("--split", default=None, choices=("train", "test"),
                   help="score one split only (train iteration / frozen test run)")
    r.add_argument("--judge", action="store_true", help="add LLM-as-judge layer (needs local CLI)")
    r.add_argument("--judge-reps", type=int, default=3)
    r.add_argument("--judge-model", default="haiku")
    r.add_argument("--cli-path", default=None)
    r.add_argument("--min-wins", type=int, default=5)
    r.add_argument("--gate", action="store_true", help="exit 1 if the N3 gate fails")
    r.add_argument("--csv", default=None)

    args = ap.parse_args(argv)
    if args.mode == "golden":
        return golden_main(args)
    if args.mode == "ab":
        return ab_main(args)
    return graphrag_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
