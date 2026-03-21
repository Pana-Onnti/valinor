"""
CurrencyGuard — detects mixed-currency aggregation before it corrupts findings.
Silent currency mixing is one of the most common sources of ERP reporting errors.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import structlog

logger = structlog.get_logger()


@dataclass
class CurrencyCheckResult:
    is_homogeneous: bool
    dominant_currency: str
    dominant_pct: float
    mixed_exposure_pct: float  # fraction of total value in non-dominant currency
    recommendation: str
    safe_to_aggregate: bool


class CurrencyGuard:
    """
    Checks query results for currency mixing before amounts are summed.

    The rule: NEVER sum amount_currency across different currencies.
    Always use debit/credit (company currency) for cross-currency aggregation.
    """

    def check_result_set(self, rows: List[Dict], amount_col: str = None,
                         currency_col: str = None) -> CurrencyCheckResult:
        """
        Check if a result set has mixed currencies.
        Auto-detects currency column if not specified.
        """
        if not rows:
            return CurrencyCheckResult(
                is_homogeneous=True, dominant_currency="unknown",
                dominant_pct=1.0, mixed_exposure_pct=0.0,
                recommendation="Empty result set",
                safe_to_aggregate=True
            )

        # Auto-detect currency column
        if currency_col is None:
            sample = rows[0] if isinstance(rows[0], dict) else {}
            for col in sample.keys():
                if any(hint in col.lower() for hint in ['currency', 'moneda', 'curr']):
                    currency_col = col
                    break

        if currency_col is None or currency_col not in (rows[0] if isinstance(rows[0], dict) else {}):
            # No currency column found — assume homogeneous
            return CurrencyCheckResult(
                is_homogeneous=True, dominant_currency="unknown",
                dominant_pct=1.0, mixed_exposure_pct=0.0,
                recommendation="No currency column detected",
                safe_to_aggregate=True
            )

        # Auto-detect amount column
        if amount_col is None:
            sample = rows[0] if isinstance(rows[0], dict) else {}
            for col in sample.keys():
                if any(hint in col.lower() for hint in ['amount', 'total', 'importe', 'monto']):
                    amount_col = col
                    break

        # Count by currency
        currency_amounts: Dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            curr = str(row.get(currency_col, 'unknown'))
            amount = 0.0
            if amount_col and amount_col in row:
                try:
                    amount = float(row[amount_col] or 0)
                except (ValueError, TypeError):
                    amount = 0.0
            currency_amounts[curr] = currency_amounts.get(curr, 0) + abs(amount)

        if not currency_amounts:
            return CurrencyCheckResult(
                is_homogeneous=True, dominant_currency="unknown",
                dominant_pct=1.0, mixed_exposure_pct=0.0,
                recommendation="Could not parse currency data",
                safe_to_aggregate=True
            )

        total = sum(currency_amounts.values())
        dominant = max(currency_amounts, key=currency_amounts.get)
        dominant_amount = currency_amounts[dominant]
        dominant_pct = dominant_amount / total if total > 0 else 1.0
        mixed_pct = 1.0 - dominant_pct

        is_homogeneous = mixed_pct < 0.001  # < 0.1% mixed is acceptable

        if not is_homogeneous:
            logger.warning(
                "CurrencyGuard: mixed currencies detected",
                dominant=dominant,
                dominant_pct=f"{dominant_pct:.1%}",
                mixed_pct=f"{mixed_pct:.1%}",
                currencies=list(currency_amounts.keys()),
            )

        return CurrencyCheckResult(
            is_homogeneous=is_homogeneous,
            dominant_currency=dominant,
            dominant_pct=dominant_pct,
            mixed_exposure_pct=mixed_pct,
            recommendation=(
                f"Use debit/credit columns (company currency) for aggregation. "
                f"{mixed_pct:.1%} of value is in non-{dominant} currencies: "
                f"{[c for c in currency_amounts if c != dominant]}"
            ) if not is_homogeneous else f"All values in {dominant}",
            safe_to_aggregate=is_homogeneous,
        )

    def scan_query_results(self, query_results: Dict[str, Any]) -> Dict[str, CurrencyCheckResult]:
        """Scan all query results for currency mixing."""
        findings = {}
        for query_id, result in query_results.get("results", {}).items():
            rows = result.get("rows", [])
            if not rows:
                continue
            check = self.check_result_set(rows)
            if not check.is_homogeneous:
                findings[query_id] = check
                logger.warning(
                    "Mixed currencies in query result",
                    query_id=query_id,
                    mixed_pct=f"{check.mixed_exposure_pct:.2%}"
                )
        return findings

    def build_currency_context_block(self, check: CurrencyCheckResult) -> str:
        """
        Generate a context string suitable for injection into agent prompts.

        Informs downstream agents (Analyst, Sentinel, Hunter, Narrators) whether
        they are operating on a homogeneous dataset or a mixed-currency one, and
        gives explicit instructions to prevent silent cross-currency aggregation.

        Best-practice rationale
        -----------------------
        Hedge funds and banks apply two canonical approaches when comparing
        amounts across periods that span different currencies:

        1. **Constant-currency reporting** (used by multinationals such as
           Microsoft, Unilever, and SAP in their quarterly earnings):
           Re-state prior-period figures using the *current-period exchange rate*
           so that revenue/cost deltas reflect volume/price changes only, not FX
           moves.  The formula is:
               CC_growth = (current_value / prior_value_restated_at_current_FX) - 1

        2. **Functional-currency aggregation** (IFRS 21 / ASC 830):
           Each entity records transactions in its functional currency; only the
           company-currency (debit/credit) columns are used for consolidated
           totals.  The original transaction currency is preserved for audit but
           never summed directly with other currencies.

        In the context of Valinor, agents must never add EUR amounts to USD
        amounts from the raw `amount_currency` field.  They should either:
          a) Use the `debit`/`credit` (company currency) columns for aggregated
             KPIs, or
          b) Analyse each currency bucket in isolation and note FX impact
             explicitly in the narrative.

        The RevenueFactorModel should receive homogeneous inputs; if mixing is
        detected the factor decomposition must be deferred until FX normalisation
        has been applied upstream.

        Parameters
        ----------
        check : CurrencyCheckResult
            Result from a prior `check_result_set()` or `scan_query_results()`
            call.

        Returns
        -------
        str
            A formatted, human-readable context block ready to prepend to any
            agent system prompt or user message.
        """
        if check.is_homogeneous:
            currency_label = check.dominant_currency.upper()
            return (
                f"[CONTEXTO MONEDA]\n"
                f"Moneda única detectada: {currency_label}. "
                f"Comparaciones directas válidas. "
                f"El modelo de factores (RevenueFactorModel) puede agregarse sin conversión FX."
            )

        # Mixed-currency path
        dominant = check.dominant_currency.upper()
        dominant_pct = check.dominant_pct * 100
        mixed_pct = check.mixed_exposure_pct * 100

        return (
            f"[CONTEXTO MONEDA — ADVERTENCIA]\n"
            f"AVISO: Los datos contienen múltiples monedas. "
            f"NO sumes EUR + USD. Analiza cada moneda por separado.\n"
            f"Moneda dominante: {dominant} ({dominant_pct:.1f}% del valor total). "
            f"Exposición en moneda no dominante: {mixed_pct:.1f}%.\n"
            f"Instrucciones para agentes:\n"
            f"  1. Usar columnas debit/credit (moneda de empresa) para KPIs agregados.\n"
            f"  2. Descomponer resultados por moneda antes de comparar períodos.\n"
            f"  3. Para comparación período-a-período (ej. Q1 2024 EUR vs Q1 2023 EUR "
            f"con transacciones en USD): aplicar metodología 'constant currency' — "
            f"re-expresar el período anterior al tipo de cambio actual y marcar el "
            f"impacto FX como factor separado.\n"
            f"  4. El RevenueFactorModel NO debe ejecutarse sobre datos mixtos sin "
            f"normalización FX previa."
        )


# Module singleton
_guard: Optional[CurrencyGuard] = None

def get_currency_guard() -> CurrencyGuard:
    global _guard
    if _guard is None:
        _guard = CurrencyGuard()
    return _guard
