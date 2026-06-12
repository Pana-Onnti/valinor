#!/usr/bin/env python3
"""
N3 GraphRAG offline runner — answer the global questions in all arms (VAL-192 N3).

Loads a captured pipeline state (VAL-163 format), builds the entity graph +
communities (deterministic), summarizes communities once, then answers every
active golden question per arm. No swarm re-run, no DB — the only LLM cost is
summaries + answers (Haiku via local CLI, same bootstrap as the VAL-163 runner).

    venv/bin/python scripts/graphrag_answer.py \
        --state evals/fixtures/state_demo.json \
        --questions evals/golden/global_questions.yaml \
        --out-dir docs/experiments/val-192-n3/demo \
        [--arms flat,flat_narrator,community] [--model haiku] [--cli-path ...]

Outputs: <out-dir>/{flat,flat_narrator,community}.json ({qid: answer}) and
dataset.json (graph stats, community map, seeds per question — audit trail).
Score with: venv/bin/python scripts/eval.py graphrag --dir <out-dir> --references <refs.json>

Refs: VAL-192
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_capture_ab_live import bootstrap, warm_up  # noqa: E402


async def run(args) -> int:
    from valinor.graphrag import build_entity_graph, detect_communities, select_seeds
    from valinor.agents.graph_global import (
        answer_flat,
        answer_global_question,
        summarize_communities,
    )

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    questions = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    active = [q for q in questions if q.get("status") != "replaced"]
    if args.split:
        active = [q for q in active if q.get("split", "train") == args.split]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        active = [q for q in active if q["id"] in wanted]
    arms = [a.strip() for a in args.arms.split(",")]

    await warm_up(args.model)

    graph = build_entity_graph(
        state["entity_map"], state["query_results"], state["baseline"],
        state["findings"],
    )
    communities = detect_communities(graph)
    n_comm = len({c for c in communities.values() if c >= 0})
    print(f"[graph] nodes={len(graph.nodes)} edges={len(graph.edges)} "
          f"communities={n_comm}", flush=True)

    summaries = {}
    if "community" in arms:
        t0 = time.time()
        summaries = await summarize_communities(graph, communities, state["client_config"])
        print(f"[summaries] {len(summaries)} communities in {time.time()-t0:.0f}s", flush=True)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n_samples = args.samples
    # With n_samples>1: answers[arm][qid] is a list; with n_samples==1: a string.
    answers: dict[str, dict] = {arm: {} for arm in arms}
    seeds_audit = {}

    for q in active:
        qid = q["id"]
        seeds_audit[qid] = sorted(select_seeds(q["question"], graph))
        for arm in arms:
            if n_samples > 1:
                sample_list: list[str] = []
                for k in range(n_samples):
                    t0 = time.time()
                    if arm == "community":
                        ans = await answer_global_question(
                            q["question"], graph, communities, summaries,
                            None, state["client_config"])
                    else:
                        ans = await answer_flat(
                            q["question"], state, state["client_config"],
                            include_raw_rows=(arm == "flat"))
                    elapsed = time.time() - t0
                    print(f"[{qid}] {arm} sample {k+1}/{n_samples}: {len(ans)} chars ({elapsed:.0f}s)", flush=True)
                    sample_list.append(ans)
                answers[arm][qid] = sample_list
            else:
                t0 = time.time()
                if arm == "community":
                    ans = await answer_global_question(
                        q["question"], graph, communities, summaries,
                        None, state["client_config"])
                else:
                    ans = await answer_flat(
                        q["question"], state, state["client_config"],
                        include_raw_rows=(arm == "flat"))
                answers[arm][qid] = ans
                print(f"[{qid}] {arm}: {len(ans)} chars ({time.time()-t0:.0f}s)", flush=True)

    for arm in arms:
        (out / f"{arm}.json").write_text(
            json.dumps(answers[arm], indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "dataset.json").write_text(json.dumps({
        "graph": {"nodes": len(graph.nodes), "edges": len(graph.edges),
                  "communities": n_comm,
                  "community_sizes": {str(c): sum(1 for v in communities.values() if v == c)
                                      for c in sorted(set(communities.values()))}},
        "seeds_per_question": seeds_audit,
        "summaries": summaries,
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[done] → {out}", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-192 N3 GraphRAG answer runner")
    ap.add_argument("--state", required=True)
    ap.add_argument("--questions", default="evals/golden/global_questions.yaml")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--arms", default="flat,flat_narrator,community")
    ap.add_argument("--split", default=None, choices=("train", "test"),
                    help="iterate on train only; test stays frozen until the final run")
    ap.add_argument("--only", default=None, help="comma-separated question ids")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--cli-path", default=None)
    ap.add_argument("--samples", type=int, default=1,
                    help="N>1: generate each answer N times; output saves a list per qid")
    args = ap.parse_args(argv)
    bootstrap(args.model, args.cli_path)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
