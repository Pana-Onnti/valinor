"""
Tests for VAL-40 through VAL-43: Swarm improvements.

- VAL-40: Anomaly explanation generation
- VAL-41: Agent quorum model
- VAL-42: Semantic column enrichment
- VAL-43: Zero-row feedback loop
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def sample_entity_map():
    """Standard entity map for testing."""
    return {
        "entities": {
            "invoices": {
                "table": "c_invoice",
                "type": "TRANSACTIONAL",
                "row_count": 4117,
                "key_columns": {
                    "pk": "c_invoice_id",
                    "invoice_date": "dateinvoiced",
                    "amount_col": "grandtotal",
                    "customer_fk": "c_bpartner_id",
                },
                "base_filter": "issotrx='Y' AND docstatus='CO'",
                "probed_values": {
                    "issotrx": {"Y": 2366, "N": 1751},
                    "docstatus": {"CO": 4108, "DR": 9},
                },
            },
            "customers": {
                "table": "c_bpartner",
                "type": "MASTER",
                "row_count": 88,
                "key_columns": {
                    "pk": "c_bpartner_id",
                    "customer_name": "name",
                },
                "base_filter": "",
                "probed_values": {},
            },
        },
        "relationships": [
            {
                "from": "invoices",
                "to": "customers",
                "via": "c_bpartner_id",
                "cardinality": "N:1",
            }
        ],
    }


@pytest.fixture
def sample_kg(sample_entity_map):
    """Build a KG from the sample entity map."""
    from valinor.knowledge_graph import build_knowledge_graph
    return build_knowledge_graph(sample_entity_map)


# ═══════════════════════════════════════════════════════════════════════════
# VAL-40: ANOMALY EXPLANATION
# ═══════════════════════════════════════════════════════════════════════════


class TestAnomalyExplainer:
    """Tests for the anomaly explainer (VAL-40)."""

    def test_anomaly_dataclass(self):
        from valinor.agents.anomaly_explainer import Anomaly

        a = Anomaly(
            metric="total_revenue",
            expected=100000,
            actual=150000,
            deviation_pct=50.0,
            table="c_invoice",
        )
        assert a.direction == "above"
        assert a.abs_deviation_pct == 50.0

    def test_anomaly_below_expected(self):
        from valinor.agents.anomaly_explainer import Anomaly

        a = Anomaly(metric="revenue", expected=100000, actual=60000, deviation_pct=-40.0)
        assert a.direction == "below"

    def test_explain_generates_hypotheses(self, sample_entity_map, sample_kg):
        from valinor.agents.anomaly_explainer import AnomalyExplainer, Anomaly

        explainer = AnomalyExplainer(kg=sample_kg, entity_map=sample_entity_map)
        anomaly = Anomaly(
            metric="total_revenue",
            expected=100000,
            actual=150000,
            deviation_pct=50.0,
            table="c_invoice",
        )
        explanation = explainer.explain(anomaly)

        assert len(explanation.hypotheses) > 0
        assert explanation.summary
        # Should have at least temporal and entity hypotheses
        types = {h.hypothesis_type.value for h in explanation.hypotheses}
        assert "temporal" in types
        assert "entity" in types

    def test_explain_no_table_finds_transactional(self, sample_entity_map, sample_kg):
        from valinor.agents.anomaly_explainer import AnomalyExplainer, Anomaly

        explainer = AnomalyExplainer(kg=sample_kg, entity_map=sample_entity_map)
        anomaly = Anomaly(
            metric="revenue", expected=100, actual=200, deviation_pct=100.0,
        )
        explanation = explainer.explain(anomaly)
        assert len(explanation.hypotheses) > 0

    def test_explain_generates_drill_down_queries(self, sample_entity_map, sample_kg):
        from valinor.agents.anomaly_explainer import AnomalyExplainer, Anomaly

        explainer = AnomalyExplainer(kg=sample_kg, entity_map=sample_entity_map)
        anomaly = Anomaly(
            metric="revenue", expected=100000, actual=50000,
            deviation_pct=-50.0, table="c_invoice",
        )
        explanation = explainer.explain(anomaly)

        queries_found = sum(
            1 for h in explanation.hypotheses if h.drill_down_query is not None
        )
        assert queries_found > 0

    def test_evaluate_entity_hypothesis_supported(self, sample_entity_map, sample_kg):
        from valinor.agents.anomaly_explainer import (
            AnomalyExplainer, Anomaly, Hypothesis, HypothesisType, HypothesisStatus,
        )

        explainer = AnomalyExplainer(kg=sample_kg, entity_map=sample_entity_map)
        h = Hypothesis(
            hypothesis_id="test",
            hypothesis_type=HypothesisType.ENTITY,
            description="test",
        )
        result = explainer.evaluate_hypothesis(h, {
            "rows": [
                {"customer_fk": "C001", "entity_total": 80000, "pct_of_total": 45.0},
                {"customer_fk": "C002", "entity_total": 20000, "pct_of_total": 11.0},
            ]
        })
        assert result.status == HypothesisStatus.SUPPORTED
        assert result.confidence > 0.3

    def test_evaluate_entity_hypothesis_refuted(self, sample_entity_map, sample_kg):
        from valinor.agents.anomaly_explainer import (
            AnomalyExplainer, Hypothesis, HypothesisType, HypothesisStatus,
        )

        explainer = AnomalyExplainer(kg=sample_kg, entity_map=sample_entity_map)
        h = Hypothesis(
            hypothesis_id="test",
            hypothesis_type=HypothesisType.ENTITY,
            description="test",
        )
        result = explainer.evaluate_hypothesis(h, {
            "rows": [
                {"customer_fk": "C001", "entity_total": 20000, "pct_of_total": 10.0},
            ]
        })
        assert result.status == HypothesisStatus.REFUTED

    def test_evaluate_data_quality_hypothesis(self, sample_entity_map, sample_kg):
        from valinor.agents.anomaly_explainer import (
            AnomalyExplainer, Hypothesis, HypothesisType, HypothesisStatus,
        )

        explainer = AnomalyExplainer(kg=sample_kg, entity_map=sample_entity_map)
        h = Hypothesis(
            hypothesis_id="test",
            hypothesis_type=HypothesisType.DATA_QUALITY,
            description="test",
        )
        result = explainer.evaluate_hypothesis(h, {
            "rows": [{"total_rows": 1000, "null_count": 100, "null_pct": 10.0}]
        })
        assert result.status == HypothesisStatus.SUPPORTED

    def test_select_best_hypothesis(self, sample_entity_map, sample_kg):
        from valinor.agents.anomaly_explainer import (
            AnomalyExplainer, Anomaly, AnomalyExplanation,
            Hypothesis, HypothesisType, HypothesisStatus,
        )

        explainer = AnomalyExplainer(kg=sample_kg, entity_map=sample_entity_map)
        explanation = AnomalyExplanation(
            anomaly=Anomaly(metric="x", expected=100, actual=200, deviation_pct=100),
            hypotheses=[
                Hypothesis(
                    hypothesis_id="h1", hypothesis_type=HypothesisType.TEMPORAL,
                    description="t1", status=HypothesisStatus.SUPPORTED, confidence=0.6,
                ),
                Hypothesis(
                    hypothesis_id="h2", hypothesis_type=HypothesisType.ENTITY,
                    description="t2", status=HypothesisStatus.SUPPORTED, confidence=0.9,
                ),
            ],
        )
        result = explainer.select_best_hypothesis(explanation)
        assert result.best_hypothesis is not None
        assert result.best_hypothesis.hypothesis_id == "h2"

    def test_anomaly_explanation_pydantic_schema(self):
        from valinor.schemas.agent_outputs import (
            AnomalyInput, HypothesisResult, AnomalyExplanationOutput,
            HypothesisType as HT, HypothesisStatus as HS,
        )

        model = AnomalyExplanationOutput(
            anomaly=AnomalyInput(
                metric="revenue", expected=100.0, actual=150.0, deviation_pct=50.0,
            ),
            hypotheses=[
                HypothesisResult(
                    hypothesis_id="h1",
                    hypothesis_type=HT.TEMPORAL,
                    description="Seasonal pattern",
                    status=HS.SUPPORTED,
                    confidence=0.8,
                ),
            ],
            best_hypothesis_id="h1",
            summary="Seasonal pattern detected.",
            explained=True,
        )
        assert model.explained
        assert len(model.supported_hypotheses) == 1


# ═══════════════════════════════════════════════════════════════════════════
# VAL-41: QUORUM MODEL
# ═══════════════════════════════════════════════════════════════════════════


class TestQuorumVoter:
    """Tests for the quorum voter (VAL-41)."""

    def test_basic_quorum_accept(self):
        from valinor.quorum import QuorumVoter, Vote

        voter = QuorumVoter(threshold=0.5)
        fid = voter.submit_finding("analyst", {"id": "FIN-001", "domain": "financial"})
        voter.cast_vote(fid, "sentinel", Vote.AGREE, confidence=0.8)
        voter.cast_vote(fid, "hunter", Vote.AGREE, confidence=0.7)

        report = voter.tally()
        assert report.total_findings == 1
        assert len(report.accepted_findings) == 1
        assert report.results[0].accepted
        assert report.results[0].agree_count == 3  # analyst auto-agree + 2

    def test_basic_quorum_reject(self):
        from valinor.quorum import QuorumVoter, Vote

        voter = QuorumVoter(threshold=0.5)
        fid = voter.submit_finding("analyst", {"id": "FIN-001"})
        voter.cast_vote(fid, "sentinel", Vote.DISAGREE, reason="Value mismatch")
        voter.cast_vote(fid, "hunter", Vote.DISAGREE, reason="Not in data")

        report = voter.tally()
        assert len(report.rejected_findings) == 1
        assert not report.results[0].accepted
        assert len(report.results[0].dissenting_reasons) == 2

    def test_abstain_does_not_count(self):
        from valinor.quorum import QuorumVoter, Vote

        voter = QuorumVoter(threshold=0.5)
        fid = voter.submit_finding("analyst", {"id": "FIN-001"})
        voter.cast_vote(fid, "sentinel", Vote.ABSTAIN)
        voter.cast_vote(fid, "hunter", Vote.ABSTAIN)

        report = voter.tally()
        # Only 1 vote (auto-agree from analyst), 0 disagree → ratio = 1.0
        assert report.results[0].accepted
        assert report.results[0].abstain_count == 2

    def test_configurable_threshold(self):
        from valinor.quorum import QuorumVoter, Vote

        voter = QuorumVoter(threshold=0.75)
        fid = voter.submit_finding("analyst", {"id": "FIN-001"})
        voter.cast_vote(fid, "sentinel", Vote.AGREE)
        voter.cast_vote(fid, "hunter", Vote.DISAGREE)

        report = voter.tally()
        # 2 agree, 1 disagree → ratio = 0.667 < 0.75 → rejected
        assert not report.results[0].accepted

    def test_duplicate_vote_ignored(self):
        from valinor.quorum import QuorumVoter, Vote

        voter = QuorumVoter()
        fid = voter.submit_finding("analyst", {"id": "FIN-001"})
        assert voter.cast_vote(fid, "sentinel", Vote.AGREE)
        assert not voter.cast_vote(fid, "sentinel", Vote.DISAGREE)

    def test_vote_unknown_finding(self):
        from valinor.quorum import QuorumVoter, Vote

        voter = QuorumVoter()
        assert not voter.cast_vote("nonexistent", "sentinel", Vote.AGREE)

    def test_invalid_threshold(self):
        from valinor.quorum import QuorumVoter

        with pytest.raises(ValueError):
            QuorumVoter(threshold=1.5)

    def test_finding_ballot_properties(self):
        from valinor.quorum import FindingBallot, AgentVote, Vote

        ballot = FindingBallot(
            finding_id="test", finding={}, source_agent="analyst",
            votes=[
                AgentVote(agent_name="a", vote=Vote.AGREE),
                AgentVote(agent_name="b", vote=Vote.DISAGREE),
                AgentVote(agent_name="c", vote=Vote.ABSTAIN),
            ],
        )
        assert ballot.agree_count == 1
        assert ballot.disagree_count == 1
        assert ballot.abstain_count == 1
        assert ballot.voting_count == 2
        assert ballot.agreement_ratio == 0.5

    def test_reconcile_with_quorum_no_findings(self):
        from valinor.quorum import reconcile_with_quorum

        result = reconcile_with_quorum({
            "analyst": {"output": "no structured data"},
        })
        assert "_quorum_report" in result
        assert result["_quorum_report"]["total_findings"] == 0

    def test_reconcile_with_quorum_agreeing_agents(self):
        import json
        from valinor.quorum import reconcile_with_quorum

        findings = {
            "analyst": {
                "output": json.dumps([
                    {"id": "FIN-001", "domain": "financial", "value_eur": 1000000},
                ]),
            },
            "sentinel": {
                "output": json.dumps([
                    {"id": "DQ-001", "domain": "financial", "value_eur": 1050000},
                ]),
            },
        }
        result = reconcile_with_quorum(findings, threshold=0.5)
        report = result["_quorum_report"]
        assert report["ran"]
        assert report["total_findings"] >= 1

    def test_quorum_report_pydantic_schema(self):
        from valinor.schemas.agent_outputs import QuorumReportOutput, QuorumFindingResult

        model = QuorumReportOutput(
            threshold=0.5,
            total_findings=3,
            accepted=2,
            rejected=1,
            acceptance_rate=0.67,
            summary="test",
            results=[
                QuorumFindingResult(
                    finding_id="FIN-001", accepted=True,
                    agreement_ratio=1.0, confidence=0.9,
                    votes="3A/0D/0X",
                ),
            ],
        )
        assert model.ran
        assert len(model.results) == 1

    def test_reset(self):
        from valinor.quorum import QuorumVoter

        voter = QuorumVoter()
        voter.submit_finding("analyst", {"id": "FIN-001"})
        assert voter.tally().total_findings == 1
        voter.reset()
        assert voter.tally().total_findings == 0


# ═══════════════════════════════════════════════════════════════════════════
# VAL-42: SEMANTIC COLUMN ENRICHMENT
# ═══════════════════════════════════════════════════════════════════════════


class TestSemanticEnricher:
    """Tests for the semantic column enricher (VAL-42)."""

    def test_classify_amount_by_name(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column("grandtotal", "c_invoice")
        assert col.semantic_type == SemanticColumnType.AMOUNT
        assert col.confidence > 0.5

    def test_classify_date_by_name(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column("dateinvoiced", "c_invoice")
        assert col.semantic_type == SemanticColumnType.DATE

    def test_classify_identifier_by_name(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column("c_invoice_id", "c_invoice")
        assert col.semantic_type == SemanticColumnType.IDENTIFIER

    def test_classify_status_by_name(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column("docstatus", "c_invoice")
        assert col.semantic_type == SemanticColumnType.STATUS

    def test_classify_flag_by_name(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column("isactive", "c_invoice")
        assert col.semantic_type == SemanticColumnType.FLAG

    def test_classify_by_data_pattern_amount(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column(
            "col1", "test_table",
            sample_values=["123.45", "678.90", "234.56", "890.12", "345.67"],
        )
        # Data pattern should detect amount
        assert col.data_signal == SemanticColumnType.AMOUNT

    def test_classify_by_data_pattern_boolean(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column(
            "col1", "test_table",
            sample_values=["Y", "N", "Y", "Y", "N", "Y"],
        )
        assert col.data_signal == SemanticColumnType.FLAG

    def test_name_and_data_agree_boosts_confidence(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column(
            "total_amount", "test_table",
            sample_values=["100.50", "200.75", "350.00", "475.25", "600.00"],
        )
        assert col.semantic_type == SemanticColumnType.AMOUNT
        assert col.confidence > col.name_confidence  # boosted by agreement

    def test_enrich_table(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher

        enricher = SemanticEnricher()
        result = enricher.enrich_table("c_invoice", {
            "dateinvoiced": {"sample_values": ["2024-01-15", "2024-02-20"], "db_type": "date"},
            "grandtotal": {"sample_values": ["1000.50", "2000.75"], "db_type": "numeric"},
            "c_invoice_id": {"sample_values": ["1001", "1002", "1003"], "db_type": "integer"},
        })
        assert len(result.date_columns) >= 1
        assert len(result.amount_columns) >= 1

    def test_enrich_from_entity_map(self, sample_entity_map):
        from valinor.discovery.semantic_enricher import SemanticEnricher

        enricher = SemanticEnricher()
        results = enricher.enrich_from_entity_map(sample_entity_map)
        assert "c_invoice" in results
        assert len(results["c_invoice"].columns) > 0

    def test_generate_alternatives(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column("grandtotal", "c_invoice")
        assert len(col.alternative_names) > 0
        assert "grandtotal" not in [a.lower() for a in col.alternative_names]

    def test_unknown_column_name(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column("xyz_abc_123", "test_table")
        assert col.semantic_type == SemanticColumnType.UNKNOWN

    def test_db_type_signal(self):
        from valinor.discovery.semantic_enricher import SemanticEnricher, SemanticColumnType

        enricher = SemanticEnricher()
        col = enricher.enrich_column("my_col", "test_table", db_type="timestamp")
        # DB type should provide a signal even with unknown name
        assert col.semantic_type == SemanticColumnType.DATE


# ═══════════════════════════════════════════════════════════════════════════
# VAL-43: ZERO-ROW FEEDBACK LOOP
# ═══════════════════════════════════════════════════════════════════════════


class TestZeroRowReformulation:
    """Tests for zero-row query reformulation (VAL-43)."""

    def test_relax_date_filters(self, sample_entity_map, sample_kg):
        from valinor.agents.query_generator import QueryGenerator

        gen = QueryGenerator(
            kg=sample_kg,
            entity_map=sample_entity_map,
            period={"start": "2024-01-01", "end": "2024-12-31"},
        )
        original = {
            "id": "revenue_summary",
            "sql": "SELECT SUM(grandtotal) FROM c_invoice WHERE dateinvoiced >= '2024-01-01' AND dateinvoiced <= '2024-12-31'",
            "description": "Revenue summary",
        }
        reformulations = gen.reformulate_zero_row_query(original)
        assert len(reformulations) > 0

        # First reformulation should be date relaxation
        first = reformulations[0]
        assert first["reformulation_strategy"] == "relax_date_filters"
        assert "2023" in first["sql"]  # date shifted back ~6 months

    def test_remove_filters(self, sample_entity_map, sample_kg):
        from valinor.agents.query_generator import QueryGenerator

        gen = QueryGenerator(
            kg=sample_kg,
            entity_map=sample_entity_map,
            period={"start": "2024-01-01", "end": "2024-12-31"},
        )
        original = {
            "id": "test",
            "sql": "SELECT COUNT(*) FROM c_invoice WHERE issotrx='Y' AND docstatus='CO' AND isactive='Y'",
            "description": "Test query",
        }
        reformulations = gen.reformulate_zero_row_query(original, max_retries=5)

        # Should have variants with filters removed
        filter_removed = [r for r in reformulations if "remove_filter" in r["reformulation_strategy"]]
        assert len(filter_removed) > 0

    def test_alternative_columns(self, sample_entity_map, sample_kg):
        from valinor.agents.query_generator import QueryGenerator

        gen = QueryGenerator(
            kg=sample_kg,
            entity_map=sample_entity_map,
            period={"start": "2024-01-01", "end": "2024-12-31"},
        )
        original = {
            "id": "test",
            "sql": "SELECT SUM(grandtotal) FROM c_invoice WHERE dateinvoiced >= '2024-01-01'",
            "description": "Test",
        }
        semantic = {
            "grandtotal": ["amount_total", "total"],
        }
        reformulations = gen.reformulate_zero_row_query(
            original, semantic_enrichment=semantic,
        )

        alt_reforms = [r for r in reformulations if r["reformulation_strategy"] == "alternative_columns"]
        if alt_reforms:
            assert "amount_total" in alt_reforms[0]["sql"] or "total" in alt_reforms[0]["sql"]

    def test_max_retries_limit(self, sample_entity_map, sample_kg):
        from valinor.agents.query_generator import QueryGenerator

        gen = QueryGenerator(
            kg=sample_kg,
            entity_map=sample_entity_map,
            period={"start": "2024-01-01", "end": "2024-12-31"},
        )
        original = {
            "id": "test",
            "sql": "SELECT COUNT(*) FROM c_invoice WHERE issotrx='Y' AND docstatus='CO' AND dateinvoiced >= '2024-01-01' AND dateinvoiced <= '2024-12-31'",
            "description": "Test",
        }
        reformulations = gen.reformulate_zero_row_query(original, max_retries=2)
        assert len(reformulations) <= 2

    def test_no_reformulation_for_simple_query(self, sample_entity_map, sample_kg):
        from valinor.agents.query_generator import QueryGenerator

        gen = QueryGenerator(
            kg=sample_kg,
            entity_map=sample_entity_map,
            period={"start": "2024-01-01", "end": "2024-12-31"},
        )
        original = {
            "id": "test",
            "sql": "SELECT COUNT(*) FROM c_invoice",
            "description": "Count all",
        }
        reformulations = gen.reformulate_zero_row_query(original)
        # No WHERE clause → nothing to relax/remove
        assert len(reformulations) == 0

    def test_reformulation_metadata(self, sample_entity_map, sample_kg):
        from valinor.agents.query_generator import QueryGenerator

        gen = QueryGenerator(
            kg=sample_kg,
            entity_map=sample_entity_map,
            period={"start": "2024-01-01", "end": "2024-12-31"},
        )
        original = {
            "id": "rev",
            "sql": "SELECT SUM(grandtotal) FROM c_invoice WHERE dateinvoiced >= '2024-01-01' AND dateinvoiced <= '2024-12-31'",
            "description": "Revenue",
        }
        reformulations = gen.reformulate_zero_row_query(original)
        for r in reformulations:
            assert "id" in r
            assert "sql" in r
            assert "reformulation_strategy" in r
            assert "attempt" in r
            assert r["attempt"] >= 1
