"""
Valinor Adapter - Wrapper around v0 CLI functionality for SaaS.
Preserves all original functionality while adding SaaS capabilities.
"""

import os
import sys
import json
import re
import asyncio
import tempfile
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

# Import original Valinor components (unchanged) — NOW safe to import
from valinor.config import load_client_config, parse_period
from valinor.agents.cartographer import run_cartographer
from valinor.agents.query_builder import build_queries
from valinor.pipeline import run_analysis_agents, execute_queries, compute_baseline
from valinor.agents.narrators.executive import narrate_executive
from valinor.deliver import deliver_reports
from valinor.gates import gate_cartographer, gate_analysis

from shared.ssh_tunnel import create_ssh_tunnel, ZeroTrustValidator
from shared.storage import MetadataStorage

logger = structlog.get_logger()

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
            # Inside Docker, localhost/127.0.0.1 refers to the container itself.
            # Route to the host via host.docker.internal. Because host postgres only
            # listens on 127.0.0.1, a port forwarder on 0.0.0.0:5444 → 127.0.0.1:5432
            # is expected on the host (see scripts/pg_proxy.py or scripts/claude_proxy.py).
            if os.path.exists("/.dockerenv"):
                import re as _re
                def _remap_pg_port(m):
                    port = int(m.group(1))
                    # Map standard PG ports to the forwarder ports on the host
                    port_map = {5432: 5444, 5433: 5444, 5435: 5445, 5436: 5446}
                    new_port = port_map.get(port, port)
                    return f"@host.docker.internal:{new_port}/"
                conn_str = _re.sub(r'@(?:localhost|127\.0\.0\.1):(\d+)/', _remap_pg_port, conn_str)
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
                
            # Calculate execution time
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            results["execution_time_seconds"] = execution_time
            results["status"] = "completed"
            results["completed_at"] = datetime.utcnow().isoformat()
            
            # Store results metadata (no client data)
            await self.metadata_storage.store_job_results(job_id, {
                "findings_count": len(results.get("findings", {})),
                "execution_time": execution_time,
                "success": True
            })
            
            await self._progress("completed", 100, f"Analysis completed in {execution_time:.1f} seconds")
            
            return results
            
        except Exception as e:
            logger.error(
                "Analysis failed",
                job_id=job_id,
                client=client_name,
                error=str(e)
            )
            
            results["status"] = "failed"
            results["error"] = str(e)
            results["failed_at"] = datetime.utcnow().isoformat()
            
            # Store failure metadata
            await self.metadata_storage.store_job_results(job_id, {
                "success": False,
                "error": str(e)
            })
            
            await self._progress("failed", -1, f"Analysis failed: {str(e)}")
            
            raise
    
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
        job_id: str
    ) -> Dict[str, Any]:
        """
        Run the original Valinor pipeline with progress callbacks.
        Wraps the v0 pipeline without modifying it.
        """
        results = {"stages": {}}

        try:
            # Parse period
            period_config = parse_period(period)

            # ═══ STAGE 1: CARTOGRAPHER ═══
            await self._progress("cartographer", 15, "Discovering database schema...")

            entity_map = await self._run_direct_cartographer(config)
            results["stages"]["cartographer"] = {
                "entities_found": len(entity_map.get("entities", {})),
                "success": True
            }
            
            # Gate check
            if not gate_cartographer(entity_map):
                raise ValueError("Insufficient entity mapping - need at least customers + invoices")
            
            await self._progress("cartographer", 25, f"Found {len(entity_map['entities'])} entities")
            
            # ═══ STAGE 2: QUERY BUILDER ═══
            await self._progress("query_builder", 30, "Building analysis queries...")
            
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
                "success": True
            }
            
            await self._progress("query_execution", 50, f"Executed {len(query_results['results'])} queries")
            
            # ═══ STAGE 3: ANALYSIS AGENTS (PARALLEL) ═══
            await self._progress("analysis_agents", 55, "Running AI analysis agents...")
            
            # Get memory if exists
            memory = await self.metadata_storage.get_client_memory(config.get("name", "unknown"))

            # Compute baseline (frozen brief with provenance-tagged numbers)
            baseline = compute_baseline(query_results)

            findings = await run_analysis_agents(query_results, entity_map, memory, baseline)
            results["stages"]["analysis_agents"] = {
                "agents_completed": list(findings.keys()),
                "success": gate_analysis(findings)
            }
            results["findings"] = findings
            
            await self._progress("analysis_agents", 75, f"Completed {len(findings)} agent analyses")
            
            # ═══ STAGE 4: NARRATORS ═══
            await self._progress("narrators", 80, "Generating executive reports...")
            
            report_text = await narrate_executive(findings, entity_map, memory, config, baseline)
            # narrate_executive returns a str; wrap in dict for deliver_reports
            reports = {"executive": report_text} if isinstance(report_text, str) else report_text
            results["stages"]["narrators"] = {
                "reports_generated": len(reports),
                "success": True
            }
            results["reports"] = reports

            await self._progress("narrators", 95, "Reports generated successfully")

            # ═══ STAGE 5: DELIVER ═══
            await self._progress("delivery", 98, "Finalizing results...")

            # Store in temporary location for this job
            output_dir = Path(f"/tmp/valinor_output/{job_id}")
            output_dir.mkdir(parents=True, exist_ok=True)

            await deliver_reports(reports, entity_map, findings, results, output_dir)
            results["stages"]["delivery"] = {
                "output_path": str(output_dir),
                "success": True
            }
            
            # Update memory for next run
            new_memory = self._build_memory(entity_map, findings, results, memory)
            await self.metadata_storage.store_client_memory(
                config.get("name", "unknown"),
                period,
                new_memory
            )
            
            return results
            
        except Exception as e:
            logger.error(
                "Pipeline stage failed",
                job_id=job_id,
                stage=results.get("current_stage", "unknown"),
                error=str(e)
            )
            raise
    
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
        return {
            "name": safe_name,
            "display_name": safe_name.replace("_", " ").title(),
            "connection_string": connection_string,  # Now using tunneled connection
            "sector": original_config.get("sector", "unknown"),
            "country": original_config.get("country", "unknown"),
            "currency": original_config.get("currency", "USD"),
            "language": original_config.get("language", "es"),
            "erp": original_config.get("erp", "unknown"),
            "fiscal_context": original_config.get("fiscal_context", "generic"),
            "overrides": original_config.get("overrides", {})
        }
    
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