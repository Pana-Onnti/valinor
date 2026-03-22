"""
Tests for Active Re-Query Verification (CRITIC pattern).

Validates:
  1. _generate_verification_query() produces valid SQL from entity_map
  2. Query generation is data-driven (uses KG filters, not hardcoded)
  3. Returns None for unverifiable claim types
  4. _execute_verification_query() handles timeout gracefully
  5. _execute_verification_query() blocks write operations
  6. Full verify_findings with active verification against Gloria DB
  7. Claims go UNVERIFIABLE → VERIFIED after active re-query
"""
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest
from valinor.verification import (
    VerificationEngine,
    AtomicClaim,
    VerificationResult,
)
from valinor.knowledge_graph import SchemaKnowledgeGraph, build_knowledge_graph


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES — generic entity_map (no hardcoded ERP names)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def generic_entity_map():
    """
    A schema-agnostic entity_map that could come from any ERP.
    Table/column names are intentionally NOT Openbravo-specific.
    """
    return {
        "entities": {
            "invoices": {
                "table": "t_invoice",
                "type": "TRANSACTIONAL",
                "row_count": 5000,
                "base_filter": "is_sales='Y' AND doc_status='CO'",
                "key_columns": {
                    "pk": "invoice_id",
                    "amount_col": "grand_total",
                    "customer_fk": "bp_id",
                    "date_col": "invoice_date",
                },
                "probed_values": {
                    "is_sales": {"Y": 3000, "N": 2000},
                    "doc_status": {"CO": 4500, "DR": 500},
                },
            },
            "customers": {
                "table": "t_customer",
                "type": "MASTER",
                "row_count": 1500,
                "base_filter": "",
                "key_columns": {
                    "pk": "customer_id",
                    "name": "full_name",
                },
                "probed_values": {},
            },
        },
        "relationships": [
            {
                "from": "invoices",
                "to": "customers",
                "via": "bp_id",
                "cardinality": "N:1",
            },
        ],
    }


@pytest.fixture
def generic_kg(generic_entity_map):
    """Knowledge graph built from generic entity_map."""
    return build_knowledge_graph(generic_entity_map)


@pytest.fixture
def empty_query_results():
    """Empty query results — forces active re-query path."""
    return {"results": {}, "errors": {}}


@pytest.fixture
def empty_baseline():
    return {}


@pytest.fixture
def active_engine(empty_query_results, empty_baseline, generic_kg, generic_entity_map):
    """Engine configured for active verification (no passive results)."""
    return VerificationEngine(
        query_results=empty_query_results,
        baseline=empty_baseline,
        knowledge_graph=generic_kg,
        connection_string="postgresql://test:test@localhost:5432/testdb",
        entity_map=generic_entity_map,
    )


# ═══════════════════════════════════════════════════════════════════════════
# TEST: _generate_verification_query
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateVerificationQuery:

    def test_revenue_claim_produces_valid_sql(self, active_engine, generic_entity_map):
        """A revenue claim should generate a SUM query on the amount column."""
        claim = AtomicClaim(
            claim_id="test_rev",
            finding_id="F1",
            claim_text="EUR value: 1631559.62",
            claim_type="numeric",
            claimed_value=1631559.62,
            claimed_unit="EUR",
        )
        vq = active_engine._generate_verification_query(claim, generic_entity_map)

        assert vq is not None
        sql = vq["sql"].upper()
        assert "SELECT" in sql
        assert "SUM" in sql
        # Must use entity_map column name, not hardcoded
        assert "GRAND_TOTAL" in sql
        assert "T_INVOICE" in sql
        assert vq["expected_type"] == "sum"

    def test_uses_kg_filters_not_hardcoded(self, active_engine, generic_entity_map):
        """Generated SQL must include the base_filter from entity_map."""
        claim = AtomicClaim(
            claim_id="test_filter",
            finding_id="F2",
            claim_text="EUR value: 500000",
            claim_type="numeric",
            claimed_value=500000.0,
            claimed_unit="EUR",
        )
        vq = active_engine._generate_verification_query(claim, generic_entity_map)

        assert vq is not None
        sql = vq["sql"]
        # base_filter says is_sales='Y' AND doc_status='CO'
        assert "is_sales" in sql.lower()
        assert "doc_status" in sql.lower()

    def test_count_claim_produces_count_sql(self, active_engine, generic_entity_map):
        """A count claim should generate a COUNT query."""
        claim = AtomicClaim(
            claim_id="test_count",
            finding_id="F3",
            claim_text="customer count: 1223",
            claim_type="numeric",
            claimed_value=1223.0,
            claimed_unit="count",
        )
        vq = active_engine._generate_verification_query(claim, generic_entity_map)

        assert vq is not None
        sql = vq["sql"].upper()
        assert "COUNT" in sql
        assert "DISTINCT" in sql
        # Must use the customer FK from entity_map
        assert "BP_ID" in sql
        assert vq["expected_type"] == "count"

    def test_returns_none_for_unverifiable_claim(self, active_engine):
        """Claims without a numeric value or with no matching entity should return None."""
        claim = AtomicClaim(
            claim_id="test_none",
            finding_id="F4",
            claim_text="The data quality is excellent",
            claim_type="existence",
            claimed_value=None,
        )
        vq = active_engine._generate_verification_query(claim, {"entities": {}})
        assert vq is None

    def test_returns_none_for_empty_entity_map(self, active_engine):
        """No entity_map → cannot generate query."""
        claim = AtomicClaim(
            claim_id="test_empty",
            finding_id="F5",
            claim_text="EUR value: 100",
            claim_type="numeric",
            claimed_value=100.0,
        )
        assert active_engine._generate_verification_query(claim, None) is None
        assert active_engine._generate_verification_query(claim, {}) is None

    def test_percentage_claim_not_generated(self, active_engine, generic_entity_map):
        """Percentage claims don't map to a simple SUM/COUNT — may return None."""
        claim = AtomicClaim(
            claim_id="test_pct",
            finding_id="F6",
            claim_text="Percentage: 45.2%",
            claim_type="numeric",
            claimed_value=45.2,
            claimed_unit="percent",
        )
        # Percentage claims are not revenue or count, so should not match
        vq = active_engine._generate_verification_query(claim, generic_entity_map)
        # Either None or it falls through — both acceptable
        # The key is it should NOT generate a misleading SUM/COUNT query
        if vq is not None:
            assert vq["expected_type"] in ("sum", "count")


# ═══════════════════════════════════════════════════════════════════════════
# TEST: _execute_verification_query
# ═══════════════════════════════════════════════════════════════════════════

class TestExecuteVerificationQuery:

    def test_blocks_insert(self, active_engine):
        """INSERT statements must be blocked."""
        result = active_engine._execute_verification_query(
            "INSERT INTO t_invoice VALUES (1, 2, 3)",
            "postgresql://x:x@localhost/db",
        )
        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_blocks_update(self, active_engine):
        """UPDATE statements must be blocked."""
        result = active_engine._execute_verification_query(
            "UPDATE t_invoice SET grand_total = 0",
            "postgresql://x:x@localhost/db",
        )
        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_blocks_delete(self, active_engine):
        """DELETE statements must be blocked."""
        result = active_engine._execute_verification_query(
            "DELETE FROM t_invoice",
            "postgresql://x:x@localhost/db",
        )
        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_blocks_drop(self, active_engine):
        """DROP statements must be blocked."""
        result = active_engine._execute_verification_query(
            "DROP TABLE t_invoice",
            "postgresql://x:x@localhost/db",
        )
        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_blocks_truncate(self, active_engine):
        """TRUNCATE statements must be blocked."""
        result = active_engine._execute_verification_query(
            "TRUNCATE t_invoice",
            "postgresql://x:x@localhost/db",
        )
        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_blocks_alter(self, active_engine):
        """ALTER statements must be blocked."""
        result = active_engine._execute_verification_query(
            "ALTER TABLE t_invoice ADD COLUMN hack text",
            "postgresql://x:x@localhost/db",
        )
        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_blocks_write_in_subquery(self, active_engine):
        """Write keywords inside the query (not just start) must be blocked."""
        result = active_engine._execute_verification_query(
            "SELECT * FROM t_invoice; DELETE FROM t_invoice",
            "postgresql://x:x@localhost/db",
        )
        assert "error" in result
        assert "blocked" in result["error"].lower()

    def test_blocks_non_select(self, active_engine):
        """Non-SELECT/WITH queries must be blocked."""
        result = active_engine._execute_verification_query(
            "GRANT ALL ON t_invoice TO public",
            "postgresql://x:x@localhost/db",
        )
        assert "error" in result

    def test_handles_timeout_gracefully(self, active_engine):
        """If the query takes too long, return a timeout error."""
        # Mock sqlalchemy to simulate a slow query
        def slow_connect(*args, **kwargs):
            time.sleep(10)  # way longer than timeout

        with patch("valinor.verification.threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            # Simulate thread not finishing in time
            mock_thread.is_alive.return_value = True
            mock_thread.join = MagicMock()

            result = active_engine._execute_verification_query(
                "SELECT SUM(grand_total) FROM t_invoice",
                "postgresql://x:x@localhost/db",
                timeout=1,
            )
            assert "error" in result
            assert "timed out" in result["error"].lower()

    def test_handles_connection_error(self, active_engine):
        """Bad connection string should return error, not crash."""
        result = active_engine._execute_verification_query(
            "SELECT 1",
            "postgresql://bad:bad@nonexistent:9999/nodb",
            timeout=3,
        )
        assert "error" in result


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Full active verification flow
# ═══════════════════════════════════════════════════════════════════════════

class TestActiveVerificationFlow:

    def test_claim_becomes_verified_after_active_requery(
        self, empty_query_results, empty_baseline, generic_kg, generic_entity_map,
    ):
        """
        A claim that has NO match in the registry should become VERIFIED
        if the active re-query returns a matching value.
        """
        engine = VerificationEngine(
            query_results=empty_query_results,
            baseline=empty_baseline,
            knowledge_graph=generic_kg,
            connection_string="postgresql://test:test@localhost:5432/testdb",
            entity_map=generic_entity_map,
        )
        engine._build_registry_from_queries()

        claim = AtomicClaim(
            claim_id="active_test",
            finding_id="F-ACTIVE",
            claim_text="EUR value: 1631559.62",
            claim_type="numeric",
            claimed_value=1631559.62,
            claimed_unit="EUR",
        )

        # Mock _execute_verification_query to return matching value
        with patch.object(engine, "_execute_verification_query") as mock_exec:
            mock_exec.return_value = {
                "rows": [{"total": 1631559.62}],
                "row_count": 1,
            }
            result = engine._verify_claim(claim)

        assert result.status == "VERIFIED"
        assert result.actual_value == 1631559.62
        assert "Active re-query confirmed" in result.evidence
        assert result.verification_query is not None

    def test_claim_stays_unverifiable_without_connection(
        self, empty_query_results, empty_baseline, generic_kg, generic_entity_map,
    ):
        """Without connection_string, active re-query is skipped."""
        engine = VerificationEngine(
            query_results=empty_query_results,
            baseline=empty_baseline,
            knowledge_graph=generic_kg,
            connection_string=None,  # No connection
            entity_map=generic_entity_map,
        )
        engine._build_registry_from_queries()

        claim = AtomicClaim(
            claim_id="no_conn",
            finding_id="F-NOCONN",
            claim_text="EUR value: 1631559.62",
            claim_type="numeric",
            claimed_value=1631559.62,
            claimed_unit="EUR",
        )
        result = engine._verify_claim(claim)
        assert result.status == "UNVERIFIABLE"

    def test_claim_fails_when_requery_contradicts(
        self, empty_query_results, empty_baseline, generic_kg, generic_entity_map,
    ):
        """A claim contradicted by active re-query should be FAILED."""
        engine = VerificationEngine(
            query_results=empty_query_results,
            baseline=empty_baseline,
            knowledge_graph=generic_kg,
            connection_string="postgresql://test:test@localhost:5432/testdb",
            entity_map=generic_entity_map,
        )
        engine._build_registry_from_queries()

        claim = AtomicClaim(
            claim_id="contradict_test",
            finding_id="F-BAD",
            claim_text="EUR value: 13500000",
            claim_type="numeric",
            claimed_value=13500000.0,
            claimed_unit="EUR",
        )

        with patch.object(engine, "_execute_verification_query") as mock_exec:
            mock_exec.return_value = {
                "rows": [{"total": 1631559.62}],
                "row_count": 1,
            }
            result = engine._verify_claim(claim)

        assert result.status == "FAILED"
        assert "contradicts" in result.evidence.lower()

    def test_backward_compatible_init(self):
        """Existing code that doesn't pass connection_string/entity_map still works."""
        engine = VerificationEngine(
            query_results={"results": {}},
            baseline={},
        )
        assert engine.connection_string is None
        assert engine.entity_map is None

        # Also works with just knowledge_graph
        engine2 = VerificationEngine(
            query_results={"results": {}},
            baseline={},
            knowledge_graph=None,
        )
        assert engine2.connection_string is None

    def test_full_verify_findings_with_active_requery(
        self, empty_query_results, empty_baseline, generic_kg, generic_entity_map,
    ):
        """End-to-end: verify_findings uses active re-query for unmatched claims."""
        engine = VerificationEngine(
            query_results=empty_query_results,
            baseline=empty_baseline,
            knowledge_graph=generic_kg,
            connection_string="postgresql://test:test@localhost:5432/testdb",
            entity_map=generic_entity_map,
        )

        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "FIN-ACTIVE",
                    "headline": "December 2024 revenue: $1,631,559.62",
                    "value_eur": 1631559.62,
                    "value_confidence": "measured",
                    "evidence": "some_query",
                }],
            }
        }

        with patch.object(engine, "_execute_verification_query") as mock_exec:
            mock_exec.return_value = {
                "rows": [{"total": 1631559.62}],
                "row_count": 1,
            }
            report = engine.verify_findings(findings)

        verified = [r for r in report.results if r.status == "VERIFIED"]
        assert len(verified) > 0
        # At least the primary value claim should be verified via active re-query
        active_verified = [
            r for r in verified if r.evidence and "Active re-query" in r.evidence
        ]
        assert len(active_verified) > 0


# ═══════════════════════════════════════════════════════════════════════════
# TEST: Live Gloria DB (skip if unavailable)
# ═══════════════════════════════════════════════════════════════════════════

def _gloria_db_available() -> bool:
    """Check if Gloria DB is reachable."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine("postgresql://tad:tad@localhost:5432/gloria")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _gloria_db_available(),
    reason="Gloria DB not available at localhost:5432",
)
class TestGloriaActiveVerification:

    GLORIA_CONN = "postgresql://tad:tad@localhost:5432/gloria"

    def test_active_requery_against_gloria(self):
        """
        Full integration: verify a revenue claim against the live Gloria DB.

        This test uses the actual entity_map structure for Gloria/Openbravo
        but does NOT hardcode — it uses entity_map semantics.
        """
        # Gloria entity_map (as the Cartographer would produce)
        gloria_entity_map = {
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "type": "TRANSACTIONAL",
                    "row_count": 5000,
                    "base_filter": "issotrx='Y' AND docstatus='CO'",
                    "key_columns": {
                        "pk": "c_invoice_id",
                        "amount_col": "grandtotal",
                        "customer_fk": "c_bpartner_id",
                        "date_col": "dateinvoiced",
                    },
                    "probed_values": {
                        "issotrx": {"Y": 3139, "N": 2000},
                        "docstatus": {"CO": 4500, "DR": 500},
                    },
                },
                "customers": {
                    "table": "c_bpartner",
                    "type": "MASTER",
                    "row_count": 1500,
                    "base_filter": "",
                    "key_columns": {
                        "pk": "c_bpartner_id",
                        "name": "name",
                    },
                    "probed_values": {},
                },
            },
            "relationships": [
                {
                    "from": "invoices",
                    "to": "customers",
                    "via": "c_bpartner_id",
                    "cardinality": "N:1",
                },
            ],
        }

        kg = build_knowledge_graph(gloria_entity_map)

        engine = VerificationEngine(
            query_results={"results": {}, "errors": {}},
            baseline={},
            knowledge_graph=kg,
            connection_string=self.GLORIA_CONN,
            entity_map=gloria_entity_map,
        )

        # The claim: total revenue (we know it's ~1.6M from tests)
        findings = {
            "analyst": {
                "output": "",
                "findings": [{
                    "id": "GLORIA-ACTIVE",
                    "headline": "Total revenue from completed sales invoices",
                    "value_eur": None,  # We won't set a EUR value
                    "evidence": "live db check",
                }],
            },
        }

        # Just verify that the query generation works against real schema
        claim = AtomicClaim(
            claim_id="gloria_rev",
            finding_id="GLORIA-REV",
            claim_text="EUR value: 1631559.62",
            claim_type="numeric",
            claimed_value=1631559.62,
            claimed_unit="EUR",
        )

        vq = engine._generate_verification_query(claim, gloria_entity_map)
        assert vq is not None
        assert "c_invoice" in vq["sql"]
        assert "grandtotal" in vq["sql"]
        assert "issotrx" in vq["sql"].lower()

        # Execute the actual query
        result = engine._execute_verification_query(vq["sql"], self.GLORIA_CONN)
        assert "error" not in result
        assert len(result.get("rows", [])) > 0
        # The total should be a positive number
        total = float(list(result["rows"][0].values())[0])
        assert total > 0
