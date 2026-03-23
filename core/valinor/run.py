"""
Valinor v0 — CLI Entry Point.

Usage:
    python -m valinor.run --client gloria --period Q2-2025
    python -m valinor.run --client nuevo --source /path/to/excel.xlsx --period 2025
"""

import asyncio
import argparse
import json
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from valinor.agents.cartographer import run_cartographer
from valinor.agents.query_builder import build_queries
from valinor.pipeline import (
    run_analysis_agents, execute_queries, run_narrators,
    compute_baseline, gate_calibration, reconcile_swarm,
)
from valinor.deliver import deliver_reports, build_memory
from valinor.gates import gate_cartographer, gate_analysis, gate_sanity, gate_monetary_consistency
from valinor.config import load_client_config, load_memory, parse_period
from valinor.quality.data_quality_gate import DataQualityGate

console = Console()


async def main(client: str, period: str, source: str | None = None):
    """Main pipeline execution."""
    run_start = time.time()
    run_log = {"client": client, "period": period, "stages": {}, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    # ═══ LOAD CONFIG ═══
    try:
        config = load_client_config(client, source=source)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]✗ Configuration error: {e}[/red]")
        return

    memory = load_memory(client)

    console.print(Panel(
        f"[bold cyan]Client:[/bold cyan] {config.get('display_name', client)}\n"
        f"[bold cyan]Period:[/bold cyan] {period}\n"
        f"[bold cyan]Source:[/bold cyan] {config.get('connection_string', config.get('source_path', 'unknown'))}\n"
        f"[bold cyan]Memory:[/bold cyan] {'loaded (' + memory.get('run_timestamp', '?') + ')' if memory else 'first run'}",
        title="⬡ VALINOR v0",
        border_style="cyan",
    ))

    # ═══ STAGE 0a: DATA QUALITY GATE ═══
    period_dates = parse_period(period)
    conn_string = config.get("connection_string", "")
    dq_report = None

    if conn_string and not config.get("source_path"):
        console.print("\n[bold]▸ Stage 0: Data Quality Gate...[/bold]")
        t0 = time.time()
        try:
            from sqlalchemy import create_engine
            dq_engine = create_engine(conn_string)
            dq_gate = DataQualityGate(
                engine=dq_engine,
                period_start=period_dates["start_date"],
                period_end=period_dates["end_date"],
                erp=config.get("erp", ""),
            )
            dq_report = dq_gate.run()
            dq_engine.dispose()
            stage_time = time.time() - t0

            run_log["stages"]["data_quality_gate"] = {
                "duration_s": round(stage_time, 1),
                "overall_score": dq_report.overall_score,
                "gate_decision": dq_report.gate_decision,
                "confidence_label": dq_report.confidence_label,
                "data_quality_tag": dq_report.data_quality_tag,
                "checks_passed": sum(1 for c in dq_report.checks if c.passed),
                "checks_total": len(dq_report.checks),
            }

            if dq_report.gate_decision == "HALT":
                console.print(f"[red]✗ Data Quality Gate HALTED — score {dq_report.overall_score:.0f}/100[/red]")
                for issue in dq_report.blocking_issues[:3]:
                    console.print(f"[red]  ↳ {issue}[/red]")
                return
            elif dq_report.gate_decision == "PROCEED_WITH_WARNINGS":
                console.print(
                    f"[yellow]⚠ DQ Gate: {dq_report.overall_score:.0f}/100 "
                    f"({dq_report.confidence_label})[/yellow]"
                )
            else:
                console.print(f"[green]✓ DQ Gate: {dq_report.overall_score:.0f}/100 ({dq_report.confidence_label})[/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ DQ Gate skipped: {e}[/yellow]")
            run_log["stages"]["data_quality_gate"] = {"skipped": True, "error": str(e)}

    # ═══ STAGE 0b: INTAKE (if Excel/CSV) ═══
    if config.get("source_path"):
        console.print("\n[bold]▸ Stage 0: Intake...[/bold]")
        source_path = config["source_path"]
        if source_path.endswith((".xlsx", ".xls")):
            from valinor.tools.excel_tools import excel_to_sqlite
            result = await excel_to_sqlite({"file_path": source_path, "client_name": client})
            console.print(f"  [green]✓[/green] Excel converted to SQLite")
        elif source_path.endswith(".csv"):
            from valinor.tools.excel_tools import csv_to_sqlite
            result = await csv_to_sqlite({"file_path": source_path, "client_name": client, "table_name": "data"})
            console.print(f"  [green]✓[/green] CSV converted to SQLite")

    # ═══ STAGE 1: CARTOGRAPHER (EXPLORE-VERIFY-COMMIT) ═══
    # Pattern: Reflexion retry loop — Guard Rail failures feed back to Cartographer
    # Phase 1 (deterministic): pre-scan discriminator columns, no LLM cost
    # Phase 2 (Sonnet): deep map with Phase 1 hints + optional retry feedback
    console.print("\n[bold]▸ Stage 1: Cartographer (Explore-Verify-Commit)...[/bold]")

    MAX_CARTOGRAPHER_RETRIES = 2
    calibration_feedback = None
    calibration = None
    entity_map = None

    for attempt in range(MAX_CARTOGRAPHER_RETRIES + 1):
        if attempt > 0:
            console.print(
                f"\n  [yellow]↻ Retry {attempt}/{MAX_CARTOGRAPHER_RETRIES} — "
                f"feeding Guard Rail failures back to Cartographer...[/yellow]"
            )
            for f in calibration_feedback:
                console.print(
                    f"  [yellow]  ↳ [{f['entity']}] {f['feedback'][:100]}[/yellow]"
                )

        t0 = time.time()
        entity_map = await run_cartographer(config, calibration_feedback=calibration_feedback)
        stage_time = time.time() - t0

        # Gate 1: enough entities? (no retry on this — structural problem)
        if not gate_cartographer(entity_map):
            console.print("[red]  ✗ Gate 1 FAILED: insufficient entity mapping[/red]")
            console.print(f"  Found: {list(entity_map.get('entities', {}).keys())}")
            console.print("  Need at least 2 of: customers, invoices, products, payments (confidence > 0.7)")
            return

        entities_list = list(entity_map.get("entities", {}).keys())
        prescan_meta = entity_map.get("_phase1_prescan", {})
        console.print(
            f"  [green]✓[/green] {len(entities_list)} entities mapped: {', '.join(entities_list)}"
            f" [dim](attempt {attempt + 1}, {stage_time:.1f}s,"
            f" {prescan_meta.get('tables_probed', 0)} tables pre-scanned)[/dim]"
        )

        # Stage 1.5: Guard Rail — verifies base_filter with real SQL COUNTs
        t1 = time.time()
        calibration = await gate_calibration(entity_map, config)
        calibration_time = time.time() - t1

        if calibration["passed"]:
            console.print(
                f"  [green]✓[/green] Guard Rail: {calibration['entities_verified']} entities verified"
                f" [dim]({calibration_time:.1f}s)[/dim]"
            )
            break  # Commit — entity_map is good

        # Guard Rail failed
        failures = calibration.get("failures", [])
        console.print(
            f"  [red]✗ Guard Rail: {len(failures)} base_filter issue(s) "
            f"[dim]({calibration_time:.1f}s)[/dim][/red]"
        )
        for failure in failures:
            console.print(
                f"  [red]  ↳ [{failure['entity']}] {failure['feedback'][:120]}[/red]"
            )

        if attempt >= MAX_CARTOGRAPHER_RETRIES:
            console.print(
                "[yellow]  ⚠ Max retries reached — continuing with unverified filters.\n"
                "  Agent findings may mix tenants or include cancelled records.[/yellow]"
            )
            break

        # Prepare feedback for next attempt (Reflexion: structured error → correction)
        calibration_feedback = failures

    # Log final calibration state
    run_log["stages"]["cartographer"] = {
        "duration_s": round(stage_time, 1),
        "entities_found": len(entity_map.get("entities", {})),
        "attempts": attempt + 1,
        "calibration_passed": calibration["passed"] if calibration else False,
        "entities_verified": calibration["entities_verified"] if calibration else 0,
        "failures": calibration.get("failures", []) if calibration else [],
        "warnings": [w.get("detail", "") for w in calibration.get("warnings", [])] if calibration else [],
    }

    if calibration and calibration.get("warnings"):
        for w in calibration["warnings"]:
            console.print(f"  [yellow]  ↳ {w.get('entity','?')}: {w.get('detail','')[:100]}[/yellow]")

    # ═══ STAGE 2: QUERY BUILDER ═══
    console.print("\n[bold]▸ Stage 2: Query Builder...[/bold]")
    period_config = parse_period(period)
    query_pack = build_queries(entity_map, period_config)
    console.print(
        f"  [green]✓[/green] {len(query_pack['queries'])} queries built, "
        f"{len(query_pack['skipped'])} skipped"
    )

    if query_pack["skipped"]:
        for skipped in query_pack["skipped"][:3]:
            console.print(f"  [dim]  ↳ Skipped {skipped['id']}: {skipped['reason']}[/dim]")

    # ═══ STAGE 2.5: EXECUTE QUERIES ═══
    console.print("\n[bold]▸ Stage 2.5: Executing queries...[/bold]")
    t0 = time.time()
    query_results = await execute_queries(query_pack, config)
    stage_time = time.time() - t0
    run_log["stages"]["queries"] = {
        "duration_s": round(stage_time, 1),
        "executed": len(query_results["results"]),
        "failed": len(query_results["errors"]),
    }
    console.print(
        f"  [green]✓[/green] {len(query_results['results'])} executed, "
        f"{len(query_results['errors'])} failed "
        f"[dim]({stage_time:.1f}s)[/dim]"
    )

    if query_results["errors"]:
        for qid, error in list(query_results["errors"].items())[:3]:
            console.print(f"  [yellow]  ↳ {qid}: {error['error'][:80]}[/yellow]")

    # Compute shared baseline from query results — prevents divergent EUR estimates
    baseline = compute_baseline(query_results)
    if baseline["data_available"]:
        rev = baseline["total_revenue"]
        customers = baseline["distinct_customers"]
        freshness = baseline["data_freshness_days"]
        console.print(
            f"  [cyan]Baseline:[/cyan] "
            f"revenue={f'€{rev:,.0f}' if rev else 'unknown'} | "
            f"customers={customers or 'unknown'} | "
            f"freshness={f'{freshness}d' if freshness else 'unknown'}"
        )
        if baseline.get("warning"):
            console.print(f"  [yellow]  ⚠ {baseline['warning']}[/yellow]")
    else:
        console.print("  [yellow]  ⚠ No baseline data — agents will estimate from schema only[/yellow]")

    # ═══ STAGE 3: PARALLEL AGENTS ═══
    # Inject DQ context into baseline so all agents see data quality status
    if dq_report:
        baseline["dq_score"] = dq_report.overall_score
        baseline["dq_confidence"] = dq_report.confidence_label
        baseline["dq_tag"] = dq_report.data_quality_tag
        baseline["dq_context"] = dq_report.to_prompt_context()

    console.print("\n[bold]▸ Stage 3: Analysis agents (parallel)...[/bold]")
    t0 = time.time()
    findings = await run_analysis_agents(query_results, entity_map, memory, baseline)
    stage_time = time.time() - t0
    run_log["stages"]["agents"] = {
        "duration_s": round(stage_time, 1),
        "agents_completed": list(findings.keys()),
    }

    # GATE 2: at least 2 agents produced findings?
    if not gate_analysis(findings):
        console.print("[yellow]  ⚠ Gate 2 WARNING: some agents failed, continuing with partial results[/yellow]")

    console.print(f"  [green]✓[/green] Agents completed: {', '.join(findings.keys())} [dim]({stage_time:.1f}s)[/dim]")

    # ═══ STAGE 3.5: RECONCILIATION NODE ═══
    # Pattern: Debate + Judge — Haiku arbiter resolves >2x numeric conflicts
    console.print("\n[bold]▸ Stage 3.5: Reconciliation...[/bold]")
    t0 = time.time()
    findings = await reconcile_swarm(findings, baseline)
    recon = findings.get("_reconciliation", {})
    run_log["stages"]["reconciliation"] = {
        "duration_s": round(time.time() - t0, 1),
        "conflicts_found": recon.get("conflicts_found", 0),
        "message": recon.get("message", ""),
    }
    if recon.get("conflicts_found", 0) > 0:
        console.print(
            f"  [yellow]⚠[/yellow] {recon['conflicts_found']} conflict(s) arbitrated"
            f" [dim]({run_log['stages']['reconciliation']['duration_s']}s)[/dim]"
        )
        for note in recon.get("notes", []):
            arb = note.get("arbitration", {})
            console.print(
                f"  [yellow]  ↳ {note['agents'][0]} vs {note['agents'][1]} "
                f"({note['domain']}): {note['ratio']}x gap → "
                f"selected €{arb.get('selected_value','?'):,} "
                f"[{arb.get('selected_agent','?')}][/yellow]"
            )
    else:
        console.print(
            f"  [green]✓[/green] No conflicts {recon.get('message', '')}"
            f" [dim]({run_log['stages']['reconciliation']['duration_s']}s)[/dim]"
        )

    # ═══ STAGE 4: NARRATORS ═══
    console.print("\n[bold]▸ Stage 4: Generating reports...[/bold]")
    t0 = time.time()
    reports = await run_narrators(findings, entity_map, memory, config, baseline, query_results)
    stage_time = time.time() - t0
    run_log["stages"]["narrators"] = {
        "duration_s": round(stage_time, 1),
        "reports_generated": list(reports.keys()),
    }
    console.print(f"  [green]✓[/green] {len(reports)} reports generated [dim]({stage_time:.1f}s)[/dim]")

    # ═══ STAGE 5: DELIVER ═══
    console.print("\n[bold]▸ Stage 5: Delivering...[/bold]")
    output_dir = Path(f"output/{client}/{period}")
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = await deliver_reports(reports, entity_map, findings, run_log, output_dir, query_results)

    # Save updated memory
    new_memory = build_memory(entity_map, findings, run_log, memory, baseline)
    memory_path = Path(f"memory/{client}/swarm_memory_{period}.json")
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(json.dumps(new_memory, indent=2, ensure_ascii=False), encoding="utf-8")

    # Sanity gate
    sanity = gate_sanity(reports, query_results)
    if not sanity["passed"]:
        console.print("[yellow]  ⚠ Sanity gate: some checks did not pass[/yellow]")
        for check in sanity["checks"]:
            if check["status"] == "warn":
                console.print(f"  [yellow]  ↳ {check['check']}: {check.get('reason', 'warning')}[/yellow]")

    # Monetary consistency gate
    consistency = gate_monetary_consistency(reports, baseline)
    if not consistency["passed"]:
        console.print("[yellow]  ⚠ Monetary consistency warnings:[/yellow]")
        for w in consistency["warnings"]:
            console.print(f"  [yellow]  ↳ [{w['report']}] {w['issue']}[/yellow]")
        run_log["monetary_consistency_warnings"] = consistency["warnings"]

    total_time = time.time() - run_start

    console.print(Panel(
        f"[bold green]Complete[/bold green] in {total_time:.0f}s\n\n"
        f"[bold]Output:[/bold] {output_dir}\n"
        f"[bold]Memory:[/bold] {memory_path}\n"
        f"[bold]Reports:[/bold]\n" +
        "\n".join(f"  • {name}: {len(content):,} chars" for name, content in reports.items()),
        title="⬡ VALINOR v0",
        border_style="green",
    ))


def cli():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="⬡ Valinor v0 — Business Intelligence Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m valinor.run --client gloria --period Q2-2025
  python -m valinor.run --client nuevo --source data.xlsx --period 2025
  python -m valinor.run --client demo --source report.csv --period Q1-2026
        """,
    )
    parser.add_argument("--client", required=True, help="Client name (matches directory in clients/)")
    parser.add_argument("--period", required=True, help="Period to analyze (Q1-2025, H1-2025, 2025)")
    parser.add_argument("--source", help="Path to Excel/CSV file (overrides DB connection)")
    args = parser.parse_args()

    asyncio.run(main(args.client, args.period, args.source))


if __name__ == "__main__":
    cli()
