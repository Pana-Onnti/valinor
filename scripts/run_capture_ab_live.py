#!/usr/bin/env python3
"""
VAL-163 live A/B runner — console-CLI bootstrap + N reps over one captured state.

scripts/capture_narrator_ab.py is the pure orchestrator (unit-tested offline);
this wrapper owns everything the LIVE run needs and that bit us before:

  * LLM provider bootstrap: LLM_PROVIDER=console_cli + shared.llm.monkey_patch
    BEFORE any valinor import (fresh process → no module reload dance needed).
  * Sequential warm-up query: provider init probes the `claude` CLI; concurrent
    probes from the narrator gather race and fail with "CLI not available".
  * Sales stub: reporte_ventas hits its timeout ceiling on every run (VAL-162
    known issue) — stubbed out so each branch doesn't burn narrator_timeout on it.
  * Model override: VALINOR_NARRATOR_MODEL (default haiku — local CLI, $0 API).
  * N reps for confidence intervals (issue DoD: 3 per branch). The CLI has no
    seed control; reps quantify sampling variance instead.

Usage (venv python has claude_agent_sdk; system python3 does not):
    venv/bin/python scripts/run_capture_ab_live.py \
        --state docs/experiments/val-163/state.json \
        --out-dir docs/experiments/val-163 \
        --reps 3 --model haiku \
        --only briefing_ceo,reporte_controller,reporte_ejecutivo

Writes out-dir/rep{i}/{control,treatment,dataset}.json — score each rep with
scripts/ab_test_number_registry.py. Refs: VAL-163, VAL-192
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))           # shared.*
sys.path.insert(0, str(ROOT / "core"))  # valinor.*
sys.path.insert(0, str(ROOT / "scripts"))


def bootstrap(model: str, cli_path: Optional[str] = None) -> None:
    """Install the console-CLI provider before any valinor import."""
    os.environ["LLM_PROVIDER"] = "console_cli"
    os.environ.setdefault("CLAUDE_PROXY_HOST", "localhost")
    os.environ["VALINOR_NARRATOR_MODEL"] = model
    # Verbose narrators (Haiku, unfiltered findings) blow past the CLI's 8192
    # output-token default and die with exit 1. NOTE: requires claude CLI ≥ 2.x —
    # 1.0.x ignores the env var (verified live: 1.0.98 caps at 8192 regardless;
    # 2.1.170 honors it). Pass --cli-path if `claude` on PATH is a 1.x.
    os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "32000"
    if cli_path:
        os.environ["CLAUDE_CLI_PATH"] = cli_path
    sys.modules.pop("claude_agent_sdk", None)
    from shared.llm.monkey_patch import apply_monkey_patch  # auto-applies on import

    apply_monkey_patch()


async def warm_up(model: str) -> None:
    """One sequential query so provider init never races the narrator gather."""
    import claude_agent_sdk

    t0 = time.time()
    options = claude_agent_sdk.ClaudeAgentOptions(model=model, max_turns=1)
    async for msg in claude_agent_sdk.query(prompt="Reply with exactly: OK", options=options):
        for block in getattr(msg, "content", []):
            text = getattr(block, "text", "")
            if text.startswith("Error:"):
                raise SystemExit(f"warm-up failed — CLI bridge down? {text[:200]}")
    print(f"[warm-up] provider ready in {time.time() - t0:.1f}s", flush=True)


def stub_sales() -> None:
    """Replace narrate_sales with an instant stub (VAL-162 known issue)."""
    import valinor.agents.narrators.sales as sales_mod

    async def _stubbed_sales(*args, **kwargs) -> str:
        return "# reporte_ventas\n\n*stubbed in live A/B (VAL-162 known issue)*"

    sales_mod.narrate_sales = _stubbed_sales
    print("[setup] reporte_ventas stubbed (VAL-162)", flush=True)


async def build_enriched_vr(state: dict):
    """VAL-192 N2 treatment2: stage-1 VR + generic registry enrichment +
    LLM rerank of UNVERIFIABLE claims (one batched call, deterministic confirm)."""
    from valinor.knowledge_graph import build_knowledge_graph
    from valinor.verification import VerificationEngine
    from valinor.verification_rerank import enrich_registry, rerank_unverifiable

    kg = build_knowledge_graph(state["entity_map"])
    eng = VerificationEngine(state["query_results"], state["baseline"], kg)
    report = eng.verify_findings(state["findings"])
    claims = {}
    for agent_name, agent_data in state["findings"].items():
        if agent_name.startswith("_") or not isinstance(agent_data, dict):
            continue
        for f in eng._parse_agent_findings(agent_data):
            for c in (eng._decompose_finding(f, agent_name)
                      + eng._detect_temporal_claims(f, agent_name)
                      + eng._detect_negative_claims(f, agent_name)):
                claims[c.claim_id] = c
    added = enrich_registry(report, state["query_results"])
    out = await rerank_unverifiable(report, state["query_results"], claims)
    print(f"[N2] registry +{added} → {len(report.number_registry)} | "
          f"rerank upgraded={len(out.upgraded)} rejected={len(out.rejected)} "
          f"disputed={len(out.disputed)} | verified={report.verified_claims}/"
          f"{report.total_claims}", flush=True)
    return report


async def run(args) -> int:
    # VAL-192 N3: --graphrag swaps in the graph-on/graph-off capture (treatment =
    # narrators WITH the deterministic graph context). Same live bridge + reps.
    if args.graphrag:
        from graphrag_narrator_ab import capture_graphrag_ab as capture_fn  # noqa: E402
    else:
        from capture_narrator_ab import capture_ab as capture_fn  # noqa: E402

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    only = {s.strip() for s in args.only.split(",")} if args.only else None

    await warm_up(args.model)
    if not args.keep_sales:
        stub_sales()

    build_vr_fn = None
    if args.enriched:
        vr2 = await build_enriched_vr(state)   # once; reps reuse it (deterministic input)
        build_vr_fn = lambda _s: vr2  # noqa: E731

    out_root = Path(args.out_dir)
    for rep in range(1, args.reps + 1):
        t0 = time.time()
        print(f"[rep {rep}/{args.reps}] running control + treatment…", flush=True)
        kwargs = {"build_vr_fn": build_vr_fn} if build_vr_fn else {}
        control, treatment, dataset = await capture_fn(state, only=only, **kwargs)

        rep_dir = out_root / f"rep{rep}"
        rep_dir.mkdir(parents=True, exist_ok=True)
        for name, payload in (
            ("control.json", control),
            ("treatment.json", treatment),
            ("dataset.json", dataset),
        ):
            (rep_dir / name).write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
        sizes = {k: len(v) for k, v in control.items()}
        print(
            f"[rep {rep}/{args.reps}] done in {time.time() - t0:.0f}s → {rep_dir} "
            f"(control chars: {sizes})",
            flush=True,
        )
    print("[all reps complete]", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-163 live A/B runner (console CLI)")
    ap.add_argument("--state", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--only", default="briefing_ceo,reporte_controller,reporte_ejecutivo")
    ap.add_argument("--keep-sales", action="store_true",
                    help="run the real sales narrator instead of the VAL-162 stub")
    ap.add_argument("--cli-path", default=None,
                    help="claude CLI binary (needs ≥2.x for the output-token override)")
    ap.add_argument("--enriched", action="store_true",
                    help="VAL-192 N2: treatment uses the enriched+reranked VR (treatment2)")
    ap.add_argument("--graphrag", action="store_true",
                    help="VAL-192 N3: treatment = narrators WITH the deterministic "
                         "graph context (vs without); both arms keep the registry")
    args = ap.parse_args(argv)

    bootstrap(args.model, args.cli_path)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
