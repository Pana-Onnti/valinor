#!/usr/bin/env python3
"""
N5 enforcement A/B — does a citation directive lower the uncited-claims rate? (VAL-192)

Runs the Analyst agent TWICE over the SAME captured input (entity_map +
query_results + baseline), differing ONLY in the prompt:

  * control   — current prompt (rule "reference which query or table")
  * treatment — + a CITATION DIRECTIVE: cite the EXACT source query_id verbatim in
                `evidence`, or mark value_confidence=inferred if it doesn't trace.

Each arm's findings are verified (VerificationEngine) and scored with the N5
instrument (`score_agent_claims`). The delta in `uncited_rate` is the measured
effect of the enforcement. Both arms run the SAME model (Haiku via the local CLI
— Sonnet hangs on long prompts over the v2 CLI, documented) so the comparison is
controlled: only the prompt differs.

Analyst-only (the primary agent) as a representative datapoint; the directive
extends to sentinel/hunter once the lever is validated. Only aggregate numbers
are printed — no client rows.

Usage:
    venv/bin/python scripts/agent_citation_ab.py \
        --state docs/experiments/val-163/state.json \
        --model haiku --cli-path /tmp/claude-stable-v2

Refs: VAL-192 (N5 enforcement). Relates VAL-163 (the A/B method this mirrors).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "core"))


def bootstrap(model: str, cli_path: Optional[str]) -> None:
    """Install the console-CLI provider before any valinor agent import."""
    import os
    os.environ["LLM_PROVIDER"] = "console_cli"
    os.environ.setdefault("CLAUDE_PROXY_HOST", "localhost")
    os.environ["VALINOR_NARRATOR_MODEL"] = model
    os.environ["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = "32000"
    if cli_path:
        os.environ["CLAUDE_CLI_PATH"] = cli_path
    sys.modules.pop("claude_agent_sdk", None)
    from shared.llm.monkey_patch import apply_monkey_patch
    apply_monkey_patch()


async def warm_up(model: str) -> None:
    import claude_agent_sdk
    options = claude_agent_sdk.ClaudeAgentOptions(model=model, max_turns=1)
    async for msg in claude_agent_sdk.query(prompt="Reply with exactly: OK", options=options):
        for block in getattr(msg, "content", []):
            if getattr(block, "text", "").startswith("Error:"):
                raise SystemExit("warm-up failed — CLI bridge down")
    print("[warm-up] provider ready", flush=True)


def _treatment_directive(query_results: dict) -> str:
    results = query_results.get("results", query_results)
    keys = list(results.keys()) if isinstance(results, dict) else []
    keys_str = ", ".join(keys)
    return (
        "CITATION REQUIREMENT (obligatorio): en el campo `evidence` de CADA finding, "
        "citá TEXTUALMENTE el id EXACTO de la query fuente que produjo el número — "
        f"uno de estos ids: {keys_str}. Escribilo verbatim (ej. el id tal cual). "
        "Si el valor NO proviene de ninguna de esas queries, marcá "
        'value_confidence: "inferred" en vez de inventar una fuente.'
    )


def _score_arm(parsed_findings: list, query_results: dict, baseline: dict, kg) -> dict:
    from valinor.verification import VerificationEngine
    from valinor.quality.agent_grounding_metrics import score_agent_claims

    findings = {"analyst": {"findings": parsed_findings}}
    eng = VerificationEngine(query_results, baseline, kg)
    report = eng.verify_findings(findings)
    claims = []
    for f in parsed_findings:
        claims += eng._decompose_finding(f, "analyst")
        claims += eng._detect_temporal_claims(f, "analyst")
        claims += eng._detect_negative_claims(f, "analyst")
    audit = score_agent_claims(report.results, claims, findings=findings)
    return audit.to_dict()


async def run(args) -> int:
    from valinor.agents.analyst import run_analyst
    from valinor.knowledge_graph import build_knowledge_graph
    from valinor.verification import VerificationEngine

    state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    qr, em, bl = state["query_results"], state["entity_map"], state["baseline"]
    kg = build_knowledge_graph(em)

    await warm_up(args.model)
    directive = _treatment_directive(qr)
    _parse = VerificationEngine(qr, bl, kg)._parse_agent_findings

    arms = {"control": "", "treatment": directive}
    out: dict = {}
    for arm, cit in arms.items():
        t0 = time.time()
        raw = await run_analyst(qr, em, None, bl, kg=kg, model=args.model, citation_directive=cit)
        parsed = _parse(raw)
        audit = _score_arm(parsed, qr, bl, kg)
        out[arm] = {"findings": len(parsed), **audit}
        print(f"[{arm}] {len(parsed)} findings · {audit['total_claims']} claims · "
              f"uncited_rate={audit['uncited_rate']} · cited={audit['cited']} "
              f"uncited={audit['uncited']} declared={audit['declared_inference']} "
              f"({time.time() - t0:.0f}s)", flush=True)

    c, t = out["control"], out["treatment"]
    delta = round(t["uncited_rate"] - c["uncited_rate"], 4)
    print("\n=== N5 enforcement A/B (analyst, %s) ===" % args.model)
    print(f"control   uncited_rate = {c['uncited_rate']}  (cited {c['cited']}/{c['verifiable']})")
    print(f"treatment uncited_rate = {t['uncited_rate']}  (cited {t['cited']}/{t['verifiable']})")
    print(f"Δ uncited_rate = {delta}  ({'MEJORA' if delta < 0 else 'sin mejora' if delta == 0 else 'PEOR'})")

    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-192 N5 citation-directive A/B")
    ap.add_argument("--state", required=True)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--cli-path", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    bootstrap(args.model, args.cli_path)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
