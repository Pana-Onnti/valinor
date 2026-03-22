"""
Cartographer Agent — Stage 1: Schema Discovery.

Phase 1 (deterministic): Pre-scan for discriminator columns using probe_column_values.
  Schema-Then-Data pattern — zero LLM cost, discovers tenant IDs and filter flags.

Phase 2 (Sonnet): Deep entity map with Phase 1 hints injected.
  Explore-Verify-Commit: accepts calibration_feedback for retry loop.

Pattern references:
  - ReFoRCE Column Exploration (arxiv:2502.00675)
  - Reflexion self-correction (arxiv:2303.11366)
  - Schema-Then-Data phasing (Anthropic harness)
"""

import json
import logging
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    create_sdk_mcp_server,
)

from valinor.tools.db_tools import (
    connect_database,
    introspect_schema,
    sample_table,
    classify_entity,
    probe_column_values,
)
from valinor.tools.memory_tools import write_artifact

logger = logging.getLogger(__name__)

# Path to the cartographer skill
SKILL_PATH = Path(__file__).parent.parent.parent / ".claude" / "skills" / "cartographer.md"

# Column name patterns that signal tenant/direction/status discriminators
_DISCRIMINATOR_PATTERNS = [
    "ad_client_id", "client_id", "tenant_id", "company_id",
    "issotrx", "isreceipt", "ispurchase", "issales",
    "docstatus", "processed", "isactive", "cancelled",
    "ad_org_id", "org_id",
]

# Table name hints — only probe these for discriminators (keeps Phase 1 fast)
_BUSINESS_TABLE_HINTS = [
    "invoice", "payment", "order", "customer", "bpartner",
    "partner", "product", "shipment", "receipt", "factura",
]


async def _prescan_filter_candidates(client_config: dict) -> dict:
    """
    Phase 1: Deterministic pre-scan — discovers discriminator column values.

    Connects to DB, finds tables with business-entity names, probes columns
    matching known discriminator patterns.  No LLM involved.

    Returns:
        {
          "candidate_hints": {
            "c_invoice": {
              "ad_client_id": [{"value": "1000000", "count": 45234}, ...],
              "issotrx":      [{"value": "Y", "count": 30100}, ...],
            },
            ...
          },
          "error": "..." (only on failure)
        }
    """
    from sqlalchemy import create_engine, inspect
    from sqlalchemy import text as sa_text

    candidate_hints: dict = {}

    try:
        engine = create_engine(client_config["connection_string"])
        inspector = inspect(engine)

        # Detect schema: prefer 'public' (PostgreSQL) fall back to first available
        available_schemas = inspector.get_schema_names()
        db_schema = "public" if "public" in available_schemas else available_schemas[0]

        all_tables = inspector.get_table_names(schema=db_schema)

        # Only probe tables with business-entity names
        target_tables = [
            t for t in all_tables
            if any(h in t.lower() for h in _BUSINESS_TABLE_HINTS)
        ][:6]  # cap at 6 tables to keep Phase 1 fast

        for table in target_tables:
            try:
                col_names = [
                    c["name"] for c in inspector.get_columns(table, schema=db_schema)
                ]
            except (KeyError, TypeError, OSError) as exc:
                logger.warning("cartographer prescan: failed to get columns for table %s", table, exc_info=exc)
                continue

            # Find columns matching discriminator patterns (case-insensitive)
            matches = [
                c for c in col_names
                if any(p in c.lower() for p in _DISCRIMINATOR_PATTERNS)
            ][:4]  # max 4 discriminator cols per table

            if not matches:
                continue

            table_hints: dict = {}
            # Batch all discriminator probes into a single UNION ALL query
            union_parts = []
            for col in matches:
                union_parts.append(
                    f"(SELECT '{col}' AS col_name, \"{col}\"::text AS val, "
                    f'COUNT(*) AS cnt '
                    f'FROM "{db_schema}"."{table}" '
                    f"GROUP BY 2 ORDER BY cnt DESC LIMIT 10)"
                )
            batch_sql = " UNION ALL ".join(union_parts)
            try:
                with engine.connect() as conn:
                    result = conn.execute(sa_text(batch_sql))
                    for row in result.fetchall():
                        col_name, val, cnt = row[0], row[1], row[2]
                        table_hints.setdefault(col_name, []).append(
                            {"value": str(val), "count": cnt}
                        )
            except (OSError, TypeError, ValueError) as exc:
                logger.warning("cartographer prescan: failed to probe table %s", table, exc_info=exc)

            if table_hints:
                candidate_hints[table] = table_hints

        engine.dispose()

    except Exception as e:
        return {"error": str(e), "candidate_hints": {}}

    return {"candidate_hints": candidate_hints}


def _format_phase1_hints(prescan: dict) -> str:
    """Format Phase 1 pre-scan results as a prompt section."""
    hints = prescan.get("candidate_hints", {})
    if not hints:
        return ""

    lines = [
        "\n## PHASE 1 PRE-SCAN — Discriminator Columns Discovered",
        "These column value distributions were found BEFORE you started.",
        "Use them to construct precise base_filter values (DO NOT guess — the data is here):\n",
    ]

    for table, cols in hints.items():
        lines.append(f"### {table}")
        for col, values in cols.items():
            top = ", ".join(
                f"'{v['value']}'={v['count']:,}" for v in values[:5]
            )
            lines.append(f"  {col}: [{top}]")
        lines.append("")

    lines.append(
        "ACTION: For each entity's base_filter, use the dominant values above.\n"
        "Example: if issotrx has Y=30100 and N=15134 → set base_filter to include issotrx='Y'\n"
    )

    return "\n".join(lines)


def _format_calibration_feedback(failures: list) -> str:
    """Format Guard Rail calibration failures as retry instructions."""
    if not failures:
        return ""

    lines = [
        "\n## ⚠ CALIBRATION FEEDBACK — Fix These Before Writing entity_map",
        "The Guard Rail ran real SQL COUNT checks and found these problems.",
        "YOU MUST fix the base_filter for each failing entity:\n",
    ]

    for f in failures:
        entity = f.get("entity", "?")
        feedback = f.get("feedback", "")
        lines.append(f"- [{entity}] {feedback}")
        lines.append(
            f"  → Use probe_column_values on {entity}'s table to verify actual filter values.\n"
        )

    return "\n".join(lines)


async def run_cartographer(
    client_config: dict,
    calibration_feedback: list | None = None,
) -> dict:
    """
    Run the Cartographer agent to map a database schema.

    Phase 1 (deterministic): Pre-scan discriminator columns — no LLM cost.
    Phase 2 (Sonnet): Deep entity map with Phase 1 hints + optional retry feedback.

    Args:
        client_config: Client configuration dict with connection_string, name, etc.
        calibration_feedback: List of Guard Rail failures from a previous attempt.
            Each item: {"entity": "invoices", "feedback": "filtered_count is 0 ..."}
            When provided, Cartographer is instructed to fix these specific entities.

    Returns:
        entity_map dict with discovered entities, relationships, base_filter, and quality flags.
    """
    # ── Phase 1: Deterministic pre-scan ──────────────────────────────────────
    prescan = await _prescan_filter_candidates(client_config)
    phase1_section = _format_phase1_hints(prescan)

    # ── Build prompt ──────────────────────────────────────────────────────────
    retry_section = ""
    if calibration_feedback:
        retry_section = _format_calibration_feedback(calibration_feedback)

    skill_content = ""
    if SKILL_PATH.exists():
        skill_content = SKILL_PATH.read_text(encoding="utf-8")

    prompt = f"""
    Client: {client_config['name']}
    Connection: {client_config['connection_string']}
    {phase1_section}
    {retry_section}

    Map this database. Discover all entities. Classify each table.
    Output: Use the `write_artifact` tool to write the `entity_map.json` mapping.

    Rules:
    - NEVER assume what a table is by its name. Sample 5 rows first.
    - Classify: MASTER / TRANSACTIONAL / CONFIG / BRIDGE
    - Identify the key business entities: customers, products, invoices, payments
    - For each entity: table name, key columns, row count, confidence score
    - For each entity: set base_filter using Phase 1 pre-scan data (or probe_column_values if unsure)
    - Flag any quality issues you notice during sampling
    - Client name for artifacts: {client_config['name']}
    - Period for artifacts: discovery
    """

    overrides = client_config.get("overrides", {})
    if overrides:
        prompt += "\n\n    HINTS from client config (verify, don't blindly trust):\n"
        for key, value in overrides.items():
            prompt += f"    - {key}: {value}\n"

    # ── Phase 2: Sonnet deep map ──────────────────────────────────────────────
    tools_server = create_sdk_mcp_server(
        name="cartographer-tools",
        version="1.0.0",
        tools=[
            connect_database,
            introspect_schema,
            sample_table,
            classify_entity,
            probe_column_values,  # Phase 3: ReFoRCE Column Exploration
            write_artifact,
        ],
    )

    options = ClaudeAgentOptions(
        model="sonnet",
        system_prompt=skill_content,
        max_turns=35,  # extra turns for probe_column_values calls
        mcp_servers={
            "tools": tools_server,
        },
        allowed_tools=[
            "mcp__tools__connect_database",
            "mcp__tools__introspect_schema",
            "mcp__tools__sample_table",
            "mcp__tools__classify_entity",
            "mcp__tools__probe_column_values",
            "mcp__tools__write_artifact",
        ],
        permission_mode="acceptEdits",
    )

    last_text = ""

    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        last_text = block.text
    except Exception as e:
        print(f"\n[INFO] Agent finished with SDK exit code: {str(e)}")

    # Read from disk where write_artifact would have saved it
    artifact_path = Path(f"output/{client_config['name']}/discovery/entity_map.json")
    if artifact_path.exists():
        try:
            entity_map = json.loads(artifact_path.read_text(encoding="utf-8"))
            # Attach prescan metadata for diagnostics
            entity_map["_phase1_prescan"] = {
                "tables_probed": len(prescan.get("candidate_hints", {})),
                "retry_attempt": bool(calibration_feedback),
            }
            return entity_map
        except json.JSONDecodeError as exc:
            logger.warning("cartographer: failed to parse entity_map artifact", exc_info=exc)

    print(f"\n[DEBUG] Agent Last Text Payload POST-LOOP: {last_text}")
    return {
        "client": client_config["name"],
        "status": "partial",
        "entities": {},
        "note": "Failed to read entity_map.json artifact. Last response: " + last_text[:500],
    }
