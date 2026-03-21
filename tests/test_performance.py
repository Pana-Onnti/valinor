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


# ===========================================================================
# 11. benford_test — 100,000 values scales linearly (< 5 seconds)
# ===========================================================================

def test_benford_check_100k_values_under_5s():
    """benford_test on 100,000 values completes in under 5 seconds."""
    from valinor.quality.statistical_checks import benford_test

    rng = random.Random(99)
    values = [math.exp(rng.uniform(0, math.log(1_000_000))) for _ in range(100_000)]

    start = time.perf_counter()
    result = benford_test(values)
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0, f"benford_test x100k took {elapsed:.3f}s, expected < 5.0s"
    assert result["n_samples"] == 100_000


# ===========================================================================
# 12. cusum_structural_break — 10,000 points < 500 ms
# ===========================================================================

def test_cusum_10k_points_under_500ms():
    """cusum_structural_break on a 10,000-point series completes in under 500 ms."""
    from valinor.quality.statistical_checks import cusum_structural_break

    rng = random.Random(17)
    # Inject a regime shift half-way through
    series = (
        [rng.gauss(100.0, 5.0) for _ in range(5_000)]
        + [rng.gauss(130.0, 5.0) for _ in range(5_000)]
    )

    start = time.perf_counter()
    result = cusum_structural_break(series)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"cusum x10k took {elapsed:.3f}s, expected < 0.5s"
    assert "break_detected" in result
    assert "cusum_last" in result


# ===========================================================================
# 13. seasonal_adjusted_zscore — 1,000 calls < 2 seconds
# ===========================================================================

def test_seasonal_adjusted_zscore_1000_calls_under_2s():
    """seasonal_adjusted_zscore called 1,000 times completes in under 2 seconds."""
    from valinor.quality.statistical_checks import seasonal_adjusted_zscore

    rng = random.Random(31)
    # Build a fixed 24-point history (2 years of monthly data)
    base_series = [rng.gauss(500_000.0, 50_000.0) for _ in range(24)]

    start = time.perf_counter()
    for _ in range(1_000):
        current_val = rng.gauss(500_000.0, 50_000.0)
        result = seasonal_adjusted_zscore(base_series, current_val, period=12)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"seasonal_adjusted_zscore x1000 took {elapsed:.3f}s, expected < 2.0s"
    assert "z_score" in result
    assert "is_anomalous" in result


# ===========================================================================
# 14. cointegration_test — 100 calls < 2 seconds
# ===========================================================================

def test_cointegration_test_100_calls_under_2s():
    """cointegration_test called 100 times with 50-point series each < 2 seconds."""
    from valinor.quality.statistical_checks import cointegration_test

    rng = random.Random(53)
    n_points = 50

    start = time.perf_counter()
    for _ in range(100):
        s1 = [rng.gauss(1_000_000.0, 100_000.0) for _ in range(n_points)]
        # s2 is correlated with s1 but with added noise
        s2 = [v * rng.uniform(0.9, 1.1) for v in s1]
        result = cointegration_test(s1, s2)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"cointegration_test x100 took {elapsed:.3f}s, expected < 2.0s"
    assert "correlation" in result
    assert "method" in result


# ===========================================================================
# 15. format_currency compact mode — 5,000 calls < 200 ms
# ===========================================================================

def test_format_currency_compact_5000_calls_under_200ms():
    """format_currency in compact mode called 5,000 times completes in under 200 ms."""
    from shared.utils.formatting import format_currency

    rng = random.Random(77)
    currencies = ["EUR", "USD", "GBP", "BRL"]
    values = [rng.uniform(10_000, 50_000_000) for _ in range(5_000)]

    start = time.perf_counter()
    for i, v in enumerate(values):
        format_currency(v, currency=currencies[i % len(currencies)], compact=True)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.2, f"format_currency compact x5000 took {elapsed:.3f}s, expected < 0.2s"


# ===========================================================================
# 16. format_percentage — 10,000 calls < 100 ms
# ===========================================================================

def test_format_percentage_10000_calls_under_100ms():
    """format_percentage called 10,000 times completes in under 100 ms."""
    from shared.utils.formatting import format_percentage

    rng = random.Random(61)
    values = [rng.uniform(-50.0, 200.0) for _ in range(10_000)]

    start = time.perf_counter()
    for v in values:
        format_percentage(v, decimals=1)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.1, f"format_percentage x10k took {elapsed:.3f}s, expected < 0.1s"


# ===========================================================================
# 17. format_delta — 10,000 calls < 100 ms
# ===========================================================================

def test_format_delta_10000_calls_under_100ms():
    """format_delta called 10,000 times (mixed percentage/plain) completes in under 100 ms."""
    from shared.utils.formatting import format_delta

    rng = random.Random(83)
    deltas = [rng.uniform(-30.0, 30.0) for _ in range(10_000)]

    start = time.perf_counter()
    for i, d in enumerate(deltas):
        format_delta(d, as_percentage=(i % 2 == 0))
    elapsed = time.perf_counter() - start

    assert elapsed < 0.1, f"format_delta x10k took {elapsed:.3f}s, expected < 0.1s"


# ===========================================================================
# 18. truncate_text — 50,000 calls < 500 ms
# ===========================================================================

def test_truncate_text_50000_calls_under_500ms():
    """truncate_text called 50,000 times with mixed lengths completes in under 500 ms."""
    from shared.utils.formatting import truncate_text

    rng = random.Random(19)
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "
    texts = [
        "".join(rng.choices(alphabet, k=rng.randint(20, 300)))
        for _ in range(1_000)
    ]
    calls = [texts[i % len(texts)] for i in range(50_000)]

    start = time.perf_counter()
    for text in calls:
        truncate_text(text, max_len=100)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"truncate_text x50k took {elapsed:.3f}s, expected < 0.5s"


# ===========================================================================
# 19. format_duration — 10,000 calls < 50 ms
# ===========================================================================

def test_format_duration_10000_calls_under_50ms():
    """format_duration called 10,000 times across the full range completes in under 50 ms."""
    from shared.utils.date_utils import format_duration

    rng = random.Random(41)
    durations = [rng.uniform(0, 7 * 3600) for _ in range(10_000)]

    start = time.perf_counter()
    for d in durations:
        format_duration(d)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"format_duration x10k took {elapsed:.3f}s, expected < 0.05s"


# ===========================================================================
# 20. parse_period — 10,000 calls (cycling all formats) < 500 ms
# ===========================================================================

def test_parse_period_10000_calls_under_500ms():
    """parse_period called 10,000 times across all supported formats completes in under 500 ms."""
    from shared.utils.date_utils import parse_period

    periods = (
        [f"Q{q}-{y}" for q in range(1, 5) for y in range(2000, 2026)]
        + [f"H{h}-{y}" for h in (1, 2) for y in range(2000, 2026)]
        + [str(y) for y in range(1990, 2030)]
    )
    calls = [periods[i % len(periods)] for i in range(10_000)]

    start = time.perf_counter()
    for p in calls:
        parse_period(p)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"parse_period x10k took {elapsed:.3f}s, expected < 0.5s"


# ===========================================================================
# 21. AnomalyDetector.format_for_agent — 500 anomalies < 50 ms
# ===========================================================================

def test_anomaly_detector_format_for_agent_500_items_under_50ms():
    """AnomalyDetector.format_for_agent with 500 anomaly objects completes in under 50 ms."""
    from valinor.quality.anomaly_detector import AnomalyDetector, StatisticalAnomaly

    rng = random.Random(11)
    detector = AnomalyDetector()

    severities = ["HIGH", "MEDIUM", "LOW"]
    anomalies = [
        StatisticalAnomaly(
            query_id=f"q{i}",
            column="amount",
            method="iqr_3x_log",
            severity=severities[i % len(severities)],
            description=f"Anomaly {i} detected",
            outlier_values=[rng.uniform(1e6, 1e9) for _ in range(3)],
            outlier_count=rng.randint(1, 20),
            value_share=rng.uniform(0.01, 0.40),
        )
        for i in range(500)
    ]

    start = time.perf_counter()
    text = detector.format_for_agent(anomalies)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"format_for_agent x500 took {elapsed:.3f}s, expected < 0.05s"
    assert isinstance(text, str)
    assert len(text) > 0


# ===========================================================================
# 22. CurrencyGuard.check_result_set — 5,000 rows < 200 ms
# ===========================================================================

def test_currency_guard_check_5000_rows_under_200ms():
    """CurrencyGuard.check_result_set on 5,000 rows completes in under 200 ms."""
    from valinor.quality.currency_guard import CurrencyGuard

    rng = random.Random(23)
    currencies = ["EUR"] * 95 + ["USD"] * 4 + ["GBP"] * 1  # 95% homogeneous
    rows = [
        {
            "currency_id": currencies[i % len(currencies)],
            "amount": rng.uniform(100.0, 50_000.0),
        }
        for i in range(5_000)
    ]

    guard = CurrencyGuard()

    start = time.perf_counter()
    result = guard.check_result_set(rows, currency_col="currency_id", amount_col="amount")
    elapsed = time.perf_counter() - start

    assert elapsed < 0.2, f"CurrencyGuard.check_result_set took {elapsed:.3f}s, expected < 0.2s"
    assert result.dominant_currency == "EUR"
    assert 0.94 < result.dominant_pct <= 1.0


# ===========================================================================
# 23. CurrencyGuard.build_currency_context_block — 1,000 calls < 50 ms
# ===========================================================================

def test_currency_guard_context_block_1000_calls_under_50ms():
    """CurrencyGuard.build_currency_context_block called 1,000 times completes in under 50 ms."""
    from valinor.quality.currency_guard import CurrencyGuard, CurrencyCheckResult

    guard = CurrencyGuard()

    homogeneous_result = CurrencyCheckResult(
        is_homogeneous=True,
        dominant_currency="EUR",
        dominant_pct=1.0,
        mixed_exposure_pct=0.0,
        recommendation="All values in EUR",
        safe_to_aggregate=True,
    )
    mixed_result = CurrencyCheckResult(
        is_homogeneous=False,
        dominant_currency="USD",
        dominant_pct=0.75,
        mixed_exposure_pct=0.25,
        recommendation="Mixed: EUR 25%",
        safe_to_aggregate=False,
    )

    start = time.perf_counter()
    for i in range(1_000):
        guard.build_currency_context_block(homogeneous_result if i % 2 == 0 else mixed_result)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"build_currency_context_block x1000 took {elapsed:.3f}s, expected < 0.05s"


# ===========================================================================
# 24. SegmentationEngine.segment_from_query_results — 500 customers < 500 ms
# ===========================================================================

def test_segmentation_engine_500_customers_under_500ms():
    """SegmentationEngine.segment_from_query_results with 500 customers completes in under 500 ms."""
    from shared.memory.segmentation_engine import SegmentationEngine
    from shared.memory.client_profile import ClientProfile

    rng = random.Random(37)
    engine = SegmentationEngine()
    profile = ClientProfile.new("perf-test-seg")
    profile.industry_inferred = "distribución mayorista"
    profile.currency_detected = "EUR"

    rows = [
        {
            "customer_name": f"Cliente {i:04d}",
            "grandtotal": rng.lognormvariate(10, 1.5),
        }
        for i in range(500)
    ]
    query_results = {
        "results": {
            "customer_concentration": {
                "columns": ["customer_name", "grandtotal"],
                "rows": rows,
            }
        }
    }

    start = time.perf_counter()
    result = engine.segment_from_query_results(query_results, profile)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.5, f"segment_from_query_results x500 took {elapsed:.3f}s, expected < 0.5s"
    assert result is not None
    assert result.total_customers == 500
    assert len(result.segments) == 3


# ===========================================================================
# 25. SegmentationEngine.build_context_block — 100 calls < 50 ms
# ===========================================================================

def test_segmentation_engine_build_context_block_100_calls_under_50ms():
    """SegmentationEngine.build_context_block called 100 times completes in under 50 ms."""
    from shared.memory.segmentation_engine import SegmentationEngine, SegmentationResult, CustomerSegment

    engine = SegmentationEngine()
    segments = [
        CustomerSegment(
            name="Champions", count=100, total_revenue=2_000_000.0,
            revenue_share=0.70, avg_revenue=20_000.0,
            top_customers=["Acme Corp", "Beta SA", "Gamma Ltda"],
            currency="EUR", description="Clientes con mayor volumen",
        ),
        CustomerSegment(
            name="Growth", count=300, total_revenue=700_000.0,
            revenue_share=0.25, avg_revenue=2_333.0,
            top_customers=["Delta Inc", "Epsilon SL"],
            currency="EUR", description="Potencial de crecimiento",
        ),
        CustomerSegment(
            name="Maintenance", count=100, total_revenue=150_000.0,
            revenue_share=0.05, avg_revenue=1_500.0,
            top_customers=["Zeta SA"],
            currency="EUR", description="Clientes en riesgo",
        ),
    ]
    seg_result = SegmentationResult(
        method="pareto_percentile",
        segments=segments,
        total_customers=500,
        total_revenue=2_850_000.0,
        computed_at=datetime.utcnow().isoformat(),
        industry="distribución mayorista",
        thresholds={"Champions": 15_000.0, "Growth": 2_000.0},
    )

    start = time.perf_counter()
    for _ in range(100):
        text = engine.build_context_block(seg_result, currency="EUR")
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"build_context_block x100 took {elapsed:.3f}s, expected < 0.05s"
    assert "Champions" in text
    assert "EUR" in text


# ===========================================================================
# 26. AlertEngine.check_thresholds — 50 thresholds × 20 history points < 200 ms
# ===========================================================================

def test_alert_engine_50_thresholds_under_200ms():
    """AlertEngine.check_thresholds with 50 thresholds and 20 history points each completes in under 200 ms."""
    from shared.memory.alert_engine import AlertEngine
    from shared.memory.client_profile import ClientProfile

    rng = random.Random(47)
    engine = AlertEngine()
    profile = ClientProfile.new("perf-test-alert")

    conditions = ["absolute_above", "absolute_below", "pct_change_above", "pct_change_below", "z_score_above"]
    profile.alert_thresholds = [
        {
            "label": f"threshold_{i}",
            "metric": f"kpi_{i % 10}",
            "condition": conditions[i % len(conditions)],
            "value": float(rng.randint(50, 500)),
            "severity": "HIGH",
            "message": f"Alert {i} fired",
        }
        for i in range(50)
    ]

    now = datetime.utcnow().isoformat()
    baseline_history = {
        f"kpi_{k}": [
            {
                "period": f"Q{q}-2025",
                "label": f"KPI {k}",
                "value": f"€{rng.randint(100, 1000)}K",
                "numeric_value": float(rng.randint(100, 1000)),
                "run_date": now,
            }
            for q in range(1, 21)
        ]
        for k in range(10)
    }

    findings = {}

    start = time.perf_counter()
    triggered = engine.check_thresholds(profile, baseline_history, findings)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.2, f"AlertEngine.check_thresholds took {elapsed:.3f}s, expected < 0.2s"
    assert isinstance(triggered, list)
