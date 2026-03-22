"""
Valinor SaaS API — FastAPI application entry point.

This module creates the FastAPI app, configures middleware, exception handlers,
and mounts all routers. Route implementations live in api/routers/*.

Router modules:
  - routers/jobs.py      Analysis job lifecycle (analyze, status, results, stream)
  - routers/clients.py   Client profiles, findings, costs, analytics
  - routers/alerts.py    Alert threshold CRUD and triggered alerts
  - routers/reports.py   PDF export, email digest, quality reports
  - routers/system.py    Health, version, audit, metrics, system status
  - routers/nl_query.py  Natural language query (VAL-32)
  - routes/quality.py    Data quality endpoints
  - routes/onboarding.py Onboarding endpoints
"""

import os
import sys
import uuid as _uuid
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import structlog
import redis.asyncio as redis
import sentry_sdk

# Add shared modules to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.storage import MetadataStorage
from api.routes.quality import router as quality_router
from api.routes.onboarding import router as onboarding_router
from api.routers.nl_query import router as nl_query_router
from api.routers.jobs import router as jobs_router
from api.routers.clients import router as clients_router
from api.routers.alerts import router as alerts_router
from api.routers.reports import router as reports_router
from api.routers.system import router as system_router
from api.logging_config import setup_logging
from api.metrics import PrometheusMiddleware, metrics_response
from api.deps import set_redis_client, set_limiter

# Re-export models for backward compatibility (tests import from api.main)
from api.models import (  # noqa: F401
    SSHConfig,
    DatabaseConfig,
    AnalysisRequest,
    JobStatus,
    AnalysisResults,
)

# Re-export helpers and state for backward compatibility (tests import from api.main)
from api.routers.jobs import (  # noqa: F401
    _validate_client_name,
    _validate_period,
    _results_cache,
    _RESULTS_CACHE_TTL,
)

setup_logging()
logger = structlog.get_logger()


# ═══ SENTRY ═══

def _sentry_before_send(event, hint):
    """Strip sensitive headers before sending events to Sentry."""
    request_ctx = event.get("request", {})
    headers = request_ctx.get("headers", {})
    for key in list(headers.keys()):
        if key.lower() in ("authorization", "x-api-key", "cookie"):
            headers[key] = "[FILTERED]"
    return event


def _init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        logger.info("Sentry disabled — SENTRY_DSN not set")
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("APP_ENV", "development"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        before_send=_sentry_before_send,
    )
    logger.info("Sentry initialized", environment=os.getenv("APP_ENV", "development"))


_init_sentry()


# ═══ GLOBAL STATE ═══

redis_client = None
metadata_storage = MetadataStorage()
_app_start_time: float = time.time()


# ═══ LIFESPAN ═══

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: initialize and cleanup application components."""
    global redis_client
    logger.info("Starting Valinor SaaS API...")
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connection established", redis_url=redis_url)
        set_redis_client(redis_client)
        await metadata_storage.health_check()
        logger.info("Metadata storage initialized")
    except Exception as e:
        logger.error("Startup failed", error=str(e))
        raise
    yield
    logger.info("Shutting down Valinor SaaS API...")
    if redis_client:
        await redis_client.close()
    redis_client = None
    set_redis_client(None)


# ═══ APP CREATION ═══

app = FastAPI(
    title="Valinor SaaS API",
    description="""
## Valinor — AI-Powered Business Intelligence

Analiza cualquier base de datos empresarial y genera reportes ejecutivos en 15 minutos.

### Arquitectura
- **Zero Data Storage** — solo metadata y resultados agregados
- **Multi-agent pipeline**: Cartographer -> DataQualityGate -> QueryBuilder -> Analysts -> Narrators
- **Calidad institucional**: 9 controles de datos antes de cada analisis

### Flujo tipico
1. `POST /api/analyze` — inicia analisis (devuelve job_id)
2. `GET /api/jobs/{id}/stream` — SSE para progreso en tiempo real
3. `GET /api/jobs/{id}/results` — resultados completos
4. `GET /api/jobs/{id}/pdf` — reporte PDF con marca Valinor
5. `GET /api/jobs/{id}/quality` — reporte de calidad de datos

### Metodologia de calidad de datos
Implementa estandares de: Renaissance Technologies, Bloomberg Terminal, ECB, Big 4 Audit
- Ecuacion contable (Activos = Pasivos + Capital)
- Reconciliacion 3 rutas de revenue
- Ley de Benford
- Descomposicion STL estacional
- Cointegracion Engle-Granger
    """,
    version="2.0.0",
    contact={"name": "Delta 4C", "email": "hola@delta4c.com"},
    license_info={"name": "Proprietary"},
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ═══ RATE LIMITER ═══

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
set_limiter(limiter)


# ═══ MIDDLEWARE ═══

# CORS
_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8080",
    "https://valinor-saas.vercel.app",
    *([o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]),
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# Request ID tracing
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = request.headers.get("X-Request-ID", str(_uuid.uuid4())[:8])
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIDMiddleware)
app.add_middleware(PrometheusMiddleware)


# ═══ EXCEPTION HANDLERS ═══

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    request_id = getattr(request.state, "request_id", None)
    body = {"error": "not_found", "path": request.url.path}
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=404, content=body)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        "Unhandled exception",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    body = {"error": "internal_error", "message": "An unexpected error occurred"}
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=500, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)
    errors = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err.get("loc", []))
        errors.append({"field": field, "message": err.get("msg"), "type": err.get("type")})
    body = {
        "error": "validation_error",
        "message": "Request validation failed",
        "details": errors,
    }
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=422, content=body)


# ═══ REGISTER ROUTERS ═══

app.include_router(system_router)
app.include_router(jobs_router)
app.include_router(clients_router)
app.include_router(alerts_router)
app.include_router(reports_router)
app.include_router(quality_router)
app.include_router(onboarding_router)
app.include_router(nl_query_router)


# ═══ MAIN ═══

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
