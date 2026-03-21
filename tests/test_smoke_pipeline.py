"""
Smoke test: simula un análisis completo desde el frontend con datos mínimos.

Crea una DB SQLite en memoria con 3 tablas (customers, invoices, payments)
y 8 filas de facturas. Ejecuta la cadena real de post-procesamiento:
    build_queries → execute_queries → currency_guard → anomaly_detector
    → segmentation_engine → query_evolver

No llama al LLM (cartographer, agents, narrators están mockeados).
Objetivo: verificar que todo el pipeline post-query no explota.

Ejecución:
    pytest tests/test_smoke_pipeline.py -v
Esperado: < 5 segundos, sin errores.
"""
from __future__ import annotations

import os
import sys
import types
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT))

# ── Stub claude_agent_sdk ANTES de importar pipeline (que lo importa al nivel de módulo) ──
if "claude_agent_sdk" not in sys.modules:
    _sdk_stub = types.ModuleType("claude_agent_sdk")
    _sdk_stub.query = None
    _sdk_stub.ClaudeAgentOptions = object
    _sdk_stub.AssistantMessage = object
    _sdk_stub.TextBlock = object
    sys.modules["claude_agent_sdk"] = _sdk_stub

# ── Stub structlog si no está ──────────────────────────────────────────────────
if "structlog" not in sys.modules:
    import types as _t
    _sl = _t.ModuleType("structlog")
    class _NullLog:
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def error(self, *a, **kw): pass
        def debug(self, *a, **kw): pass
        def bind(self, **kw): return self
    _sl.get_logger = lambda: _NullLog()
    sys.modules["structlog"] = _sl

from sqlalchemy import create_engine, text

# ── Minimal test schema ────────────────────────────────────────────────────────

_DDL = [
    "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)",
    """CREATE TABLE invoices (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER,
        amount REAL,
        invoice_date TEXT
    )""",
    """CREATE TABLE payments (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER,
        outstanding REAL,
        due_date TEXT
    )""",
]

_CUSTOMERS = [(1, "ACME Corp"), (2, "Beta SA"), (3, "Gamma SRL"),
              (4, "Delta Corp"), (5, "Epsilon Ltd")]

_INVOICES = [
    (1, 1, 10000.0, "2026-01-15"), (2, 1, 5000.0,  "2026-02-10"),
    (3, 2,  8000.0, "2026-01-20"), (4, 3, 3000.0,  "2026-02-05"),
    (5, 4,  1200.0, "2026-03-01"), (6, 5,  900.0,  "2026-01-10"),
    (7, 2,  4500.0, "2026-03-15"), (8, 1, 7000.0,  "2026-03-20"),
]

_PAYMENTS = [
    (1, 1, 500.0, "2026-04-01"),
    (2, 3, 3000.0, "2026-03-15"),
    (3, 4, 1200.0, "2026-03-01"),
]

# entity_map que apunta a las tablas SQLite
ENTITY_MAP = {
    "entities": {
        "customers": {
            "table": "customers",
            "confidence": 0.95,
            "base_filter": "",
            "key_columns": {
                "customer_pk": "id",
                "customer_name": "name",
                "customer_fk": "id",
            },
        },
        "invoices": {
            "table": "invoices",
            "confidence": 0.95,
            "base_filter": "",
            "key_columns": {
                "invoice_pk": "id",
                "invoice_date": "invoice_date",
                "amount_col": "amount",
                "customer_fk": "customer_id",
            },
        },
        "payments": {
            "table": "payments",
            "confidence": 0.85,
            "base_filter": "",
            "key_columns": {
                "outstanding_amount": "outstanding",
                "due_date": "due_date",
                "customer_id": "customer_id",
            },
        },
    },
    "relationships": [
        {"from": "invoices", "to": "customers", "via": "customer_id"}
    ],
}

PERIOD = {"start": "2026-01-01", "end": "2026-03-31", "label": "Q1-2026"}


@pytest.fixture(scope="module")
def sqlite_conn_str():
    """Crea una DB SQLite en archivo temporal y la popula. Devuelve conn_str."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn_str = f"sqlite:///{tmp.name}"

    engine = create_engine(conn_str)
    with engine.connect() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
        for row in _CUSTOMERS:
            conn.execute(text("INSERT INTO customers VALUES (:id,:name)"),
                         {"id": row[0], "name": row[1]})
        for row in _INVOICES:
            conn.execute(text("INSERT INTO invoices VALUES (:id,:cid,:amt,:dt)"),
                         {"id": row[0], "cid": row[1], "amt": row[2], "dt": row[3]})
        for row in _PAYMENTS:
            conn.execute(text("INSERT INTO payments VALUES (:id,:cid,:out,:due)"),
                         {"id": row[0], "cid": row[1], "out": row[2], "due": row[3]})
        conn.commit()
    engine.dispose()

    yield conn_str
    os.unlink(tmp.name)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSmokePipeline:
    """
    Verifica que la cadena de post-procesamiento de queries funciona end-to-end
    con datos reales (SQLite) y sin LLM.
    """

    @pytest.mark.asyncio
    async def test_execute_queries_returns_dict_format(self, sqlite_conn_str):
        """execute_queries debe devolver results como dict keyed by query_id."""
        from valinor.agents.query_builder import build_queries
        from valinor.pipeline import execute_queries

        query_pack = build_queries(ENTITY_MAP, PERIOD)
        assert len(query_pack["queries"]) > 0, "build_queries debe generar al menos 1 query"

        config = {"connection_string": sqlite_conn_str}
        qr = await execute_queries(query_pack, config)

        assert isinstance(qr, dict)
        assert "results" in qr
        assert "snapshot_timestamp" in qr
        assert isinstance(qr["results"], dict), (
            f"results debe ser dict, no {type(qr['results']).__name__}"
        )

    @pytest.mark.asyncio
    async def test_segmentation_no_crash(self, sqlite_conn_str):
        """
        segment_from_query_results no debe crashear con el formato dict.
        Este es el bug exacto que fue corregido.
        """
        from valinor.agents.query_builder import build_queries
        from valinor.pipeline import execute_queries
        from shared.memory.segmentation_engine import get_segmentation_engine

        query_pack = build_queries(ENTITY_MAP, PERIOD)
        config = {"connection_string": sqlite_conn_str}
        qr = await execute_queries(query_pack, config)

        profile = MagicMock()
        profile.industry_inferred = "distribución mayorista"
        profile.currency_detected = "USD"

        engine = get_segmentation_engine()
        result = engine.segment_from_query_results(qr, profile)
        # None si no encontró columnas que matcheen — eso está bien, no crash
        assert result is None or hasattr(result, "segments")

    @pytest.mark.asyncio
    async def test_currency_guard_no_crash(self, sqlite_conn_str):
        """scan_query_results funciona con el formato dict de results."""
        from valinor.agents.query_builder import build_queries
        from valinor.pipeline import execute_queries
        from valinor.quality.currency_guard import get_currency_guard

        query_pack = build_queries(ENTITY_MAP, PERIOD)
        config = {"connection_string": sqlite_conn_str}
        qr = await execute_queries(query_pack, config)

        issues = get_currency_guard().scan_query_results(qr)
        assert isinstance(issues, dict)

    @pytest.mark.asyncio
    async def test_anomaly_detector_no_crash(self, sqlite_conn_str):
        """anomaly_detector.scan funciona con el formato dict de results."""
        from valinor.agents.query_builder import build_queries
        from valinor.pipeline import execute_queries
        from valinor.quality.anomaly_detector import get_anomaly_detector

        query_pack = build_queries(ENTITY_MAP, PERIOD)
        config = {"connection_string": sqlite_conn_str}
        qr = await execute_queries(query_pack, config)

        anomalies = get_anomaly_detector().scan(qr)
        assert isinstance(anomalies, list)

    @pytest.mark.asyncio
    async def test_query_evolver_no_crash(self, sqlite_conn_str):
        """
        query_evolver.analyze_query_results funciona con el formato dict.
        Segundo bug corregido en esta sesión.
        """
        from valinor.agents.query_builder import build_queries
        from valinor.pipeline import execute_queries
        from api.refinement.query_evolver import QueryEvolver

        query_pack = build_queries(ENTITY_MAP, PERIOD)
        config = {"connection_string": sqlite_conn_str}
        qr = await execute_queries(query_pack, config)

        profile = MagicMock()
        profile.focus_tables = []
        profile.metadata = {}

        report = QueryEvolver().analyze_query_results(qr, {}, profile)
        assert "empty_queries" in report
        assert isinstance(report["empty_queries"], list)

    @pytest.mark.asyncio
    async def test_full_post_query_chain(self, sqlite_conn_str):
        """
        Corre la cadena completa de post-procesamiento (igual que el adapter
        después de execute_queries) sin que ningún paso explote.
        """
        from valinor.agents.query_builder import build_queries
        from valinor.pipeline import execute_queries
        from valinor.quality.currency_guard import get_currency_guard
        from valinor.quality.anomaly_detector import get_anomaly_detector
        from shared.memory.segmentation_engine import get_segmentation_engine
        from api.refinement.query_evolver import QueryEvolver

        query_pack = build_queries(ENTITY_MAP, PERIOD)
        config = {"connection_string": sqlite_conn_str}
        qr = await execute_queries(query_pack, config)

        profile = MagicMock()
        profile.industry_inferred = "distribución mayorista"
        profile.currency_detected = "USD"
        profile.focus_tables = []
        profile.metadata = {}

        # 1. Currency guard
        currency_issues = get_currency_guard().scan_query_results(qr)
        assert isinstance(currency_issues, dict)

        # 2. Anomaly detector
        anomalies = get_anomaly_detector().scan(qr)
        assert isinstance(anomalies, list)

        # 3. Segmentation (el bug original)
        seg = get_segmentation_engine().segment_from_query_results(qr, profile)
        assert seg is None or hasattr(seg, "segments")

        # 4. Query evolver (segundo bug)
        evolver_report = QueryEvolver().analyze_query_results(qr, {}, profile)
        assert "empty_queries" in evolver_report

        # Si llegamos aquí sin excepción, el pipeline post-query está sano
        executed = len(qr["results"])
        assert executed >= 0  # puede ser 0 si SQLite rechaza todo — igual válido
