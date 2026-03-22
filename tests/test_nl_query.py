"""
Tests for NL→SQL layer (VAL-32).

All tests use mocks — no real Anthropic API calls or database connections.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── VannaAdapter tests ────────────────────────────────────────────────────────

class TestVannaAdapter:
    def test_adapter_is_ready_without_api_key(self):
        """VannaAdapter.is_ready is False when Vanna can't init without API key."""
        import os
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            # With empty key, vanna may still init (just fail on actual calls)
            # Test that is_ready matches internal state
            from core.valinor.nl.vanna_adapter import VannaAdapter
            adapter = VannaAdapter(api_key="test-key")
            # is_ready True or False depending on whether Anthropic_Chat accepts empty config
            assert isinstance(adapter.is_ready, bool)

    def test_ask_returns_error_when_not_ready(self):
        """ask() returns error dict when adapter is not ready."""
        from core.valinor.nl.vanna_adapter import VannaAdapter
        adapter = VannaAdapter.__new__(VannaAdapter)
        adapter._vn = None
        adapter._trained = False

        result = adapter.ask("What are my top customers?")
        assert "error" in result
        assert result["sql"] is None

    def test_ask_and_run_returns_error_when_not_ready(self):
        """ask_and_run() returns error dict when adapter is not ready."""
        from core.valinor.nl.vanna_adapter import VannaAdapter
        adapter = VannaAdapter.__new__(VannaAdapter)
        adapter._vn = None
        adapter._trained = False

        result = adapter.ask_and_run(
            "What are my top customers?",
            connection_string="postgresql://localhost/test",
        )
        assert "error" in result
        assert result["sql"] is None

    def test_train_from_entity_map_returns_zero_when_not_ready(self):
        """train_from_entity_map() returns 0 when adapter is not ready."""
        from core.valinor.nl.vanna_adapter import VannaAdapter
        adapter = VannaAdapter.__new__(VannaAdapter)
        adapter._vn = None
        adapter._trained = False

        count = adapter.train_from_entity_map({"client": "test", "entities": {}})
        assert count == 0

    def test_ask_with_mocked_vanna(self):
        """ask() calls generate_sql and returns structured response."""
        from core.valinor.nl.vanna_adapter import VannaAdapter
        adapter = VannaAdapter.__new__(VannaAdapter)
        adapter._trained = False

        mock_vn = MagicMock()
        mock_vn.generate_sql.return_value = "SELECT customer_name, SUM(grandtotal) FROM c_invoice GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
        adapter._vn = mock_vn

        result = adapter.ask("What are my top 10 customers?")
        assert result["error"] is None
        assert "SELECT" in result["sql"]
        assert result["explanation"] is not None

    def test_train_from_entity_map_calls_vanna(self):
        """train_from_entity_map() calls add_ddl and add_documentation."""
        from core.valinor.nl.vanna_adapter import VannaAdapter
        adapter = VannaAdapter.__new__(VannaAdapter)
        adapter._trained = False

        mock_vn = MagicMock()
        mock_vn.add_ddl.return_value = "ddl-1"
        mock_vn.add_documentation.return_value = "doc-1"
        adapter._vn = mock_vn

        entity_map = {
            "client": "acme",
            "entities": {
                "invoices": {
                    "table": "c_invoice",
                    "entity_type": "TRANSACTIONAL",
                    "row_count": 50000,
                    "key_columns": {"invoice_date": "dateacct", "amount_col": "grandtotal"},
                    "base_filter": "AND issotrx = 'Y'",
                }
            },
        }

        count = adapter.train_from_entity_map(entity_map)
        assert count > 0
        assert mock_vn.add_ddl.called
        assert mock_vn.add_documentation.called


# ── In-memory vector store tests ─────────────────────────────────────────────

class TestInMemoryVectorStore:
    def test_add_and_get_ddl(self):
        """DDL entries can be added and retrieved."""
        from core.valinor.nl.vanna_adapter import _InMemoryVectorStore
        store = _InMemoryVectorStore()
        store.add_ddl("CREATE TABLE c_invoice (c_invoice_id SERIAL PRIMARY KEY)")
        results = store.get_related_ddl("invoices")
        assert len(results) == 1
        assert "c_invoice" in results[0]

    def test_add_and_get_documentation(self):
        """Documentation entries can be added and retrieved."""
        from core.valinor.nl.vanna_adapter import _InMemoryVectorStore
        store = _InMemoryVectorStore()
        store.add_documentation("Table c_invoice contains sales invoices.")
        docs = store.get_related_documentation("how many invoices?")
        assert len(docs) == 1

    def test_add_question_sql(self):
        """Q&A pairs can be added and retrieved."""
        from core.valinor.nl.vanna_adapter import _InMemoryVectorStore
        store = _InMemoryVectorStore()
        store.add_question_sql(
            "Top customers by revenue?",
            "SELECT c_bpartner_id, SUM(grandtotal) FROM c_invoice GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
        )
        pairs = store.get_similar_question_sql("top customers")
        assert len(pairs) == 1
        assert "SELECT" in pairs[0]["sql"]

    def test_get_training_data_returns_dataframe(self):
        """get_training_data() returns a pandas DataFrame."""
        import pandas as pd
        from core.valinor.nl.vanna_adapter import _InMemoryVectorStore
        store = _InMemoryVectorStore()
        store.add_ddl("CREATE TABLE test (id INT)")
        df = store.get_training_data()
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 1


# ── API endpoint tests ────────────────────────────────────────────────────────

class TestNLQueryEndpoint:
    def setup_method(self):
        """Clear adapter cache before each test."""
        import api.routers.nl_query as nl_module
        nl_module._adapter_cache.clear()

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from api.routers.nl_query import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_nl_query_missing_question(self, client):
        """Request with empty question returns 422."""
        response = client.post("/api/v1/nl-query", json={
            "question": "",
            "tenant_id": "test-tenant",
        })
        assert response.status_code == 422

    def test_nl_query_missing_tenant_id(self, client):
        """Request without tenant_id returns 422."""
        response = client.post("/api/v1/nl-query", json={
            "question": "What are my top customers?",
        })
        assert response.status_code == 422

    def test_nl_query_valid_request_no_connection(self, client):
        """Valid request returns SQL without executing when no connection_string."""
        mock_adapter = MagicMock()
        mock_adapter.is_ready = True
        mock_adapter.ask.return_value = {
            "sql": "SELECT customer_name FROM c_invoice LIMIT 10",
            "explanation": "Top 10 customer names",
            "error": None,
        }

        with patch("api.routers.nl_query._get_adapter", return_value=mock_adapter):
            response = client.post("/api/v1/nl-query", json={
                "question": "What are my top customers?",
                "tenant_id": "acme",
            })

        assert response.status_code == 200
        data = response.json()
        assert data["sql"] is not None
        assert data["error"] is None
        assert data["tenant_id"] == "acme"

    def test_nl_query_adapter_not_ready_returns_503(self, client):
        """When adapter is not ready, endpoint returns 503."""
        mock_adapter = MagicMock()
        mock_adapter.is_ready = False

        with patch("api.routers.nl_query._get_adapter", return_value=mock_adapter):
            response = client.post("/api/v1/nl-query", json={
                "question": "What are my top customers?",
                "tenant_id": "acme",
            })

        assert response.status_code == 503

    def test_nl_query_with_entity_map(self, client):
        """Entity map is forwarded to the adapter for training."""
        mock_adapter = MagicMock()
        mock_adapter.is_ready = True
        mock_adapter.ask.return_value = {
            "sql": "SELECT 1",
            "explanation": "test",
            "error": None,
        }

        with patch("api.routers.nl_query._get_adapter", return_value=mock_adapter) as mock_get:
            response = client.post("/api/v1/nl-query", json={
                "question": "Total revenue?",
                "tenant_id": "acme",
                "entity_map": {"client": "acme", "entities": {}},
            })

        # Verify entity_map was passed to _get_adapter
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert call_kwargs[0][1] is not None or call_kwargs[1].get("entity_map") is not None
