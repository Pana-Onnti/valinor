# Valinor SaaS — API Reference

**Base URL**: `http://localhost:8000`
**Version**: 2.0.0
**Interactive docs**: `/docs` (Swagger UI) · `/redoc` (ReDoc)

Rate limiting: most write endpoints are capped at **10 requests/minute** per IP.
All responses are JSON unless noted otherwise.

---

## Table of Contents

- [System](#system)
- [Analysis](#analysis)
- [Jobs / Streaming](#jobs--streaming)
- [Clients](#clients)
- [Alerts](#alerts)
- [Webhooks](#webhooks)
- [Onboarding](#onboarding)
- [Quality](#quality)
- [Common Error Codes](#common-error-codes)

---

## System

### `GET /health`

Liveness and readiness check. Returns the aggregate health of Redis and the metadata storage layer.

**Response**
```json
{
  "status": "healthy",
  "timestamp": "2026-03-21T10:00:00Z",
  "components": {
    "redis": "healthy",
    "storage": "healthy"
  },
  "version": "2.0.0",
  "uptime_seconds": 3600.0,
  "environment": "development"
}
```

---

### `GET /api/version`

API version metadata and capability summary.

**Response**
```json
{
  "version": "2.0.0",
  "api_prefix": "/api/v1",
  "supported_db_types": ["postgres", "mysql", "sqlserver", "oracle"],
  "max_analysis_duration_minutes": 15,
  "cost_per_analysis_usd": 8.0
}
```

---

### `GET /api/system/status`

Comprehensive system status: service health, installed packages, and enabled feature flags.

**Response**
```json
{
  "version": "2.0.0",
  "timestamp": "2026-03-21T10:00:00Z",
  "services": { "api": "healthy", "redis": "healthy", "database": "healthy" },
  "features": {
    "data_quality_gate": true,
    "pdf_reports": true,
    "sse_streaming": true,
    "client_memory": true,
    "segmentation": true,
    "auto_refinement": true
  },
  "packages": { "statsmodels": { "installed": true, "version": "0.14.0" } },
  "quality_checks": ["schema_integrity", "null_density", "..."],
  "llm_provider": "anthropic_api"
}
```

---

### `GET /metrics`

Prometheus-compatible text-format scrape endpoint. Returns job counters by status, total cost estimate, and total client count.

**Content-Type**: `text/plain`

**Sample output**
```
# HELP valinor_jobs_total Total jobs by status
# TYPE valinor_jobs_total counter
valinor_jobs_total{status="completed"} 42
valinor_jobs_total{status="failed"} 3
valinor_analysis_cost_usd_total 336.0
valinor_clients_total 7
```

---

### `GET /api/system/metrics`

Operational metrics in JSON — job counts by status, success rate, client count, total cost estimate, and all-time average DQ score.

**Response**
```json
{
  "jobs": { "completed": 42, "failed": 3, "running": 1, "pending": 0, "cancelled": 0, "total": 46 },
  "success_rate_pct": 93.3,
  "clients_with_profile": 7,
  "estimated_total_cost_usd": 336.0,
  "avg_dq_score_all_time": 87.4,
  "timestamp": "2026-03-21T10:00:00Z"
}
```

---

### `GET /api/cache/stats`

Observability metrics for the in-memory completed-job results cache (LRU, TTL = 5 minutes).

**Response**
```json
{
  "cached_jobs": 3,
  "oldest_entry_age_seconds": 128.5
}
```

---

### `POST /api/audit`

Log an audit event. Events are stored in Redis as a capped list (max 1 000 entries). Used internally and by external services.

**Body** — any JSON object. A `timestamp` field is added automatically.

**Response**
```json
{ "logged": true }
```

---

### `GET /api/audit`

Read recent audit events from Redis.

**Query params**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 50 | Number of events to return (max 1 000) |
| `event_type` | string | — | Filter by event type (e.g. `analysis_started`) |

**Response**
```json
{
  "events": [
    { "event_type": "analysis_started", "job_id": "abc123", "client_name": "acme", "timestamp": "2026-03-21T10:00:00Z" }
  ],
  "total_returned": 1
}
```

---

## Analysis

### `POST /api/analyze`

Start a new analysis job. Returns immediately with a `job_id`. Use `/api/jobs/{id}/stream` or `/api/jobs/{id}/status` to track progress.

**Rate limit**: 10/minute · **Monthly limit per client**: 25 analyses · **Concurrent jobs per client**: 2

**Request body**

```json
{
  "client_name": "acme_corp",
  "period": "Q1-2026",
  "db_config": {
    "host": "db.client.com",
    "port": 5432,
    "type": "postgresql",
    "name": "erp_prod",
    "user": "readonly",
    "password": "secret"
  },
  "ssh_config": {
    "host": "bastion.client.com",
    "username": "ubuntu",
    "private_key_path": "/keys/id_rsa",
    "port": 22
  },
  "sector": "retail",
  "country": "US",
  "currency": "USD",
  "language": "en",
  "erp": "odoo",
  "fiscal_context": "generic",
  "overrides": {}
}
```

`ssh_config` is optional. `period` accepts formats: `Q1-2026`, `H1-2026`, `2026`.

**Response**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Analysis queued successfully"
}
```

**Error codes**

| Code | Meaning |
|---|---|
| 422 | Validation error (invalid period, bad port, etc.) |
| 429 | Monthly limit or concurrent-job limit reached |

---

### `GET /api/jobs`

List all analysis jobs with pagination, filtering and sorting.

**Query params**

| Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | 1 | 1-based page number |
| `page_size` | int | 20 | Items per page (max 100) |
| `status_filter` | string | — | Filter: `completed\|failed\|pending\|running\|cancelled` |
| `client_name` | string | — | Filter to a specific client |
| `sort_by` | string | `created_at` | `created_at\|status\|client_name` |
| `sort_order` | string | `desc` | `asc\|desc` |

**Response**
```json
{
  "jobs": [
    {
      "job_id": "550e8400...",
      "status": "completed",
      "client_name": "acme_corp",
      "period": "Q1-2026",
      "created_at": "2026-03-21T09:00:00Z",
      "completed_at": "2026-03-21T09:14:30Z",
      "stage": "delivery",
      "progress": 100
    }
  ],
  "total": 46,
  "page": 1,
  "page_size": 20,
  "pages": 3
}
```

---

### `GET /api/jobs/{id}/status`

Get the current status of a job.

**Path param**: `id` — UUID returned by `POST /api/analyze`

**Response**
```json
{
  "job_id": "550e8400...",
  "status": "running",
  "stage": "data_quality",
  "progress": 35,
  "message": "Running DQ Gate — check 3/9",
  "started_at": "2026-03-21T09:00:00Z",
  "completed_at": null,
  "error": null,
  "error_detail": null
}
```

`status` values: `pending`, `running`, `completed`, `failed`, `cancelled`

---

### `GET /api/jobs/{id}/results`

Retrieve full results for a completed job. Results are cached in memory for 5 minutes after first read.

**Returns 400** if the job has not yet completed.

**Response**
```json
{
  "job_id": "550e8400...",
  "client_name": "acme_corp",
  "period": "Q1-2026",
  "status": "completed",
  "started_at": "...",
  "completed_at": "...",
  "execution_time_seconds": 847.2,
  "stages": { "cartographer": {}, "data_quality": {}, "analysis": {}, "delivery": {} },
  "findings": { "analyst": { "findings": [] }, "sentinel": {}, "hunter": {} },
  "reports": { "executive": "...", "ceo": "...", "controller": "...", "sales": "..." },
  "data_quality": { "score": 91.5, "confidence_label": "CONFIRMED", "tag": "DQ_CONFIRMED" },
  "_dq_summary": { "score": 91.5, "label": "CONFIRMED", "tag": "DQ_CONFIRMED" },
  "download_urls": {
    "executive_report": "/api/jobs/550e8400.../download/executive_report.pdf"
  }
}
```

---

### `POST /api/jobs/{id}/cancel`

Cancel a running or pending job. No-op if the job has already reached a terminal state.

**Response**
```json
{ "status": "cancelled", "job_id": "550e8400..." }
```

---

### `POST /api/jobs/{id}/retry`

Re-queue a failed or cancelled job using the original request parameters. Sensitive credentials are not retained between attempts; supply them fresh if required.

**Returns 400** if the job is not in `failed` or `cancelled` state, or if the original request data is unavailable.

**Response**
```json
{
  "job_id": "new-uuid",
  "status": "pending",
  "retry_of": "original-uuid"
}
```

---

### `DELETE /api/jobs/cleanup`

Delete completed, failed, and cancelled jobs older than N days from Redis.

**Query param**: `older_than_days` (int, default `7`)

**Response**
```json
{ "deleted": 12, "cutoff": "2026-03-14T10:00:00Z" }
```

---

## Jobs / Streaming

### `GET /api/jobs/{id}/stream`

Server-Sent Events stream for real-time job progress. The connection closes automatically when the job reaches a terminal state or after 30 minutes.

**Content-Type**: `text/event-stream`

**Event shape**
```
data: {"job_id": "...", "status": "running", "stage": "analyst", "progress": 60, "message": "...", "timestamp": "..."}

data: {"job_id": "...", "status": "completed", "stage": "done", "progress": 100, "final": true}
```

When the job reaches `data_quality` stage or completes, the event also includes `dq_score` and `dq_label` fields.

---

### `WS /api/jobs/{id}/ws`

WebSocket endpoint for real-time job progress. Messages are sent only when `status` changes (not on every poll).

**Message shape**
```json
{ "status": "running", "progress": 60, "stage": "analyst" }
```

On completion:
```json
{ "status": "completed", "progress": 100, "stage": "delivery", "dq_score": 91.5 }
```

Followed by:
```json
{ "final": true, "status": "completed" }
```

---

### `GET /api/jobs/{id}/quality`

Retrieve the Data Quality Gate report embedded in a completed job's results.

**Response**
```json
{
  "job_id": "550e8400...",
  "data_quality": {
    "score": 91.5,
    "confidence_label": "CONFIRMED",
    "tag": "DQ_CONFIRMED",
    "checks": { "schema_integrity": "PASS", "accounting_balance": "PASS", "benford_compliance": "WARN" }
  },
  "currency_warnings": {},
  "snapshot_timestamp": "2026-03-21T09:02:30Z"
}
```

---

### `GET /api/jobs/{id}/export/pdf`

Generate and download a branded PDF report for a completed job.

**Rate limit**: 10/minute
**Content-Type**: `application/pdf`
**Content-Disposition**: `attachment; filename="valinor_acme_corp_Q1-2026.pdf"`

---

### `GET /api/jobs/{id}/pdf`

Alternative PDF download endpoint (legacy). Generates the same branded report via the `BrandedPDFGenerator`. Returns 404 if no executive report text is available in the results.

**Rate limit**: 30/minute

---

### `GET /api/jobs/{id}/digest`

Preview the HTML email digest for a completed job. Returns a rendered HTML page suitable for email clients.

**Content-Type**: `text/html`

---

### `POST /api/jobs/{id}/send-digest`

Send the email digest to a specified address via SMTP.

**Query param**: `to_email` (string, required)

**Response**
```json
{ "status": "sent", "to": "cfo@acme.com" }
```

`status` is `smtp_not_configured` when `SMTP_*` environment variables are absent.

---

## Clients

Client endpoints read from persistent `ClientProfile` objects stored in PostgreSQL (with local JSON file fallback).

---

### `GET /api/clients`

List all clients that have a stored profile.

**Response**
```json
{
  "clients": [
    { "client_name": "acme_corp", "run_count": 8, "last_run_date": "2026-03-20", "known_findings_count": 4 }
  ]
}
```

---

### `GET /api/clients/summary`

Aggregated KPI summary across all clients for the operator dashboard.

**Response**
```json
{
  "total_clients": 7,
  "total_critical_findings": 3,
  "avg_dq_score": 87.4,
  "total_runs": 58,
  "clients_with_criticals": 2
}
```

---

### `GET /api/clients/comparison`

Compare DQ scores and trends across multiple clients side by side.

**Query param**: `clients` — comma-separated client names (optional; omit for all clients)

**Response**
```json
{
  "clients": [
    {
      "name": "acme_corp",
      "run_count": 8,
      "avg_dq_score": 91.5,
      "dq_trend": "improving",
      "critical_findings": 1,
      "last_run": "2026-03-20T15:00:00Z",
      "industry": "retail"
    }
  ],
  "generated_at": "2026-03-21T10:00:00Z"
}
```

`dq_trend` values: `improving`, `degrading`, `stable`

---

### `GET /api/clients/{name}/profile`

Get the full persistent `ClientProfile` for a client. Returns 404 if no profile exists.

**Response** — full profile dict including `known_findings`, `baseline_history`, `dq_history`, `run_history`, `refinement`, `webhooks`, `alert_thresholds`, etc.

---

### `GET /api/clients/{name}/profile/export`

Download the full `ClientProfile` as a JSON file attachment.

**Content-Disposition**: `attachment; filename="{name}_profile.json"`

---

### `POST /api/clients/{name}/profile/import`

Overwrite (import) a `ClientProfile` from a JSON body. The `client_name` field in the body must match the URL `{name}` parameter.

**Response**
```json
{ "status": "imported", "client": "acme_corp" }
```

---

### `DELETE /api/clients/{name}/profile`

Reset a client profile to blank. Useful after significant schema changes. The profile entry is preserved but all findings, history, and refinement settings are cleared.

---

### `GET /api/clients/{name}/refinement`

Return the current auto-refinement settings for a client (analysis depth, focus tables, excluded tables, language preferences).

**Response**
```json
{
  "client_name": "acme_corp",
  "refinement": {
    "depth": "full",
    "focus_tables": ["account_move", "res_partner"],
    "suppress_ids": []
  }
}
```

---

### `PATCH /api/clients/{name}/refinement`

Merge a partial refinement dict into the stored settings. Existing keys not present in the body are preserved.

**Body** — partial refinement object (any keys)

**Response** — updated `refinement` dict

---

### `GET /api/clients/{name}/findings`

List all active findings for a client, sorted by severity (CRITICAL first).

**Query param**: `severity_filter` — `CRITICAL|HIGH|MEDIUM|LOW|UNKNOWN` (optional, case-insensitive)

**Response**
```json
{
  "client": "acme_corp",
  "findings": [
    {
      "id": "fin_001",
      "title": "Negative gross margin on SKU-99",
      "severity": "CRITICAL",
      "agent": "sentinel",
      "first_seen": "2026-01-15",
      "last_seen": "2026-03-20",
      "runs_open": 3
    }
  ],
  "total": 4,
  "critical": 1,
  "high": 2,
  "resolved_count": 7,
  "severity_filter": null
}
```

---

### `GET /api/clients/{name}/findings/{finding_id}`

Get a single finding by ID. Returns 404 if the finding does not exist.

**Response**
```json
{
  "client": "acme_corp",
  "finding": { "id": "fin_001", "title": "...", "severity": "CRITICAL", "..." }
}
```

---

### `GET /api/clients/{name}/kpis`

Get KPI baseline history for a client — a dict of KPI label to list of datapoints.

**Response**
```json
{
  "client_name": "acme_corp",
  "kpis": {
    "Gross Revenue": [
      { "period": "Q3-2025", "value": 1200000 },
      { "period": "Q4-2025", "value": 1350000 }
    ]
  },
  "kpi_count": 12,
  "earliest_period": "Q1-2025",
  "latest_period": "Q1-2026"
}
```

---

### `GET /api/clients/{name}/analytics`

Deeper run analytics derived from `run_history`: success rate, findings per run, monthly run distribution, finding velocity trend, last 5 runs.

**Response**
```json
{
  "client_name": "acme_corp",
  "total_runs": 8,
  "success_rate": 100.0,
  "avg_findings_per_run": 3.5,
  "avg_new_findings_per_run": 0.8,
  "avg_resolved_per_run": 0.5,
  "runs_by_month": { "2026-01": 2, "2026-02": 3, "2026-03": 3 },
  "finding_velocity": "stable",
  "last_5_runs": [
    { "run_date": "2026-03-20", "findings_count": 4, "new": 1, "resolved": 0, "success": true }
  ]
}
```

---

### `GET /api/clients/{name}/costs`

Cost summary derived from `run_history`. Each run defaults to $8 unless `estimated_cost_usd` is set.

**Response**
```json
{
  "client_name": "acme_corp",
  "total_runs": 8,
  "estimated_total_cost_usd": 64.0,
  "avg_cost_per_run_usd": 8.0,
  "runs_this_month": 3,
  "cost_this_month_usd": 24.0
}
```

---

### `GET /api/clients/{name}/dq-history`

Historical DQ scores for a client with trend direction.

**Response**
```json
{
  "client": "acme_corp",
  "dq_history": [
    { "score": 85.0, "timestamp": "2026-01-15T10:00:00Z", "period": "Q4-2025" }
  ],
  "avg_score": 87.4,
  "trend": "improving",
  "runs_with_dq": 8
}
```

`trend` values: `improving`, `declining`, `stable`

---

### `GET /api/clients/{name}/segmentation`

Latest customer segmentation computed by the SegmentationEngine (RFM-based).

**Response**
```json
{
  "client": "acme_corp",
  "computed_at": "2026-03-20T15:00:00Z",
  "total_customers": 1250,
  "total_revenue": 4800000,
  "segments": {
    "champions": { "count": 120, "revenue_share": 0.42 },
    "at_risk": { "count": 85, "revenue_share": 0.08 }
  },
  "history_count": 3
}
```

---

### `GET /api/clients/{name}/stats`

Summary statistics for a client — findings overview, trend direction, KPI count, focus tables.

**Response**
```json
{
  "client_name": "acme_corp",
  "run_count": 8,
  "last_run_date": "2026-03-20",
  "industry": "retail",
  "currency": "USD",
  "active_findings": 4,
  "resolved_findings": 7,
  "critical_active": 1,
  "avg_runs_open": 2.3,
  "findings_trend": "decreasing",
  "kpi_count": 12,
  "focus_tables": ["account_move", "res_partner"],
  "refinement_ready": true,
  "entity_cache_fresh": true
}
```

---

## Alerts

### `GET /api/clients/{name}/alerts/thresholds`

Return the client's configured alert thresholds keyed by metric name.

**Response**
```json
{
  "thresholds": [
    {
      "metric": "Gross Revenue",
      "condition": "pct_change_below",
      "value": -10.0,
      "severity": "HIGH",
      "description": "Revenue drop alert",
      "triggered": false,
      "created_at": "2026-01-10T08:00:00Z"
    }
  ],
  "count": 1
}
```

---

### `POST /api/clients/{name}/alerts/thresholds`

Create or update (upsert) an alert threshold.

**Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `metric` | string | yes | KPI key from `baseline_history` |
| `condition` | string | yes | `pct_change_below\|pct_change_above\|absolute_below\|absolute_above\|z_score_above` |
| `threshold_value` | float | yes | Numeric trigger value |
| `severity` | string | yes | `CRITICAL\|HIGH\|MEDIUM` |
| `description` | string | no | Human-readable label |

**Response**
```json
{ "status": "ok", "threshold": { "..." }, "upserted": true }
```

---

### `DELETE /api/clients/{name}/alerts/thresholds/{metric}`

Remove the alert threshold identified by its metric key. Returns 404 if no matching threshold exists.

**Response**
```json
{ "deleted": true, "metric": "Gross Revenue" }
```

---

### `GET /api/clients/{name}/alerts/triggered`

Return the list of triggered alerts stored from the most recent analysis run.

**Response**
```json
{
  "triggered": [
    { "metric": "Gross Revenue", "condition": "pct_change_below", "value": -15.3, "severity": "HIGH" }
  ]
}
```

---

## Webhooks

Webhooks are fired automatically after each successful analysis. Up to 5 webhook URLs can be registered per client.

### `POST /api/clients/{name}/webhooks`

Register a webhook URL for a client.

**Body**
```json
{ "url": "https://hooks.slack.com/services/..." }
```

**Response**
```json
{ "status": "registered", "url": "https://...", "client": "acme_corp" }
```

---

### `GET /api/clients/{name}/webhooks`

List all registered webhooks for a client.

**Response**
```json
{
  "client": "acme_corp",
  "webhooks": [
    { "url": "https://...", "registered_at": "2026-03-01T08:00:00Z", "active": true }
  ]
}
```

---

### `DELETE /api/clients/{name}/webhooks`

Remove a webhook by URL.

**Query param**: `url` — the exact URL to remove

**Response**
```json
{ "status": "removed", "remaining": 2 }
```

---

## Onboarding

Onboarding endpoints are designed to be called before the first analysis. They are ephemeral — no client data is stored.

### `POST /api/onboarding/test-connection`

Test database connectivity and auto-detect ERP type. Supports direct connections (PostgreSQL, MySQL). For SSH-tunneled connections use `/api/onboarding/ssh-test`.

**Body**

| Field | Type | Default | Description |
|---|---|---|---|
| `db_type` | string | `postgresql` | `postgresql\|mysql` |
| `host` | string | — | Database host |
| `port` | int | 5432 | Database port |
| `database` | string | — | Database name |
| `user` | string | — | DB username |
| `password` | string | — | DB password |

**Response**
```json
{
  "success": true,
  "latency_ms": 12.4,
  "erp_detected": "odoo",
  "erp_version": "16.0",
  "table_count": 312,
  "has_accounting": true,
  "has_invoices": true,
  "has_partners": true,
  "recommended_analysis": "full"
}
```

`recommended_analysis` values: `full`, `accounting_only`, `limited`

---

### `POST /api/onboarding/ssh-test`

Test SSH tunnel + DB connectivity without running any analysis. Opens a tunnel, pings the DB, then immediately disconnects.

**Body**

| Field | Type | Default | Description |
|---|---|---|---|
| `ssh_host` | string | — | SSH bastion host |
| `ssh_port` | int | 22 | SSH port |
| `ssh_user` | string | — | SSH username |
| `ssh_key` | string | — | Base64-encoded PEM private key |
| `db_host` | string | — | Database host (via tunnel) |
| `db_port` | int | 5432 | Database port |
| `db_type` | string | `postgresql` | Database type |
| `db_name` | string | — | Database name |
| `db_user` | string | — | DB username |
| `db_password` | string | — | DB password |

**Response**
```json
{ "ssh_ok": true, "db_ok": true, "latency_ms": 48.7, "error": null }
```

---

### `GET /api/onboarding/supported-databases`

List of supported database types with connection string templates and default ports.

**Response**
```json
[
  {
    "id": "postgresql",
    "label": "PostgreSQL",
    "default_port": 5432,
    "connection_template": "postgresql://{user}:{password}@{host}:{port}/{database}",
    "notes": "Fully supported. Odoo, iDempiere, and custom schemas auto-detected."
  },
  { "id": "mysql", "label": "MySQL / MariaDB", "default_port": 3306, "..." },
  { "id": "sqlserver", "label": "SQL Server", "default_port": 1433, "..." },
  { "id": "oracle", "label": "Oracle Database", "default_port": 1521, "..." }
]
```

---

### `POST /api/onboarding/estimate-cost`

Estimate analysis cost, duration, and token usage based on database size.

**Body**
```json
{ "estimated_rows": 500000, "tables_count": 80, "period": "Q1-2026" }
```

**Response**
```json
{
  "estimated_cost_usd": 7.5,
  "estimated_duration_minutes": 8,
  "token_estimate": 190000
}
```

Cost formula: `base $3 + $0.50 per 100k rows + $0.20 per table` (clamped $5–$15).

---

### `POST /api/onboarding/validate-period`

Validate that a period string has the expected format.

**Body**
```json
{ "period": "Q1-2026" }
```

**Response**
```json
{ "valid": true, "period": "Q1-2026", "message": "Período válido" }
```

Accepted formats: `Q1-2026`, `H1-2026`, `2026`

---

## Quality

### `GET /api/quality/schema/{client_name}`

Real-time schema integrity check capability description. Full schema checks are executed automatically during analysis via `/api/analyze`.

**Response**
```json
{
  "client": "acme_corp",
  "message": "Schema check requires active connection — trigger via /api/analyze",
  "available_checks": ["schema_integrity", "null_density", "duplicate_rate", "..."]
}
```

---

### `GET /api/quality/methodology`

Documentation of the data quality methodology: all checks, scoring thresholds, and industry references.

**Response**
```json
{
  "methodology": "Institutional-grade data verification",
  "inspired_by": ["Renaissance Technologies", "Bloomberg Terminal", "ECB Statistical Standards", "Big 4 Audit"],
  "checks": {
    "accounting_balance": "Assets = Liabilities + Equity — FATAL if >1% discrepancy",
    "benford_compliance": "First-digit distribution chi-squared test (IRS/SEC methodology)",
    "repeatable_read": "PostgreSQL REPEATABLE READ transaction isolation for consistent snapshots"
  },
  "score_interpretation": {
    "90-100": "CONFIRMED — Full confidence",
    "75-89": "PROVISIONAL — Proceed with caveats",
    "50-74": "UNVERIFIED — Significant issues",
    "0-49": "BLOCKED — Analysis halted"
  }
}
```

---

## Common Error Codes

| HTTP | `error` field | Description |
|---|---|---|
| 400 | `bad_request` | Invalid parameter or job state conflict |
| 404 | `not_found` | Resource not found |
| 422 | `validation_error` | Request body failed schema validation |
| 429 | `monthly_limit_reached` | Client exceeded 25 analyses/month |
| 429 | `too_many_concurrent_jobs` | Client has 2 jobs already running |
| 503 | — | Redis or storage unavailable |

All error responses include a `request_id` field (also present in the `X-Request-ID` response header) to aid log correlation.

```json
{
  "error": "validation_error",
  "message": "Request validation failed",
  "details": [{ "field": "db_config.port", "message": "value is not a valid integer", "type": "type_error" }],
  "request_id": "a1b2c3d4"
}
```

---

*Valinor SaaS v2 — Delta 4C — March 2026*
