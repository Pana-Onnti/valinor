"""
Performance tests for CPU-bound operations in Valinor SaaS.

Each test verifies that a given operation completes within a generous
tolerance (roughly 10x the expected hot-path cost) to remain stable
on CI runners with variable load.

All timings use time.perf_counter() — no external services required.
"""
from __future__ import annotations

import sys
import time
import math
import random
from pathlib import Path
from datetime import datetime

import pytest

# ---------------------------------------------------------------------------
# Path setup — project root and core/ must be importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "core"))


# ===========================================================================
# 1. benford_test — 10,000 values < 1 second
# ===========================================================================

def test_benford_check_completes_under_1s():
    """benford_test on 10,000 values completes in under 1 second."""
    from valinor.quality.statistical_checks import benford_test

    rng = random.Random(42)
    # Natural financial-like values (log-uniform between 1 and 1,000,000)
    values = [math.exp(rng.uniform(0, math.log(1_000_000))) for _ in range(10_000)]

    start = time.perf_counter()
    result = benford_test(values)
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"benford_test took {elapsed:.3f}s, expected < 1.0s"
    assert "n_samples" in result


# ===========================================================================
# 2. cusum_structural_break — 1,000 points < 100 ms
# ===========================================================================

def test_cusum_check_completes_under_100ms():
    """cusum_structural_break on 1,000 points completes in under 100 ms."""
    from valinor.quality.statistical_checks import cusum_structural_break

    rng = random.Random(7)
    series = [rng.gauss(100.0, 10.0) for _ in range(1_000)]

    start = time.perf_counter()
    result = cusum_structural_break(series)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.1, f"cusum_structural_break took {elapsed:.3f}s, expected < 0.1s"
    assert "break_detected" in result


# ===========================================================================
# 3. format_currency — 1,000 calls < 100 ms
# ===========================================================================

def test_format_currency_1000_calls_under_100ms():
    """Calling format_currency 1,000 times completes in under 100 ms."""
    from shared.utils.formatting import format_currency

    currencies = ["EUR", "USD", "GBP", "ARS", "BRL", "MXN"]
    rng = random.Random(13)
    calls = [
        (rng.uniform(-1_000_000, 1_000_000), currencies[i % len(currencies)])
        for i in range(1_000)
    ]

    start = time.perf_counter()
    for value, currency in calls:
        format_currency(value, currency=currency)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.1, f"format_currency x1000 took {elapsed:.3f}s, expected < 0.1s"


# ===========================================================================
# 4. parse_period — 100 calls < 10 ms
# ===========================================================================

def test_parse_period_100_calls_under_10ms():
    """Calling parse_period 100 times completes in under 10 ms."""
    from shared.utils.date_utils import parse_period

    periods = (
        [f"Q{q}-{y}" for q in range(1, 5) for y in range(2020, 2026)]
        + [f"H{h}-{y}" for h in (1, 2) for y in range(2020, 2026)]
        + [str(y) for y in range(2010, 2026)]
    )
    # Cycle through the list to reach 100 calls
    calls = [periods[i % len(periods)] for i in range(100)]

    start = time.perf_counter()
    for period in calls:
        parse_period(period)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.01, f"parse_period x100 took {elapsed:.3f}s, expected < 0.01s"


# ===========================================================================
# 5. ProfileExtractor.update_from_run — 100 findings < 500 ms
# ===========================================================================

def test_profile_extractor_100_findings_under_500ms():
    """update_from_run with 100 findings completes in under 500 ms."""
    from shared.memory.client_profile import ClientProfile
    from shared.memory.profile_extractor import ProfileExtractor

    profile = ClientProfile.new("perf-test-client")
    extractor = ProfileExtractor()

    severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    findings_list = [
        {
            "id": f"finding-{i:04d}",
            "finding_id": f"finding-{i:04d}",
            "title": f"Test finding number {i}",
            "severity": severities[i % len(severities)],
            "sql": f"SELECT * FROM orders WHERE id = {i}",
        }
        for i in range(100)
    ]

    agent_findings = {"analyst": {"findings": findings_list}}
    entity_map = {"entities": {}}
    reports = {"executive": ""}

    start = time.perf_counter()
    delta = extractor.update_from_run(
        profile=profile,
        findings=agent_findings,
        entity_map=entity_map,
        reports=reports,
        period="Q1-2026",
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"update_from_run took {elapsed:.3f}s, expected < 0.5s"
    assert len(delta["new"]) == 100


# ===========================================================================
# 6. slugify — 10,000 calls < 500 ms
# ===========================================================================

def test_slugify_10000_calls_under_500ms():
    """slugify called 10,000 times completes in under 500 ms."""
    from shared.utils.formatting import slugify

    texts = [
        "Acme Corp S.A.",
        "Distribuidora Ñoño & Cía.",
        "El Árbol de la Vida Ltda.",
        "Société Générale International",
        "Müller & Söhne GmbH",
        "日本語テスト",
        "Revenue Q3-2025",
        "hallazgo crítico #42",
        "  spaces   everywhere  ",
        "UPPERCASE INPUT",
    ]
    calls = [texts[i % len(texts)] for i in range(10_000)]

    start = time.perf_counter()
    for text in calls:
        slugify(text)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"slugify x10000 took {elapsed:.3f}s, expected < 0.5s"


# ===========================================================================
# 7. AnomalyDetector.scan — 1,000 rows × 5 queries < 2 seconds
# ===========================================================================

def test_anomaly_detector_scan_1000_rows_under_2s():
    """AnomalyDetector.scan on 5 queries with 1,000 rows each completes in under 2 s."""
    from valinor.quality.anomaly_detector import AnomalyDetector

    rng = random.Random(99)

    def _make_rows(n: int) -> list[dict]:
        rows = []
        for _ in range(n):
            amount = rng.lognormvariate(10, 2)
            rows.append({"amount": amount, "total": amount * rng.uniform(0.9, 1.1)})
        # Inject a handful of outliers
        for _ in range(5):
            rows.append({"amount": rng.uniform(1e9, 1e10), "total": 0.0})
        return rows

    query_results = {
        "results": {
            f"q{i}": {
                "columns": ["amount", "total"],
                "rows": _make_rows(1_000),
            }
            for i in range(5)
        }
    }

    detector = AnomalyDetector()

    start = time.perf_counter()
    anomalies = detector.scan(query_results)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"AnomalyDetector.scan took {elapsed:.3f}s, expected < 2.0s"
    assert isinstance(anomalies, list)


# ===========================================================================
# 8. build_executive_system_prompt — full memory dict < 100 ms
# ===========================================================================

def test_build_executive_prompt_under_100ms():
    """build_executive_system_prompt with a fully-populated memory dict completes in under 100 ms."""
    from valinor.agents.narrators.system_prompts import build_executive_system_prompt

    memory = {
        "data_quality_context": "DQ Score: 92. All 8 checks passed. Snapshot isolation active.",
        "factor_model_context": (
            "Revenue change decomposition: Volume -5%, Price +3%, Mix +2%.\n"
            "Net effect: -0.2% vs prior period."
        ),
        "adaptive_context": {"currency": "EUR"},
        "currency_context": "Moneda detectada: EUR. Tipo de cambio: 1.0.",
        "segmentation_context": (
            "Champions: 45 clientes (€2.1M revenue).\n"
            "At Risk: 12 clientes (€340K revenue)."
        ),
        "statistical_anomalies": (
            "ANOMALÍAS (2): [HIGH] q1/amount: 3 outliers = 22% del total."
        ),
        "sentinel_patterns": "Patrón: facturas duplicadas detectadas (3 pares).",
        "cusum_warning": "Ruptura descendente detectada en últimos 2 períodos (CUSUM=6.8).",
        "benford_warning": "MAD=0.018 > umbral. Posible manipulación en campo 'price'.",
        "query_evolution_context": {
            "empty_queries": ["q_inventory_aging"],
            "high_value_tables": ["invoices", "orders", "payments"],
        },
        "run_history_summary": {
            "currency": "EUR",
            "persistent_findings": [
                {"title": "AR aging spike >90 days", "runs_open": 6},
                {"title": "Duplicate invoice detected", "runs_open": 4},
            ],
        },
    }

    start = time.perf_counter()
    prompt = build_executive_system_prompt(memory)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.1, f"build_executive_system_prompt took {elapsed:.3f}s, expected < 0.1s"
    assert isinstance(prompt, str)
    assert len(prompt) > 100


# ===========================================================================
# 9. build_adaptive_context — profile with 20 findings < 50 ms
# ===========================================================================

def test_adaptive_context_builder_under_50ms():
    """build_adaptive_context on a ClientProfile with 20 known findings completes in under 50 ms."""
    from shared.memory.client_profile import ClientProfile
    from shared.memory.adaptive_context_builder import build_adaptive_context

    profile = ClientProfile.new("perf-test-adaptive")
    profile.industry_inferred = "Distribución mayorista"
    profile.currency_detected = "ARS"
    profile.run_count = 15
    profile.last_run_date = datetime.utcnow().isoformat()
    profile.focus_tables = ["invoices", "orders", "payments", "customers", "products"]
    profile.alert_thresholds = [
        {"label": f"threshold_{i}", "metric": f"kpi_{i}", "operator": ">", "value": float(i * 100)}
        for i in range(5)
    ]

    now = datetime.utcnow().isoformat()
    for i in range(20):
        fid = f"finding-{i:03d}"
        profile.known_findings[fid] = {
            "id": fid,
            "title": f"Finding {i}",
            "severity": "HIGH",
            "agent": "analyst",
            "first_seen": now,
            "last_seen": now,
            "runs_open": i + 1,
        }

    profile.baseline_history = {
        "Revenue Total": [
            {"period": f"Q{q}-2025", "label": "Revenue Total", "value": f"€{q * 100}K", "numeric_value": q * 100_000.0, "run_date": now}
            for q in range(1, 5)
        ],
        "Cobranza Pendiente": [
            {"period": f"Q{q}-2025", "label": "Cobranza Pendiente", "value": f"€{q * 40}K", "numeric_value": q * 40_000.0, "run_date": now}
            for q in range(1, 5)
        ],
    }

    start = time.perf_counter()
    context = build_adaptive_context(profile)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"build_adaptive_context took {elapsed:.3f}s, expected < 0.05s"
    assert isinstance(context, str)
    assert "perf-test-adaptive" in context


# ===========================================================================
# 10. generate_pdf_report — full results dict < 2 seconds
# ===========================================================================

def test_pdf_generate_under_2s():
    """generate_pdf_report for a full results dict completes in under 2 seconds."""
    # Evict any stub that api_endpoints tests may have injected so we import the real module
    sys.modules.pop("shared.pdf_generator", None)
    from shared.pdf_generator import generate_pdf_report

    executive_text = (
        "## Resumen Ejecutivo\n\n"
        "- **Revenue Total**: €4.2M (+8.2% vs Q4-2025) [CONFIRMED]\n"
        "- **Cobranza Pendiente**: €840K — 3 clientes concentran el 62%\n"
        "- **Alerta Crítica**: Facturas duplicadas detectadas por €120K\n\n"
        "## Hallazgos Críticos\n\n"
        "### Facturas duplicadas\n"
        "Se detectaron 14 pares de facturas con mismo importe y cliente "
        "en ventana de 48 horas. Impacto estimado: **€120.400** (2.9% del revenue).\n\n"
        "### AR Aging >90 días\n"
        "La cartera vencida a más de 90 días aumentó un **34%** respecto al período "
        "anterior. 3 clientes representan el 71% del saldo: Acme Corp (€230K), "
        "Beta S.A. (€185K), Gamma Ltda. (€105K).\n\n"
        "## Tendencias\n\n"
        "Revenue creció 8.2% impulsado principalmente por aumento de clientes activos "
        "(+12%), parcialmente compensado por reducción del ticket promedio (-3.5%).\n\n"
        "## Indicadores Monitoreados\n\n"
        "| KPI | Actual | Anterior | Var |\n"
        "|-----|--------|----------|-----|\n"
        "| Revenue | €4.2M | €3.9M | +8.2% |\n"
        "| Clientes activos | 312 | 278 | +12.2% |\n"
        "| Ticket promedio | €13.5K | €14.0K | -3.5% |\n"
        "| Cobranza >90d | €520K | €388K | +34.0% |\n"
    )

    results = {
        "job_id": "perf-test-job-001",
        "client_name": "Acme Corp S.A.",
        "period": "Q1-2026",
        "status": "completed",
        "execution_time_seconds": 312.7,
        "timestamp": datetime.utcnow().isoformat(),
        "findings": {
            "analyst": {
                "findings": [
                    {"severity": "CRITICAL", "description": "Facturas duplicadas €120K"},
                    {"severity": "HIGH", "description": "AR aging >90 días +34%"},
                    {"severity": "MEDIUM", "description": "Concentración de cobranza 62% en 3 clientes"},
                ]
            },
            "sentinel": {
                "findings": [
                    {"severity": "HIGH", "description": "Patrón de duplicados en 48h"},
                ]
            },
            "hunter": {
                "findings": [
                    {"severity": "LOW", "description": "Oportunidad: segmento Champions sin promoción activa"},
                ]
            },
        },
        "reports": {
            "executive": executive_text,
        },
    }

    start = time.perf_counter()
    pdf_bytes = generate_pdf_report(results)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"generate_pdf_report took {elapsed:.3f}s, expected < 2.0s"
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF", "Output does not start with PDF magic bytes"
    assert len(pdf_bytes) > 1_000, f"PDF too small ({len(pdf_bytes)} bytes), likely malformed"
