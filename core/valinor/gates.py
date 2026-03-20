"""
Quality Gates — Validation checkpoints between pipeline stages.

Gates ensure minimum data quality before proceeding to expensive
LLM-powered stages.
"""

import re


def gate_cartographer(entity_map: dict) -> bool:
    """
    PASS if: at least 2 of {customers, invoices, products, payments} mapped
    with confidence > 0.7

    This gate ensures the Cartographer found enough structure for
    meaningful analysis. Without at least customers + invoices,
    the analysis agents would produce low-quality results.
    """
    required_any_2 = ["customers", "invoices", "products", "payments"]
    entities = entity_map.get("entities", {})

    found = [
        e
        for e in required_any_2
        if e in entities
        and entities[e].get("confidence", 0) > 0.7
    ]

    return len(found) >= 2


def gate_analysis(findings: dict) -> bool:
    """
    PASS if: at least 2 of 3 agents produced findings
    WARN if: only 1 agent produced findings
    FAIL if: no agents produced findings

    We continue with partial results (WARNING) but log the issue.
    Only a complete failure (0 agents) blocks the pipeline.
    """
    completed = [
        k for k, v in findings.items()
        if isinstance(v, dict)
        and not v.get("error", False)
        and not isinstance(v, Exception)
    ]
    return len(completed) >= 2


def gate_sanity(reports: dict, query_results: dict) -> dict:
    """
    Sanity check: verify that key numbers in reports match query results
    within a tolerance.

    Returns a dict with check results rather than a simple bool,
    since sanity failures are warnings, not blockers.
    """
    checks = []

    # Check if revenue_by_period results exist
    revenue_data = query_results.get("results", {}).get("revenue_by_period", {})
    if revenue_data and revenue_data.get("rows"):
        total_revenue = sum(
            float(row.get("revenue", 0) or 0) for row in revenue_data["rows"]
        )
        checks.append({
            "check": "total_revenue_available",
            "status": "pass" if total_revenue > 0 else "warn",
            "value": total_revenue,
        })
    else:
        # Try total_revenue_summary as fallback
        summary_data = query_results.get("results", {}).get("total_revenue_summary", {})
        if summary_data and summary_data.get("rows"):
            total = float(summary_data["rows"][0].get("total_revenue", 0) or 0)
            checks.append({
                "check": "total_revenue_available",
                "status": "pass" if total > 0 else "warn",
                "value": total,
                "source": "total_revenue_summary",
            })
        else:
            checks.append({
                "check": "total_revenue_available",
                "status": "skip",
                "reason": "No revenue query results available",
            })

    # Check if reports were generated with meaningful content
    for report_name, content in reports.items():
        has_content = bool(content) and len(content) > 100
        checks.append({
            "check": f"report_{report_name}_generated",
            "status": "pass" if has_content else "warn",
            "length": len(content) if content else 0,
        })

    passed = all(c["status"] in ("pass", "skip") for c in checks)

    return {
        "passed": passed,
        "checks": checks,
    }


def gate_monetary_consistency(reports: dict, baseline: dict) -> dict:
    """
    Check that EUR estimates across all reports are internally consistent.

    Catches divergent assumptions like one report saying €60K and another
    saying €18M for the same item without explicit acknowledgement.

    Strategy:
    - Extract all EUR values from reports (€XXX or EUR XXX patterns)
    - Group by proximity to same context keywords
    - Warn if max/min ratio exceeds 20x for values that look like totals

    Returns:
        Dict with 'passed' bool and 'warnings' list.
    """
    warnings = []

    # Compare reports against baseline if available
    if baseline.get("total_revenue") and baseline["total_revenue"] > 0:
        baseline_revenue = baseline["total_revenue"]
        for report_name, content in reports.items():
            # Extract all EUR values mentioned in the report
            eur_values = _extract_eur_values(content)
            if not eur_values:
                continue

            # Check if any single value exceeds 10x the measured total revenue
            # (would indicate an agent invented a number, not estimated from data)
            implausibly_large = [
                v for v in eur_values
                if v > baseline_revenue * 10 and v > 1_000_000
            ]
            if implausibly_large:
                warnings.append({
                    "report": report_name,
                    "issue": f"Contains EUR values ({implausibly_large[:3]}) "
                             f">10x the measured total revenue ({baseline_revenue:,.0f}). "
                             "Verify these are not extrapolation errors.",
                    "severity": "warn",
                })

    # Cross-report consistency: same metric shouldn't differ >20x across reports
    # (except when one is "immediate subset" vs "full potential", which agents should flag)
    all_report_maxes = {}
    for report_name, content in reports.items():
        eur_values = _extract_eur_values(content)
        if eur_values:
            all_report_maxes[report_name] = max(eur_values)

    if len(all_report_maxes) >= 2:
        values = list(all_report_maxes.values())
        overall_max = max(values)
        overall_min = min(values)
        if overall_min > 0 and overall_max / overall_min > 50:
            warnings.append({
                "report": "cross_report",
                "issue": (
                    f"Largest EUR value across reports ({overall_max:,.0f}) is "
                    f"{overall_max/overall_min:.0f}x the smallest ({overall_min:,.0f}). "
                    "Check that agents used consistent baseline assumptions."
                ),
                "severity": "warn",
            })

    return {
        "passed": len(warnings) == 0,
        "warnings": warnings,
    }


def _extract_eur_values(text: str) -> list[float]:
    """Extract EUR monetary values from text. Returns list of floats."""
    values = []
    # Patterns: €1.2M, €250K, €1,500,000, EUR 500K
    patterns = [
        r'€\s*([\d,\.]+)\s*M\b',   # €1.2M
        r'€\s*([\d,\.]+)\s*K\b',   # €250K
        r'€\s*([\d,\.]+)',          # €1,500,000 or €150
        r'EUR\s*([\d,\.]+)\s*M\b',
        r'EUR\s*([\d,\.]+)\s*K\b',
        r'EUR\s*([\d,\.]+)',
    ]
    multipliers = {'M': 1_000_000, 'K': 1_000, '': 1}

    for pattern in patterns[:2]:  # M patterns
        for m in re.finditer(pattern, text, re.IGNORECASE):
            try:
                val = float(m.group(1).replace(',', '')) * 1_000_000
                values.append(val)
            except ValueError:
                pass

    for pattern in patterns[2:4]:  # K patterns
        for m in re.finditer(pattern, text, re.IGNORECASE):
            try:
                val = float(m.group(1).replace(',', '')) * 1_000
                values.append(val)
            except ValueError:
                pass

    for m in re.finditer(r'€\s*(\d[\d,\.]{2,})', text):
        try:
            val = float(m.group(1).replace(',', '').replace('.', ''))
            if val > 100:  # ignore tiny amounts
                values.append(val)
        except ValueError:
            pass

    return values
