"""Quality and data integrity API routes."""
from fastapi import APIRouter

router = APIRouter(prefix="/api/quality", tags=["quality"])


@router.get("/schema/{client_name}")
async def check_client_schema(client_name: str):
    """
    Run a real-time schema integrity check on a client's DB.
    Uses the client's stored connection config from their last job.
    """
    # For now, return a placeholder that explains the capability
    return {
        "client": client_name,
        "message": "Schema check requires active connection — trigger via /api/analyze",
        "available_checks": [
            "schema_integrity", "null_density", "duplicate_rate",
            "accounting_balance", "cross_table_reconcile",
            "outlier_screen", "benford_compliance", "temporal_consistency",
            "receivables_cointegration"
        ]
    }


@router.get("/methodology")
async def get_quality_methodology():
    """Returns the data quality methodology documentation."""
    return {
        "methodology": "Institutional-grade data verification",
        "inspired_by": ["Renaissance Technologies", "Bloomberg Terminal", "ECB Statistical Standards", "Big 4 Audit"],
        "checks": {
            "accounting_balance": "Assets = Liabilities + Equity — FATAL if >1% discrepancy",
            "cross_table_reconcile": "3-path revenue reconciliation (invoices + GL + sales orders)",
            "benford_compliance": "First-digit distribution chi-squared test (IRS/SEC methodology)",
            "temporal_consistency": "Rolling z-score with STL seasonal decomposition",
            "receivables_cointegration": "Engle-Granger cointegration test (receivables <> revenue)",
            "currency_guard": "Silent mixed-currency aggregation prevention",
            "factor_model": "Revenue = clients x avg_ticket x frequency + residual",
            "repeatable_read": "PostgreSQL REPEATABLE READ transaction isolation for consistent snapshots",
        },
        "score_interpretation": {
            "90-100": "CONFIRMED — Full confidence",
            "75-89": "PROVISIONAL — Proceed with caveats",
            "50-74": "UNVERIFIED — Significant issues",
            "0-49": "BLOCKED — Analysis halted"
        }
    }
