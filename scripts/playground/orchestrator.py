#!/usr/bin/env python3
"""
Playground Orchestrator — Data generation + continuous testing swarm.

Usage:
    python scripts/playground/orchestrator.py                    # full swarm
    python scripts/playground/orchestrator.py --agents 3,9       # ERPForge + Smoker only
    python scripts/playground/orchestrator.py --dry-run           # validate agents
    python scripts/playground/orchestrator.py --cycles 2          # 2 cycles then stop
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Type

# Ensure the project root is on sys.path so absolute imports work when
# the script is invoked directly.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.playground.config import (
    API_BASE_URL,
    DATASETS_DIR,
    DB_CONFIG,
    MAX_CONCURRENT_JOBS,
    REPORTS_DIR,
)
from scripts.playground.agents.base import (
    AgentResult,
    PlaygroundAgent,
    PlaygroundContext,
)

# ── Agent registry ────────────────────────────────────────────────────
# Maps 1-based index to (module_path, class_name, tier).
AGENT_REGISTRY: Dict[int, Dict[str, str | None]] = {
    1:  {"module": "scripts.playground.agents.public_data_scout",    "cls": "PublicDataScoutAgent",      "tier": "hunter"},
    2:  {"module": "scripts.playground.agents.real_company_harvester","cls": "RealCompanyHarvesterAgent", "tier": "hunter"},
    3:  {"module": "scripts.playground.agents.erp_forge",            "cls": "ERPForgeAgent",             "tier": "generator"},
    4:  {"module": "scripts.playground.agents.industry_mimicker",    "cls": "IndustryMimickerAgent",     "tier": "generator"},
    5:  {"module": "scripts.playground.agents.edge_case_forge",      "cls": "EdgeCaseForgeAgent",        "tier": "generator"},
    6:  {"module": "scripts.playground.agents.bootstrap_resampler",  "cls": "BootstrapResamplerAgent",   "tier": "bootstrapper"},
    7:  {"module": "scripts.playground.agents.perturbation_engine",  "cls": "PerturbationEngineAgent",   "tier": "bootstrapper"},
    8:  {"module": "scripts.playground.agents.time_warp_generator",  "cls": "TimeWarpGeneratorAgent",    "tier": "bootstrapper"},
    9:  {"module": "scripts.playground.agents.pipeline_smoker",      "cls": "PipelineSmokerAgent",       "tier": "tester"},
    10: {"module": "scripts.playground.agents.quality_auditor",      "cls": "QualityAuditorAgent",       "tier": "tester"},
}

TIER_LABELS = {
    "hunter": "Hunter",
    "generator": "Generator",
    "bootstrapper": "Bootstrapper",
    "tester": "Tester",
}

# ── Helpers ────────────────────────────────────────────────────────────

def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Playground Orchestrator — data generation & testing swarm",
    )
    parser.add_argument(
        "--agents",
        type=str,
        default=None,
        help="Comma-separated agent numbers to run (e.g. 3,9). Default: all.",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of cycles for generators (0 = 1 for generators, infinite for testers).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate agent loading without executing any work.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args(argv)


def _resolve_agent_ids(raw: str | None) -> List[int]:
    """Parse --agents flag into a sorted list of agent IDs."""
    if raw is None:
        return sorted(AGENT_REGISTRY.keys())
    ids: List[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        n = int(token)
        if n not in AGENT_REGISTRY:
            raise ValueError(f"Unknown agent number: {n}. Valid: 1-{len(AGENT_REGISTRY)}")
        ids.append(n)
    return sorted(set(ids))


def _load_agent(agent_id: int) -> PlaygroundAgent:
    """Dynamically import and instantiate an agent by registry ID."""
    import importlib

    entry = AGENT_REGISTRY[agent_id]
    module_path = entry["module"]
    class_name = entry["cls"]
    assert isinstance(module_path, str) and isinstance(class_name, str)

    mod = importlib.import_module(module_path)
    cls: Type[PlaygroundAgent] = getattr(mod, class_name)
    return cls()


def _print_banner(agent_ids: List[int], dry_run: bool, cycles: int) -> None:
    """Print a startup banner showing active agents."""
    lines = [
        "",
        "=" * 60,
        "   PLAYGROUND SWARM — Data Generation & Testing",
        "=" * 60,
        "",
    ]
    if dry_run:
        lines.append("   MODE: DRY RUN (validation only)")
        lines.append("")

    for tier_key, tier_label in TIER_LABELS.items():
        tier_agents = [
            (aid, AGENT_REGISTRY[aid])
            for aid in agent_ids
            if AGENT_REGISTRY[aid]["tier"] == tier_key
        ]
        if not tier_agents:
            continue
        lines.append(f"   [{tier_label}]")
        for aid, entry in tier_agents:
            lines.append(f"     #{aid:>2}  {entry['cls']}")
        lines.append("")

    if cycles > 0:
        lines.append(f"   Cycles: {cycles}")
    else:
        lines.append("   Cycles: 1 (generators) / infinite (testers)")
    lines.append(f"   Max concurrent jobs: {MAX_CONCURRENT_JOBS}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("")
    print("\n".join(lines))


# ── Async runner ───────────────────────────────────────────────────────

async def _run_agent(
    agent: PlaygroundAgent,
    ctx: PlaygroundContext,
    cycles: int,
) -> AgentResult:
    """Run a single agent for the specified number of cycles.

    * Generators / hunters / bootstrappers: run *cycles* times (default 1).
    * Testers: delegate to ``run_continuous`` (respects stop_event).
    """
    if agent.tier == "tester":
        if cycles > 0:
            # Limited-cycle mode for testers
            for _ in range(cycles):
                if ctx.stop_event.is_set():
                    break
                result = await agent.run(ctx)
                if result.datasets:
                    for ds in result.datasets:
                        await ctx.generated_datasets.put(ds)
            return AgentResult(agent_name=agent.name, success=True, stats={"cycles": cycles})
        # Infinite mode
        await agent.run_continuous(ctx)
        return AgentResult(agent_name=agent.name, success=True)

    # Non-tester: run once (or N cycles)
    effective_cycles = cycles if cycles > 0 else 1
    last_result: AgentResult | None = None
    for _ in range(effective_cycles):
        if ctx.stop_event.is_set():
            break
        last_result = await agent.run(ctx)
        if last_result.datasets:
            for ds in last_result.datasets:
                await ctx.generated_datasets.put(ds)
    return last_result or AgentResult(agent_name=agent.name, success=True)


async def _orchestrate(args: argparse.Namespace) -> None:
    """Core orchestration loop."""
    agent_ids = _resolve_agent_ids(args.agents)
    _print_banner(agent_ids, args.dry_run, args.cycles)

    # Ensure output directories exist
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load agents
    agents: List[PlaygroundAgent] = []
    for aid in agent_ids:
        try:
            agent = _load_agent(aid)
            agents.append(agent)
            logging.getLogger("playground").info("Loaded agent #%d: %s", aid, agent.name)
        except (ImportError, AttributeError) as exc:
            logging.getLogger("playground").warning(
                "Could not load agent #%d (%s): %s", aid, AGENT_REGISTRY[aid]["cls"], exc
            )

    if not agents:
        logging.getLogger("playground").error("No agents loaded — nothing to do.")
        return

    if args.dry_run:
        print(f"\nDry-run complete. {len(agents)} agent(s) validated successfully.")
        return

    # Shared context
    stop_event = asyncio.Event()
    ctx = PlaygroundContext(
        datasets_dir=DATASETS_DIR,
        reports_dir=REPORTS_DIR,
        api_base_url=API_BASE_URL,
        db_config=DB_CONFIG,
        generated_datasets=asyncio.Queue(),
        stop_event=stop_event,
        logger=logging.getLogger("playground"),
    )

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # Launch agents with bounded concurrency
    sem = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    async def _guarded(agent: PlaygroundAgent) -> AgentResult:
        async with sem:
            return await _run_agent(agent, ctx, args.cycles)

    results = await asyncio.gather(
        *[_guarded(a) for a in agents],
        return_exceptions=True,
    )

    # ── Summary ────────────────────────────────────────────────────────
    total_datasets = 0
    total_errors = 0
    for r in results:
        if isinstance(r, BaseException):
            total_errors += 1
            logging.getLogger("playground").error("Agent crashed: %s", r)
        elif isinstance(r, AgentResult):
            total_datasets += len(r.datasets)
            total_errors += len(r.errors)

    print("\n" + "=" * 60)
    print("   SWARM SUMMARY")
    print("=" * 60)
    print(f"   Agents run       : {len(agents)}")
    print(f"   Datasets produced: {total_datasets}")
    print(f"   Queued datasets  : {ctx.generated_datasets.qsize()}")
    print(f"   Errors           : {total_errors}")
    print("=" * 60 + "\n")


# ── Entry-point ────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry-point."""
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(_orchestrate(args))


if __name__ == "__main__":
    main()
