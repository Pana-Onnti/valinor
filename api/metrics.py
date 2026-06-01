"""
Prometheus metrics definitions and HTTP instrumentation middleware.

Usage — record events anywhere in the codebase:
    from api.metrics import JOBS_TOTAL, ACTIVE_JOBS, DQ_CHECKS_TOTAL
    JOBS_TOTAL.labels(status="completed").inc()
"""

import time

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CONTENT_TYPE_LATEST,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── Job lifecycle ──────────────────────────────────────────────────────────────

JOBS_TOTAL = Counter(
    "valinor_jobs_total",
    "Analysis jobs by final status",
    ["status"],  # completed | failed | cancelled
)

ACTIVE_JOBS = Gauge(
    "valinor_active_jobs",
    "Jobs currently in running state",
)

# ── Business metrics ───────────────────────────────────────────────────────────

ANALYSIS_COST_USD = Counter(
    "valinor_analysis_cost_usd_total",
    "Estimated cumulative analysis cost in USD",
)

CLIENTS_TOTAL = Gauge(
    "valinor_clients_total",
    "Registered client profiles",
)

# ── Data quality ───────────────────────────────────────────────────────────────

DQ_CHECKS_TOTAL = Counter(
    "valinor_dq_checks_total",
    "Data quality gate checks executed",
    ["check_name", "result"],  # result: passed | failed | warning
)

# Wire the DQ gate's metrics port to this counter (dependency inversion — the
# Domain gate exposes set_dq_metrics_hook so it never imports api.metrics).
try:
    from core.valinor.quality.data_quality_gate import set_dq_metrics_hook

    set_dq_metrics_hook(
        lambda check_name, passed: DQ_CHECKS_TOTAL.labels(
            check_name=check_name,
            result="passed" if passed else "failed",
        ).inc()
    )
except Exception:  # pragma: no cover - metrics wiring must never break startup
    pass

# ── HTTP ───────────────────────────────────────────────────────────────────────

HTTP_REQUESTS_TOTAL = Counter(
    "valinor_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION = Histogram(
    "valinor_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# ── Middleware ─────────────────────────────────────────────────────────────────

_SKIP_PATHS = {"/metrics", "/health", "/docs", "/redoc", "/openapi.json"}


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Record HTTP request duration and count for every non-infra endpoint."""

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        # Use the matched route TEMPLATE (e.g. "/api/jobs/{job_id}/status") instead of
        # the realized URL so UUID/name path params don't explode metric cardinality —
        # one timeseries per job_id would blow up the registry (VAL-169). Falls back to
        # the raw path only when no route matched (e.g. 404s), preserving prior behavior.
        route = request.scope.get("route")
        path_label = getattr(route, "path", None) or request.url.path

        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            path=path_label,
            status_code=str(response.status_code),
        ).inc()
        HTTP_REQUEST_DURATION.labels(
            method=request.method,
            path=path_label,
        ).observe(duration)

        return response


def metrics_response() -> Response:
    """Return a Prometheus text exposition response."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
