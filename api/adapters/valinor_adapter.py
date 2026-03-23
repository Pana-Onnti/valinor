"""
Valinor Adapter - Wrapper around v0 CLI functionality for SaaS.
Preserves all original functionality while adding SaaS capabilities.
"""

import copy
import os
import sys
import json
import re
import asyncio
import tempfile  # noqa: F401
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from datetime import datetime
import structlog

# ── CRITICAL: patch claude_agent_sdk BEFORE any core imports ──────────────────
# The core agents do `from claude_agent_sdk import query` at module load time.
# We must replace sys.modules['claude_agent_sdk'] first so those imports
# resolve to our provider-switching shim instead of the real SDK.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))  # shared/

os.environ.setdefault("LLM_PROVIDER", "console_cli")

from shared.llm.monkey_patch import apply_monkey_patch  # noqa: E402
apply_monkey_patch()
# ──────────────────────────────────────────────────────────────────────────────

from api.adapters.exceptions import (  # noqa: E402, F401
    ValinorError,
    SSHConnectionError,
    DatabaseConnectionError,
    PipelineTimeoutError,
    DQGateHaltError,
)

# Import original Valinor components (unchanged) — NOW safe to import
from valinor.config import load_client_config, parse_period  # noqa: E402, F401
from valinor.agents.cartographer import run_cartographer  # noqa: E402, F401
from valinor.agents.query_builder import build_queries  # noqa: E402
from valinor.pipeline import run_analysis_agents, execute_queries, compute_baseline  # noqa: E402
from valinor.agents.narrators.executive import narrate_executive  # noqa: E402
from valinor.deliver import deliver_reports  # noqa: E402
from valinor.gates import gate_cartographer, gate_analysis  # noqa: E402

from shared.ssh_tunnel import create_ssh_tunnel, ZeroTrustValidator  # noqa: E402
from shared.storage import MetadataStorage  # noqa: E402
from shared.memory.profile_store import get_profile_store  # noqa: E402
from shared.memory.profile_extractor import get_profile_extractor  # noqa: E402
from shared.webhook_dispatcher import WebhookDispatcher, create_webhook_payload  # noqa: E402
from api.refinement.prompt_tuner import PromptTuner  # noqa: E402
from api.refinement.focus_ranker import FocusRanker  # noqa: E402
from api.refinement.refinement_agent import RefinementAgent  # noqa: E402
from api.refinement.query_evolver import QueryEvolver  # noqa: E402
from shared.memory.industry_detector import IndustryDetector  # noqa: E402
from shared.memory.adaptive_context_builder import build_adaptive_context  # noqa: E402
from shared.memory.segmentation_engine import get_segmentation_engine  # noqa: E402
from core.valinor.quality.currency_guard import get_currency_guard  # noqa: E402
from core.valinor.quality.data_quality_gate import DataQualityGate  # noqa: E402
from core.valinor.quality.provenance import ProvenanceRegistry  # noqa: E402
from shared.llm.token_tracker import TokenTracker  # noqa: E402

logger = structlog.get_logger()

try:
    from api.metrics import JOBS_TOTAL, ACTIVE_JOBS, ANALYSIS_COST_USD, DQ_CHECKS_TOTAL  # noqa: F401
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False


class ValinorAdapter:
    """
    Adapter that exposes Valinor v0 functionality for SaaS usage.
    Zero modifications to core Valinor code - pure wrapper pattern.
    """

    def __init__(self, progress_callback: Optional[Callable] = None):
        """
        Initialize Valinor adapter.

        Args:
            progress_callback: Async function to call with progress updates
                              Signature: async def callback(stage: str, progress: int, message: str)
        """
        self.progress_callback = progress_callback
        self.metadata_storage = MetadataStorage()
        self.zero_trust = ZeroTrustValidator()
        self.profile_store = get_profile_store()
        self.profile_extractor = get_profile_extractor()
        self.prompt_tuner = PromptTuner()
        self.focus_ranker = FocusRanker()
        self.industry_detector = IndustryDetector()
        self.segmentation_engine = get_segmentation_engine()
        self.query_evolver = QueryEvolver()

    async def run_analysis(
        self,
        job_id: str,
        client_name: str,
        connection_config: Dict[str, Any],
        period: str,
        options: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Run complete Valinor analysis pipeline with SaaS enhancements.

        Args:
            job_id: Unique job identifier
            client_name: Client name for tracking
            connection_config: Database and SSH configuration
                - ssh_config: SSH tunnel parameters
                - db_config: Database connection parameters
            period: Analysis period (Q1-2025, H1-2025, 2025)
            options: Additional options (timeout, debug mode, etc.)

        Returns:
            Analysis results dictionary
        """
        start_time = datetime.utcnow()
        results = {
            "job_id": job_id,
            "client_name": client_name,
            "period": period,
            "status": "started",
            "started_at": start_time.isoformat(),
            "stages": {}
        }

        # Reset token counters so this run starts from zero
        TokenTracker.get_instance().reset()

        if _METRICS_AVAILABLE:
            ACTIVE_JOBS.inc()

        try:
            # Validate configurations
            await self._progress("validating", 5, "Validating configurations...")

            ssh_config = connection_config.get('ssh_config')
            db_config = connection_config.get('db_config', {})

            # Build connection string first so validator has it
            db_host = db_config.get('host', 'localhost')
            db_port = db_config.get('port', 5432)
            db_name = db_config.get('name') or db_config.get('database', '')
            db_user = db_config.get('user', '')
            db_pass = db_config.get('password', '')
            db_type = db_config.get('type', 'postgresql')
            conn_str = db_config.get('connection_string')
            if not conn_str:
                pg_type = 'postgresql' if db_type in ('postgresql', 'postgres') else db_type
                conn_str = f"{pg_type}://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
            # API runs with network_mode: host — localhost inside the container
            # IS the host's localhost. No port remapping needed.
            db_config['connection_string'] = conn_str

            if ssh_config and not self.zero_trust.validate_ssh_config(ssh_config):
                raise ValueError("Invalid SSH configuration")

            if not self.zero_trust.validate_db_config(db_config):
                raise ValueError("Invalid database configuration")

            # Store job metadata (no sensitive data)
            await self.metadata_storage.store_job_metadata(job_id, {
                "client_name": client_name,
                "period": period,
                "config_hash": self._hash_config(connection_config)
            })

            await self._progress("connecting", 10, "Establishing connection...")

            if ssh_config:
                # Use SSH tunnel
                with create_ssh_tunnel(
                    ssh_host=ssh_config.get('host'),
                    ssh_user=ssh_config.get('username') or ssh_config.get('user'),
                    ssh_key_path=ssh_config.get('private_key_path'),
                    db_host=db_host,
                    db_port=db_port,
                    connection_string=conn_str,
                    job_id=job_id
                ) as tunneled_connection:
                    temp_config = self._create_temp_config(client_name, tunneled_connection, connection_config)
                    pipeline_results = await self._run_pipeline_with_progress(temp_config, period, job_id)
            else:
                # Direct connection (no SSH tunnel)
                temp_config = self._create_temp_config(client_name, conn_str, connection_config)
                pipeline_results = await self._run_pipeline_with_progress(temp_config, period, job_id)

            results["stages"] = pipeline_results["stages"]
            results["findings"] = pipeline_results.get("findings", {})
            results["reports"] = pipeline_results.get("reports", {})
            results["run_delta"] = pipeline_results.get("run_delta", {})

            # Calculate execution time
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            results["execution_time_seconds"] = execution_time
            results["status"] = "completed"
            results["completed_at"] = datetime.utcnow().isoformat()

            # Cost estimation: base $8 + $2 per agent call (Sonnet ~2600 tokens/call)
            _findings = results.get("findings", {})
            _num_agents = len(_findings) if isinstance(_findings, dict) else 3
            results["estimated_cost_usd"] = round(0.008 + (_num_agents * 0.002), 3)

            # Store results metadata (no client data)
            await self.metadata_storage.store_job_results(job_id, {
                "findings_count": len(results.get("findings", {})),
                "execution_time": execution_time,
                "success": True
            })

            await self._progress("completed", 100, f"Analysis completed in {execution_time:.1f} seconds")

            if _METRICS_AVAILABLE:
                ACTIVE_JOBS.dec()
                JOBS_TOTAL.labels(status="completed").inc()
                ANALYSIS_COST_USD.inc(results.get("estimated_cost_usd", 0))

            return results

        except Exception as _raw_exc:
            # ── Categorize raw exceptions into structured error types ─────────
            e: Exception = _raw_exc
            if not isinstance(_raw_exc, ValinorError):
                error_msg = str(_raw_exc)
                if any(kw in error_msg for kw in ("SSH", "Connection refused", "Authentication")):
                    e = SSHConnectionError(error_msg)
                elif any(kw in error_msg.lower() for kw in ("timeout", "timed out")):
                    e = PipelineTimeoutError(error_msg)
                elif "DQ" in error_msg and "HALT" in error_msg:
                    _score_match = re.search(r"score=(\d+(?:\.\d+)?)", error_msg)
                    _dq_score = float(_score_match.group(1)) if _score_match else None
                    e = DQGateHaltError(error_msg, dq_score=_dq_score, gate_decision="HALT")

            logger.error(
                "Analysis failed",
                job_id=job_id,
                client=client_name,
                error=str(e),
                error_type=type(e).__name__,
            )

            results["status"] = "failed"
            results["error"] = str(e)
            results["error_type"] = type(e).__name__
            results["failed_at"] = datetime.utcnow().isoformat()

            if _METRICS_AVAILABLE:
                ACTIVE_JOBS.dec()
                JOBS_TOTAL.labels(status="failed").inc()

            # Store failure metadata (including structured error type)
            await self.metadata_storage.store_job_results(job_id, {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
            })

            await self._progress("failed", -1, f"Analysis failed: {str(e)}")

            raise e

    async def _run_direct_cartographer(self, config: Dict) -> Dict:
        """
        Direct cartographer — bypasses the agent loop.

        Instead of running Claude as an agent with MCP tools, we:
        1. Introspect the DB schema directly in Python (SQLAlchemy)
        2. Run the Phase-1 pre-scan from core (deterministic, no LLM)
        3. Call the LLM once with full schema + pre-scan data
        4. Parse the returned JSON into entity_map format

        This works with any LLM provider (console_cli, anthropic_api, mock)
        and does not require the claude_agent_sdk agent loop.
        """
        from sqlalchemy import create_engine, inspect, text as sa_text
        from valinor.agents.cartographer import _prescan_filter_candidates

        conn_str = config["connection_string"]
        logger.info("Direct cartographer starting", conn_str_preview=conn_str[:60])

        # ── Step 1: introspect schema — prioritize business tables ───────────
        # Keywords that identify business/transactional tables in Openbravo ERPs
        _BUSINESS_HINTS = [
            "invoice", "payment", "order", "customer", "bpartner",
            "partner", "product", "shipment", "receipt", "factura",
            "cashline", "fin_payment", "c_invoice", "c_order", "c_bpartner",
            "m_product", "m_inout",
        ]
        schema_info: Dict[str, Any] = {}
        try:
            engine = create_engine(conn_str)
            inspector = inspect(engine)
            all_tables = inspector.get_table_names(schema="public")
            logger.info("Schema tables found", count=len(all_tables))

            # Prioritize tables with business-entity names
            priority = [t for t in all_tables if any(h in t.lower() for h in _BUSINESS_HINTS)]
            rest = [t for t in all_tables if t not in priority]
            ordered = priority[:50] + rest[:10]  # up to 60 total, business first

            for table in ordered:
                try:
                    cols = [c["name"] for c in inspector.get_columns(table, schema="public")]
                    with engine.connect() as conn:
                        rc = conn.execute(
                            sa_text(f'SELECT COUNT(*) FROM "public"."{table}"')
                        ).scalar()
                    schema_info[table] = {"columns": cols, "row_count": int(rc or 0)}
                except Exception:
                    pass
            engine.dispose()
            logger.info("Schema introspection done", tables_captured=len(schema_info),
                        priority_tables=len(priority))
        except Exception as e:
            logger.warning("Schema introspection failed", error=str(e))

        # ── Step 2: Phase-1 pre-scan (discriminator columns) ────────────────
        prescan = await _prescan_filter_candidates(config)

        # ── Step 3: LLM classification call ─────────────────────────────────
        from shared.llm.monkey_patch import _interceptor
        from shared.llm.base import LLMOptions, ModelType

        prompt = f"""You are a database analyst. Analyze the following schema and identify the key business entities.

Database tables and columns:
{json.dumps(schema_info, indent=2)}

Pre-scan discriminator column distributions:
{json.dumps(prescan.get("candidate_hints", {}), indent=2)}

Return ONLY a valid JSON object (no markdown, no explanation) with this exact structure:
{{
  "entities": {{
    "customers": {{
      "table": "<actual_table_name>",
      "confidence": 0.95,
      "base_filter": "AND <filter_condition>",
      "key_columns": {{
        "customer_pk": "<pk_column_name>",
        "customer_name": "<name_column_name>",
        "customer_fk": "<fk_column_used_in_invoices>"
      }}
    }},
    "invoices": {{
      "table": "<actual_table_name>",
      "confidence": 0.95,
      "base_filter": "AND <filter_condition>",
      "key_columns": {{
        "invoice_pk": "<pk_column_name>",
        "invoice_date": "<date_column_name>",
        "amount_col": "<total_amount_column>",
        "customer_fk": "<customer_fk_column>"
      }}
    }},
    "payments": {{
      "table": "<actual_table_name>",
      "confidence": 0.85,
      "base_filter": "AND <filter_condition>",
      "key_columns": {{
        "outstanding_amount": "<outstanding_amount_column>",
        "due_date": "<due_date_column>",
        "customer_id": "<customer_fk_column>"
      }}
    }},
    "products": {{
      "table": "<actual_table_name>",
      "confidence": 0.85,
      "base_filter": "",
      "key_columns": {{
        "product_pk": "<pk_column_name>",
        "product_name": "<name_column_name>"
      }}
    }}
  }},
  "relationships": [
    {{"from": "invoices", "to": "customers", "via": "<fk_column_in_invoices>"}}
  ]
}}

Rules:
- Include entities you are reasonably confident about (confidence >= 0.75)
- For base_filter: use the pre-scan discriminator data to construct precise SQL fragments
  e.g. if issotrx has Y=30100 → base_filter for invoices: "AND issotrx = 'Y' AND docstatus = 'CO'"
  e.g. for customers/bpartners: "AND iscustomer = 'Y' AND isactive = 'Y'"
- Leave base_filter as empty string "" if no filter is needed
- All table names must exactly match actual table names from the schema above
- The ERP is likely Openbravo — common mappings: c_bpartner=customers, c_invoice=invoices, c_invoiceline=invoice_lines, c_payment=payments, m_product=products

RETURN ONLY THE JSON OBJECT."""

        llm_options = LLMOptions(model=ModelType.SONNET, stream=False)
        entity_map: Dict = {"entities": {}, "relationships": []}

        try:
            provider = await _interceptor.get_provider()
            result = await provider.query(prompt, llm_options)
            content = result.content if hasattr(result, "content") else str(result)

            # Extract JSON from response (handle markdown fences)
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                entity_map = json.loads(json_match.group())
                logger.info("Direct cartographer LLM classification succeeded",
                            entities=list(entity_map.get("entities", {}).keys()))
            else:
                logger.warning("Direct cartographer: no JSON in LLM response", response=content[:300])
        except Exception as e:
            logger.error("Direct cartographer LLM call failed", error=str(e))

        # ── Step 4: persist as artifact (for compatibility) ──────────────────
        client_name = config.get("name", "unknown")
        artifact_dir = Path(f"output/{client_name}/discovery")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "entity_map.json").write_text(
            json.dumps(entity_map, indent=2), encoding="utf-8"
        )

        entity_map["_phase1_prescan"] = {
            "tables_probed": len(prescan.get("candidate_hints", {})),
            "direct_mode": True,
        }
        return entity_map

    async def _run_pipeline_with_progress(
        self,
        config: Dict,
        period: str,
        job_id: str,
        timeout: int = 900,
    ) -> Dict[str, Any]:
        """
        Run the original Valinor pipeline with progress callbacks and a hard
        timeout of *timeout* seconds (default 900 = 15 minutes).

        Raises:
            PipelineTimeoutError: if the pipeline does not complete within the
                                  allotted time.
        """
        try:
            return await asyncio.wait_for(
                self._run_pipeline_impl(config, period, job_id),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise PipelineTimeoutError(
                f"Pipeline exceeded the {timeout}s time limit for job {job_id}"
            ) from exc

    async def _run_pipeline_impl(
        self,
        config: Dict,
        period: str,
        job_id: str,
    ) -> Dict[str, Any]:
        """
        Internal pipeline implementation.
        Run the original Valinor pipeline with progress callbacks.
        Wraps the v0 pipeline without modifying it.
        """
        results = {"stages": {}}
        client_name = config.get("name", "unknown")

        try:
            # Parse period
            period_config = parse_period(period)

            # ── Load ClientProfile ────────────────────────────────────────────────
            profile = await self.profile_store.load_or_create(client_name)
            logger.info("ClientProfile loaded", client=client_name, run_count=profile.run_count,
                        has_cache=profile.is_entity_map_fresh())

            # ═══ STAGE 1: CARTOGRAPHER ═══
            if profile.is_entity_map_fresh():
                # Use cached entity_map — skip expensive LLM cartographer call
                entity_map = profile.entity_map_cache
                await self._progress("cartographer", 25,
                                     f"Usando mapa de entidades en caché ({len(entity_map.get('entities', {}))} entidades)")
                results["stages"]["cartographer"] = {
                    "entities_found": len(entity_map.get("entities", {})),
                    "success": True,
                    "cache_hit": True
                }
            else:
                await self._progress("cartographer", 15, "Discovering database schema...")
                entity_map = await self._run_direct_cartographer(config)
                results["stages"]["cartographer"] = {
                    "entities_found": len(entity_map.get("entities", {})),
                    "success": True,
                    "cache_hit": False
                }
                # Update entity_map cache in profile
                profile.entity_map_cache = entity_map
                profile.entity_map_updated_at = datetime.utcnow().isoformat()
                # Auto-detect industry and currency from schema
                self.industry_detector.update_profile(profile, entity_map, config)
                await self._progress("cartographer", 25, f"Found {len(entity_map['entities'])} entities")

            # Initialize default alert thresholds for new clients (after industry detection)
            if not profile.alert_thresholds:
                try:
                    from shared.memory.alert_engine import create_default_thresholds
                    profile.alert_thresholds = create_default_thresholds(profile)
                    logger.info("Default alert thresholds initialized", client=client_name,
                                count=len(profile.alert_thresholds),
                                industry=profile.industry_inferred)
                except Exception as _init_err:
                    logger.warning("Failed to init default thresholds", error=str(_init_err))

            # Gate check
            if not gate_cartographer(entity_map):
                raise ValueError("Insufficient entity mapping - need at least customers + invoices")

            # Rerank entity map based on historical table weights
            entity_map = self.focus_ranker.rerank_entity_map(entity_map, profile)

            # ═══ STAGE 1.8: DATA QUALITY GATE ═══
            await self._progress("data_quality", 28, "Running data quality checks...")

            from sqlalchemy import create_engine as _create_engine
            _dq_engine = _create_engine(config["connection_string"])
            try:
                dq_gate = DataQualityGate(_dq_engine, period_config.get("start", ""), period_config.get("end", ""), erp=config.get("erp"), db_schema=config.get("db_schema", "public"))
                dq_report = dq_gate.run()
            except Exception as _dq_err:
                logger.warning("DataQualityGate failed, proceeding without DQ check", error=str(_dq_err))
                from core.valinor.quality.data_quality_gate import DataQualityReport
                dq_report = DataQualityReport(overall_score=75.0, gate_decision="PROCEED_WITH_WARNINGS",
                                              warnings=[f"DQ gate error: {_dq_err}"])
            finally:
                _dq_engine.dispose()

            results["data_quality"] = {
                "score": dq_report.overall_score,
                "label": dq_report.confidence_label,
                "confidence_label": dq_report.confidence_label,  # backward-compat alias
                "tag": dq_report.data_quality_tag,
                "gate_decision": dq_report.gate_decision,
                "decision": dq_report.gate_decision,  # backward-compat alias
                "checks": [
                    {
                        "name": c.check_name if hasattr(c, "check_name") else str(c),
                        "passed": getattr(c, "passed", True),
                        "severity": getattr(c, "severity", ""),
                        "score_impact": getattr(c, "score_impact", 0),
                    }
                    for c in dq_report.checks
                ],
                "warnings": dq_report.warnings[:5],
                "blocking_issues": dq_report.blocking_issues,
            }

            if dq_report.gate_decision == "HALT":
                raise ValueError(
                    f"Data quality gate HALT: score={dq_report.overall_score:.0f}/100. "
                    f"Issues: {'; '.join(dq_report.blocking_issues)}"
                )

            # Initialize provenance registry for this run
            provenance = ProvenanceRegistry(
                job_id=job_id,
                client_name=client_name,
                period=period,
                dq_report_score=dq_report.overall_score,
                dq_report_tag=dq_report.data_quality_tag,
            )
            results["_provenance"] = provenance

            await self._progress("data_quality", 30,
                                 f"DQ Score: {dq_report.overall_score:.0f}/100 ({dq_report.confidence_label})")

            # ── Factor model decomposition ────────────────────────────────────
            try:
                from core.valinor.quality.factor_model import RevenueFactorModel
                from sqlalchemy import create_engine as _create_engine
                _fm_engine = _create_engine(config["connection_string"])
                try:
                    fm = RevenueFactorModel(_fm_engine)
                    # Compute prior period (same length, shifted back)
                    from datetime import datetime as _dt, timedelta
                    _ps = period_config.get("start", "")
                    _pe = period_config.get("end", "")
                    if _ps and _pe:
                        _start_dt = _dt.strptime(_ps, "%Y-%m-%d")
                        _end_dt = _dt.strptime(_pe, "%Y-%m-%d")
                        _duration = (_end_dt - _start_dt).days
                        _prior_end = (_start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
                        _prior_start = (_start_dt - timedelta(days=_duration + 1)).strftime("%Y-%m-%d")
                        decomp = fm.compute_decomposition(_ps, _pe, _prior_start, _prior_end)
                        if decomp:
                            results["factor_model"] = {
                                "expected_revenue": decomp.expected_revenue,
                                "residual_pct": round(decomp.residual / max(abs(decomp.expected_revenue), 1) * 100, 2),
                                "primary_driver": decomp.primary_driver,
                                "anomaly": decomp.anomaly_detected,
                                "anomaly_description": decomp.anomaly_description,
                            }
                            # Inject into agent memory
                            memory_fm_context = fm.format_context_block(decomp)
                            results["_factor_model_context"] = memory_fm_context
                finally:
                    _fm_engine.dispose()
            except Exception as _fm_err:
                logger.warning("Factor model failed, skipping", error=str(_fm_err))

            # ── CUSUM structural break detection on revenue history ────────────
            try:
                from core.valinor.quality.statistical_checks import cusum_structural_break
                _revenue_history = profile.baseline_history.get("total_revenue") if hasattr(profile, "baseline_history") and profile.baseline_history else None
                if _revenue_history and len(_revenue_history) >= 4:
                    # baseline_history entries are KPIDataPoint dicts with numeric_value
                    _rev_values = [
                        float(e["numeric_value"]) for e in _revenue_history
                        if isinstance(e, dict) and e.get("numeric_value") is not None
                    ]
                    if len(_rev_values) < 4:
                        _rev_values = []
                if _rev_values:
                    _cusum_result = cusum_structural_break(_rev_values)
                    if _cusum_result.get("break_detected"):
                        _break_idx = len(_rev_values) - 1
                        results["_cusum_warning"] = {
                            "detected": True,
                            "break_point": _break_idx,
                            "message": f"Structural break detected in revenue at period {_break_idx}",
                        }
                        logger.info("CUSUM structural break detected in revenue", period=_break_idx,
                                    cusum_last=_cusum_result.get("cusum_last"))
            except Exception as _cusum_err:
                logger.warning("CUSUM structural break detection failed, skipping", error=str(_cusum_err))

            # ═══ STAGE 2: QUERY BUILDER ═══
            await self._progress("query_builder", 30, "Building analysis queries...")

            # Forward query hints from profile refinement to query builder context
            refinement = profile.get_refinement()
            if refinement.query_hints:
                # Inject hints into period_config as additional context (non-breaking)
                period_config_with_hints = {
                    **period_config,
                    "query_hints": refinement.query_hints,
                    "focus_tables": profile.focus_tables[:5],
                }
                query_pack = build_queries(entity_map, period_config_with_hints)
            else:
                query_pack = build_queries(entity_map, period_config)
            results["stages"]["query_builder"] = {
                "queries_built": len(query_pack.get("queries", [])),
                "queries_skipped": len(query_pack.get("skipped", [])),
                "success": True
            }

            await self._progress("query_builder", 35, f"Built {len(query_pack['queries'])} queries")

            # ═══ STAGE 2.5: EXECUTE QUERIES ═══
            await self._progress("query_execution", 40, "Executing database queries...")

            query_results = await execute_queries(query_pack, config)
            results["stages"]["query_execution"] = {
                "executed": len(query_results.get("results", [])),
                "failed": len(query_results.get("errors", [])),
                "snapshot_timestamp": query_results.get("snapshot_timestamp"),
                "success": True
            }

            await self._progress("query_execution", 50, f"Executed {len(query_results['results'])} queries")

            # ── Currency homogeneity check ────────────────────────────────────
            _guard = get_currency_guard()
            currency_issues = _guard.scan_query_results(query_results)
            if currency_issues:
                results["currency_warnings"] = {
                    qid: {"mixed_pct": f"{r.mixed_exposure_pct:.2%}", "recommendation": r.recommendation}
                    for qid, r in currency_issues.items()
                }
                logger.warning("Currency mixing detected in query results",
                               affected_queries=list(currency_issues.keys()))
                # Build currency context block for agent injection
                first_check = next(iter(currency_issues.values()))
                results["_currency_context"] = _guard.build_currency_context_block(first_check)
            else:
                # Confirm single currency for agents
                from core.valinor.quality.currency_guard import CurrencyCheckResult
                _ok_check = CurrencyCheckResult(is_homogeneous=True,
                                                dominant_currency=profile.currency_detected or "USD",
                                                dominant_pct=100.0,
                                                mixed_exposure_pct=0.0,
                                                safe_to_aggregate=True,
                                                recommendation="")
                results["_currency_context"] = _guard.build_currency_context_block(_ok_check)

            # ── Statistical anomaly detection on raw results ──────────────────
            try:
                from core.valinor.quality.anomaly_detector import get_anomaly_detector
                statistical_anomalies = get_anomaly_detector().scan(query_results)
                if statistical_anomalies:
                    results["statistical_anomalies"] = [
                        {"query": a.query_id, "column": a.column, "severity": a.severity,
                         "description": a.description, "value_share": a.value_share}
                        for a in statistical_anomalies
                    ]
                    # Will inject into memory in the memory section below
                    results["_anomaly_context"] = get_anomaly_detector().format_for_agent(statistical_anomalies)
            except Exception as _anom_err:
                logger.warning("Anomaly detector failed", error=str(_anom_err))

            # ── Benford's Law check on monetary columns ───────────────────────
            try:
                from core.valinor.quality.statistical_checks import benford_test
                _benford_cols = ["grandtotal", "amount_untaxed", "amount_total", "debit", "credit"]
                _benford_values = []
                for _qr in query_results.get("results", []):
                    if not isinstance(_qr, dict):
                        continue
                    _rows = _qr.get("rows") or _qr.get("data") or []
                    if len(_rows) < 100:
                        continue
                    # Find first matching monetary column
                    _col_found = None
                    if _rows and isinstance(_rows[0], dict):
                        for _col in _benford_cols:
                            if _col in _rows[0]:
                                _col_found = _col
                                break
                    if _col_found is None:
                        continue
                    # Extract positive values, cap at 500
                    _vals = []
                    for _row in _rows[:500]:
                        _v = _row.get(_col_found)
                        try:
                            _fv = float(_v)
                            if _fv > 0:
                                _vals.append(_fv)
                        except (TypeError, ValueError):
                            pass
                    if len(_vals) >= 100:
                        _benford_values = _vals
                        break  # Use first qualifying result set
                if _benford_values:
                    _bf = benford_test(_benford_values)
                    _bf_p = _bf.get("p_value")
                    _bf_mad = _bf.get("mad")
                    _bf_suspicious = _bf.get("suspicious", False)
                    if _bf_suspicious and _bf_p is not None and _bf_mad is not None:
                        results["_benford_warning"] = {
                            "detected": True,
                            "chi2_pvalue": _bf_p,
                            "mad": _bf_mad,
                            "n_samples": _bf.get("n_samples"),
                            "message": (
                                f"Distribución de primeros dígitos anómala (p={_bf_p:.3f}, MAD={_bf_mad:.3f})"
                            ),
                        }
                        logger.warning("Benford's Law anomaly detected in monetary column",
                                       p_value=_bf_p, mad=_bf_mad, n_samples=_bf.get("n_samples"))
            except Exception as _bf_err:
                logger.warning("Benford's Law check failed, skipping", error=str(_bf_err))

            # ── Customer segmentation from query results ──────────────────────
            seg_result = self.segmentation_engine.segment_from_query_results(query_results, profile)
            if seg_result:
                self.segmentation_engine.update_profile_segments(profile, seg_result)
                results["segmentation"] = {
                    "total_customers": seg_result.total_customers,
                    "total_revenue": seg_result.total_revenue,
                    "industry": seg_result.industry,
                    "segments": [
                        {"name": s.name, "count": s.count, "revenue_share": round(s.revenue_share, 3),
                         "top_customers": s.top_customers}
                        for s in seg_result.segments
                    ],
                }
                # Inject segmentation context into memory for agents
                seg_context = self.segmentation_engine.build_context_block(seg_result, profile.currency_detected or "USD")
                if "_segmentation_context" not in results:
                    results["_segmentation_context"] = seg_context

            # ═══ STAGE 3: ANALYSIS AGENTS (PARALLEL) ═══
            await self._progress("analysis_agents", 55, "Running AI analysis agents...")

            # Get old-style memory for backward compatibility
            memory = await self.metadata_storage.get_client_memory(client_name)

            # Inject adaptive context from profile into memory
            memory = self.prompt_tuner.inject_into_memory(memory or {}, profile)

            # Build and store the rich adaptive context string so all agents
            # have a single, human-readable summary of accumulated client knowledge.
            memory["adaptive_context"] = build_adaptive_context(profile)

            # Inject Data Quality Gate context into agent memory.
            # Build a rich summary that includes per-check pass/fail and critical
            # recommendations so the narrator's DATA_QUALITY_INSTRUCTION template
            # gets real, actionable data rather than just the brief default string.
            def _build_dq_context(report) -> str:
                lines = [
                    "DATA QUALITY CONTEXT:",
                    f"- DQ Score: {report.overall_score:.0f}/100 ({report.confidence_label})"
                    f" — Tag: {report.data_quality_tag}",
                    f"- Gate decision: {report.gate_decision}",
                ]

                # Per-check pass/fail breakdown
                if report.checks:
                    passed_checks = [c.check_name for c in report.checks if c.passed]
                    failed_checks = [(c.check_name, c.severity) for c in report.checks if not c.passed]
                    if passed_checks:
                        lines.append(f"- Checks PASSED ({len(passed_checks)}): {', '.join(passed_checks)}")
                    if failed_checks:
                        failed_str = ", ".join(
                            f"{name} [{sev}]" for name, sev in failed_checks
                        )
                        lines.append(f"- Checks FAILED ({len(failed_checks)}): {failed_str}")

                # Critical / fatal recommendations
                critical_recs = [
                    c.recommendation
                    for c in report.checks
                    if not c.passed
                    and c.severity in ("FATAL", "CRITICAL")
                    and c.recommendation
                ]
                if critical_recs:
                    lines.append("- Critical recommendations:")
                    for rec in critical_recs[:5]:
                        lines.append(f"    * {rec}")
                elif report.warnings:
                    warnings_str = "; ".join(report.warnings[:3])
                    lines.append(f"- Warnings: {warnings_str}")

                # Blocking issues
                if report.blocking_issues:
                    lines.append(
                        "- BLOCKING ISSUES: " + "; ".join(report.blocking_issues)
                    )

                lines.append(
                    "INSTRUCTION: Label findings as PROVISIONAL if derived from flagged data. "
                    "Never present UNVERIFIED findings as facts in executive summary."
                )
                return "\n".join(lines)

            memory["data_quality_context"] = _build_dq_context(dq_report)

            # Inject customer segmentation context if available
            if results.get("_segmentation_context"):
                memory["segmentation_context"] = results["_segmentation_context"]

            # Inject factor model context if available
            if results.get("_factor_model_context"):
                memory["factor_model_context"] = results["_factor_model_context"]

            # Inject statistical anomaly context if available
            if results.get("_anomaly_context"):
                memory["statistical_anomalies"] = results["_anomaly_context"]

            # Inject currency context block
            if results.get("_currency_context"):
                memory["currency_context"] = results["_currency_context"]

            # Inject CUSUM structural break warning if detected
            if results.get("_cusum_warning"):
                _cw = results["_cusum_warning"]
                _period_n = _cw.get("break_point", "?")
                memory["cusum_warning"] = (
                    f"AVISO: Ruptura estructural detectada en los ingresos (período {_period_n}). "
                    "Puede indicar un cambio de régimen del negocio."
                )

            # Inject Benford's Law warning if detected
            if results.get("_benford_warning"):
                memory["benford_warning"] = (
                    "AVISO: Los valores monetarios muestran distribución anómala de primeros dígitos "
                    "(Ley de Benford). Investigar posible manipulación."
                )

            # Inject sentinel fraud patterns for available tables
            try:
                from core.valinor.agents.sentinel_patterns import (
                    get_patterns_for_tables, build_sentinel_context
                )
                available_tables = list(entity_map.get("entities", {}).keys())
                relevant_patterns = get_patterns_for_tables(available_tables)
                if relevant_patterns:
                    memory["sentinel_patterns"] = build_sentinel_context(relevant_patterns)
                    logger.info("Sentinel patterns injected", count=len(relevant_patterns))
            except Exception as _sp_err:
                logger.warning("Sentinel patterns injection failed", error=str(_sp_err))

            # Inject historical context for narrator
            if profile.run_count > 0 and profile.run_history:
                memory["run_history_summary"] = {
                    "previous_run_date": profile.last_run_date,
                    "run_number": profile.run_count + 1,
                    "previously_resolved": len(profile.resolved_findings),
                    "persistent_findings": [
                        {"id": fid, "title": rec.get("title", ""), "runs_open": rec.get("runs_open", 1)}
                        for fid, rec in profile.known_findings.items()
                        if rec.get("runs_open", 0) >= 3
                    ][:5],
                    "industry": profile.industry_inferred,
                    "currency": profile.currency_detected,
                }

            # Compute baseline (frozen brief with provenance-tagged numbers)
            baseline = compute_baseline(query_results)

            findings = await run_analysis_agents(query_results, entity_map, memory, baseline)
            results["stages"]["analysis_agents"] = {
                "agents_completed": list(findings.keys()),
                "success": gate_analysis(findings)
            }
            results["findings"] = findings

            # Run QueryEvolver to track empty queries and high-value tables
            try:
                evolver_report = self.query_evolver.analyze_query_results(
                    query_results, findings, profile
                )
                results["_query_evolver"] = evolver_report
                logger.info(
                    "QueryEvolver",
                    empty_queries=len(evolver_report.get("empty_queries", [])),
                    high_value_tables=len(evolver_report.get("high_value_tables", [])),
                )
                # Update query evolver with findings — persist insights into memory
                # so narrators and profile save can see evolution context
                if evolver_report:
                    memory["query_evolution_context"] = evolver_report
            except Exception as _qe_err:
                logger.warning("QueryEvolver failed", error=str(_qe_err))

            await self._progress("analysis_agents", 75, f"Completed {len(findings)} agent analyses")

            # ═══ STAGE 4: NARRATORS ═══
            await self._progress("narrators", 80, "Generating executive reports...")

            report_text = await narrate_executive(findings, entity_map, memory, config, baseline)

            # Post-process report with quality certification
            try:
                from valinor.agents.narrators.quality_certifier import certify_report
                _dq_score = results.get("data_quality", {}).get("score", 75.0)
                _dq_label = results.get("data_quality", {}).get("confidence_label", "PROVISIONAL")
                if isinstance(report_text, str):
                    report_text = certify_report(report_text, _dq_label, _dq_score)
                elif isinstance(report_text, dict):
                    for key in report_text:
                        if isinstance(report_text[key], str):
                            report_text[key] = certify_report(report_text[key], _dq_label, _dq_score)
            except Exception as _cert_err:
                logger.warning("Quality certifier failed", error=str(_cert_err))

            reports = {"executive": report_text} if isinstance(report_text, str) else report_text
            results["stages"]["narrators"] = {
                "reports_generated": len(reports),
                "success": True
            }
            results["reports"] = reports

            await self._progress("narrators", 95, "Reports generated successfully")

            # ═══ STAGE 5: DELIVER ═══
            await self._progress("delivery", 98, "Finalizing results...")

            output_dir = Path(f"/tmp/valinor_output/{job_id}")
            output_dir.mkdir(parents=True, exist_ok=True)

            await deliver_reports(reports, entity_map, findings, results, output_dir)
            results["stages"]["delivery"] = {
                "output_path": str(output_dir),
                "success": True
            }

            # ── Update ClientProfile ──────────────────────────────────────────────
            run_delta = self.profile_extractor.update_from_run(
                profile, findings, entity_map, reports, period, run_success=True
            )
            results["run_delta"] = run_delta

            # Record DQ score in profile history
            if results.get("data_quality") and hasattr(profile, 'dq_history'):
                dq_entry = {
                    "run_date": datetime.utcnow().isoformat(),
                    "score": results["data_quality"].get("score", 100),
                    "tag": results["data_quality"].get("tag", "UNKNOWN"),
                    "label": results["data_quality"].get("confidence_label", "PROVISIONAL"),
                    "warnings_count": len(results["data_quality"].get("warnings", [])),
                }
                if not isinstance(profile.dq_history, list):
                    profile.dq_history = []
                profile.dq_history.append(dq_entry)
                profile.dq_history = profile.dq_history[-10:]  # keep last 10

            # ── Run AlertEngine to check custom thresholds ────────────────────
            try:
                from shared.memory.alert_engine import AlertEngine
                alert_engine = AlertEngine()
                triggered_alerts = alert_engine.check_thresholds(
                    profile, profile.baseline_history, findings
                )
                if triggered_alerts:
                    results["triggered_alerts"] = triggered_alerts
                    logger.info(
                        "AlertEngine: thresholds triggered",
                        count=len(triggered_alerts),
                        labels=[a.get("threshold_label") for a in triggered_alerts],
                    )
            except Exception as _ae_err:
                logger.warning("AlertEngine failed", error=str(_ae_err))

            # Store estimated cost in profile metadata for aggregation
            _profile_num_agents = len(findings) if isinstance(findings, dict) else 3
            _estimated_cost = round(0.008 + (_profile_num_agents * 0.002), 3)
            if not isinstance(getattr(profile, "metadata", None), dict):
                profile.metadata = {}
            profile.metadata["last_estimated_cost_usd"] = _estimated_cost
            profile.metadata["total_estimated_cost_usd"] = round(
                profile.metadata.get("total_estimated_cost_usd", 0.0) + _estimated_cost, 3
            )

            await self.profile_store.save(profile)

            # ── Fire RefinementAgent in background ───────────────────────────────
            # Deep copy profile to avoid race condition: the background task
            # mutates and saves profile independently from the main pipeline.
            profile_snapshot = copy.deepcopy(profile)
            asyncio.create_task(self._run_refinement_background(
                profile_snapshot, findings, entity_map, reports, period, run_delta
            ))

            # Update legacy memory for backward compatibility
            new_memory = self._build_memory(entity_map, findings, results, memory)
            await self.metadata_storage.store_client_memory(client_name, period, new_memory)

            # ── Dispatch analysis_completed webhook ───────────────────────────
            if getattr(profile, "webhooks", None) and results.get("status") == "completed":
                try:
                    _findings_count = sum(
                        len(v.get("findings", [])) if isinstance(v, dict) else 0
                        for v in findings.values()
                    ) if isinstance(findings, dict) else 0
                    _webhook_data = {
                        "job_id": job_id,
                        "client_name": client_name,
                        "period": period,
                        "findings_count": _findings_count,
                        "run_delta": run_delta,
                    }
                    _webhook_payload = create_webhook_payload(
                        "analysis_completed", _webhook_data, client_name
                    )
                    _dispatcher = WebhookDispatcher()
                    asyncio.create_task(
                        _dispatcher.dispatch(profile, "analysis_completed", _webhook_payload)
                    )
                    logger.info(
                        "Webhook dispatch queued",
                        client=client_name,
                        event="analysis_completed",
                        webhooks_registered=len(profile.webhooks),
                    )
                except Exception as _wh_err:
                    logger.warning("Webhook dispatch setup failed", error=str(_wh_err))

            return results

        except Exception as e:
            logger.error(
                "Pipeline stage failed",
                job_id=job_id,
                stage=results.get("current_stage", "unknown"),
                error=str(e)
            )
            raise

    async def _run_refinement_background(
        self,
        profile,
        findings: Dict,
        entity_map: Dict,
        reports: Dict,
        period: str,
        run_delta: Dict,
    ):
        """Background task: run RefinementAgent and update profile with results."""
        try:
            refinement_agent = RefinementAgent()
            refinement = await refinement_agent.analyze_run(
                profile, findings, entity_map, reports, period, run_delta
            )
            profile.refinement = {
                "table_weights": refinement.table_weights,
                "query_hints": refinement.query_hints,
                "focus_areas": refinement.focus_areas,
                "suppress_ids": refinement.suppress_ids,
                "context_block": refinement.context_block,
                "generated_at": refinement.generated_at,
            }
            await self.profile_store.save(profile)
            logger.info("RefinementAgent completed", client=profile.client_name)
        except Exception as e:
            logger.error("RefinementAgent background task failed", error=str(e))

    def _create_temp_config(
        self,
        client_name: str,
        connection_string: str,
        original_config: Dict
    ) -> Dict:
        """
        Create temporary configuration for pipeline execution.
        Maps SaaS config to v0 config format.
        """
        safe_name = client_name or "unknown"
        overrides = original_config.get("overrides", {})
        # Extract explicit schema from overrides (e.g. playground tests)
        db_schema = overrides.get("search_path", None)
        config = {
            "name": safe_name,
            "display_name": safe_name.replace("_", " ").title(),
            "connection_string": connection_string,  # Now using tunneled connection
            "sector": original_config.get("sector", "unknown"),
            "country": original_config.get("country", "unknown"),
            "currency": original_config.get("currency", "USD"),
            "language": original_config.get("language", "es"),
            "erp": original_config.get("erp", "unknown"),
            "fiscal_context": original_config.get("fiscal_context", "generic"),
            "overrides": overrides,
        }
        if db_schema:
            config["db_schema"] = db_schema
        return config

    def _hash_config(self, config: Dict) -> str:
        """Generate hash of configuration for tracking (no sensitive data)."""
        import hashlib

        ssh_cfg = config.get("ssh_config") or {}
        db_cfg = config.get("db_config") or {}
        safe_config = {
            "ssh_host": ssh_cfg.get("host", ""),
            "db_type": db_cfg.get("type", ""),
            "has_overrides": bool(config.get("overrides"))
        }

        return hashlib.md5(
            json.dumps(safe_config, sort_keys=True).encode()
        ).hexdigest()

    def _build_memory(
        self,
        entity_map: Dict,
        findings: Dict,
        run_log: Dict,
        previous_memory: Optional[Dict]
    ) -> Dict:
        """Build memory for next analysis run."""
        return {
            "previous_run": {
                "date": datetime.utcnow().isoformat(),
                "entities_found": len(entity_map.get("entities", {})),
                "findings_count": sum(
                    len(agent_findings.get("findings", []))
                    for agent_findings in findings.values()
                    if isinstance(agent_findings, dict)
                ),
                "critical_issues": [
                    finding
                    for agent_findings in findings.values()
                    if isinstance(agent_findings, dict)
                    for finding in agent_findings.get("findings", [])
                    if finding.get("severity") == "critical"
                ][:5]  # Keep top 5 critical issues
            },
            "entity_map_snapshot": {
                "tables": list(entity_map.get("entities", {}).keys()),
                "row_counts": {
                    name: entity.get("row_count", 0)
                    for name, entity in entity_map.get("entities", {}).items()
                }
            },
            "history": previous_memory.get("history", [])[-4:] + [  # Keep last 5 runs
                {
                    "run_date": datetime.utcnow().isoformat(),
                    "success": run_log.get("status") == "completed"
                }
            ] if previous_memory else []
        }

    async def _progress(self, stage: str, progress: int, message: str):
        """Send progress update if callback is configured."""
        if self.progress_callback:
            try:
                await self.progress_callback(stage, progress, message)
            except Exception as e:
                logger.warning(
                    "Progress callback failed",
                    stage=stage,
                    error=str(e)
                )


class PipelineExecutor:
    """
    Advanced pipeline executor with fallback mechanisms.
    """

    def __init__(self, adapter: ValinorAdapter):
        self.adapter = adapter

    async def run_with_fallback(
        self,
        job_id: str,
        config: Dict,
        period: str
    ) -> Dict:
        """
        Execute pipeline with graceful degradation.
        If non-critical agents fail, continue with partial results.
        """
        results = {"partial_failure": False}

        try:
            # Run full pipeline
            results = await self.adapter.run_analysis(
                job_id=job_id,
                client_name=config["client_name"],
                connection_config=config,
                period=period
            )

        except Exception as e:
            # Check if critical failure
            if "cartographer" in str(e).lower() or "connection" in str(e).lower():
                # Critical failure - cannot continue
                raise

            # Non-critical failure - try to salvage
            logger.warning(
                "Non-critical pipeline failure, attempting partial recovery",
                job_id=job_id,
                error=str(e)
            )

            results["partial_failure"] = True
            results["partial_error"] = str(e)

            # Return whatever we managed to collect

        return results

    async def run_with_retry(
        self,
        job_id: str,
        config: Dict,
        period: str,
        max_retries: int = 2
    ) -> Dict:
        """
        Execute pipeline with automatic retry on transient failures.
        """
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(
                        "Retrying analysis",
                        job_id=job_id,
                        attempt=attempt + 1,
                        max_retries=max_retries + 1
                    )
                    # Wait before retry (exponential backoff)
                    await asyncio.sleep(2 ** attempt)

                return await self.adapter.run_analysis(
                    job_id=job_id,
                    client_name=config["client_name"],
                    connection_config=config,
                    period=period
                )

            except Exception as e:
                last_error = e

                # Check if error is retryable
                error_str = str(e).lower()
                non_retryable = [
                    "invalid configuration",
                    "authentication failed",
                    "permission denied",
                    "insufficient privileges"
                ]

                if any(term in error_str for term in non_retryable):
                    logger.error(
                        "Non-retryable error encountered",
                        job_id=job_id,
                        error=str(e)
                    )
                    raise

                logger.warning(
                    "Retryable error encountered",
                    job_id=job_id,
                    attempt=attempt + 1,
                    error=str(e)
                )

        # All retries exhausted
        raise last_error or Exception("All retry attempts failed")
