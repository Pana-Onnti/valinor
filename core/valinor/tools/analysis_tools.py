"""
Analysis tools — Deterministic computation helpers.

These tools perform calculations that don't need LLM intelligence,
reducing token usage and improving accuracy for numerical operations.
"""

import json
from claude_agent_sdk import tool


@tool(
    "revenue_calc",
    "Calculate revenue aggregations from query results. Handles MoM, YoY, totals, averages.",
    {
        "data": str,
        "group_by": str,
        "amount_field": str,
    },
)
async def revenue_calc(args):
    """Revenue aggregation with period-over-period comparison."""
    try:
        data = json.loads(args["data"]) if isinstance(args["data"], str) else args["data"]
        amount_field = args["amount_field"]
        group_by = args.get("group_by", "period")

        if not data:
            return {
                "content": [{"type": "text", "text": json.dumps({"error": "No data provided"})}]
            }

        # Group and sum
        groups = {}
        for row in data:
            key = str(row.get(group_by, "unknown"))
            amount = float(row.get(amount_field, 0) or 0)
            if key not in groups:
                groups[key] = {"total": 0, "count": 0, "min": float("inf"), "max": float("-inf")}
            groups[key]["total"] += amount
            groups[key]["count"] += 1
            groups[key]["min"] = min(groups[key]["min"], amount)
            groups[key]["max"] = max(groups[key]["max"], amount)

        # Calculate averages and format
        result = {}
        grand_total = 0
        for key, vals in sorted(groups.items()):
            avg = vals["total"] / vals["count"] if vals["count"] > 0 else 0
            result[key] = {
                "total": round(vals["total"], 2),
                "count": vals["count"],
                "average": round(avg, 2),
                "min": round(vals["min"], 2) if vals["min"] != float("inf") else 0,
                "max": round(vals["max"], 2) if vals["max"] != float("-inf") else 0,
            }
            grand_total += vals["total"]

        # Period-over-period changes
        sorted_keys = sorted(result.keys())
        for i in range(1, len(sorted_keys)):
            prev_total = result[sorted_keys[i - 1]]["total"]
            curr_total = result[sorted_keys[i]]["total"]
            if prev_total > 0:
                change_pct = ((curr_total - prev_total) / prev_total) * 100
                result[sorted_keys[i]]["change_pct"] = round(change_pct, 1)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "grand_total": round(grand_total, 2),
                            "periods": len(result),
                            "breakdown": result,
                        },
                        indent=2,
                    ),
                }
            ]
        }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}]
        }


@tool(
    "aging_calc",
    "Calculate aging buckets for unpaid invoices/payments. Returns amounts per bucket with provision estimates.",
    {
        "data": str,
        "due_date_field": str,
        "amount_field": str,
        "reference_date": str,
    },
)
async def aging_calc(args):
    """Aging bucket calculation with provision rates."""
    from datetime import datetime, date

    try:
        data = json.loads(args["data"]) if isinstance(args["data"], str) else args["data"]
        due_date_field = args["due_date_field"]
        amount_field = args["amount_field"]
        ref_date_str = args.get("reference_date")

        ref_date = (
            datetime.strptime(ref_date_str, "%Y-%m-%d").date()
            if ref_date_str
            else date.today()
        )

        # Aging buckets with provision rates
        buckets = {
            "0-30d": {"min": 0, "max": 30, "provision_rate": 0.00, "total": 0, "count": 0},
            "31-60d": {"min": 31, "max": 60, "provision_rate": 0.05, "total": 0, "count": 0},
            "61-90d": {"min": 61, "max": 90, "provision_rate": 0.15, "total": 0, "count": 0},
            "91-180d": {"min": 91, "max": 180, "provision_rate": 0.30, "total": 0, "count": 0},
            "181-365d": {"min": 181, "max": 365, "provision_rate": 0.60, "total": 0, "count": 0},
            ">365d": {"min": 366, "max": 999999, "provision_rate": 0.90, "total": 0, "count": 0},
        }

        total_outstanding = 0
        total_provision = 0

        for row in data:
            due_str = str(row.get(due_date_field, ""))
            amount = float(row.get(amount_field, 0) or 0)

            if not due_str or due_str == "None":
                continue

            try:
                due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

            days_overdue = (ref_date - due_date).days
            if days_overdue < 0:
                days_overdue = 0

            for bucket_name, bucket in buckets.items():
                if bucket["min"] <= days_overdue <= bucket["max"]:
                    bucket["total"] += amount
                    bucket["count"] += 1
                    total_outstanding += amount
                    total_provision += amount * bucket["provision_rate"]
                    break

        # Format output
        result_buckets = {}
        for name, bucket in buckets.items():
            provision = bucket["total"] * bucket["provision_rate"]
            result_buckets[name] = {
                "total": round(bucket["total"], 2),
                "count": bucket["count"],
                "provision_rate": bucket["provision_rate"],
                "provision_amount": round(provision, 2),
            }

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "reference_date": str(ref_date),
                            "total_outstanding": round(total_outstanding, 2),
                            "total_provision_required": round(total_provision, 2),
                            "provision_pct": round(
                                (total_provision / total_outstanding * 100)
                                if total_outstanding > 0
                                else 0,
                                1,
                            ),
                            "buckets": result_buckets,
                        },
                        indent=2,
                    ),
                }
            ]
        }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}]
        }


@tool(
    "pareto_analysis",
    "Pareto/concentration analysis. Identifies top N contributors and their % of total.",
    {
        "data": str,
        "entity_field": str,
        "value_field": str,
        "top_n": int,
    },
)
async def pareto_analysis(args):
    """Pareto analysis for concentration measurement."""
    try:
        data = json.loads(args["data"]) if isinstance(args["data"], str) else args["data"]
        entity_field = args["entity_field"]
        value_field = args["value_field"]
        top_n = args.get("top_n", 10)

        # Aggregate by entity
        entities = {}
        for row in data:
            entity = str(row.get(entity_field, "unknown"))
            value = float(row.get(value_field, 0) or 0)
            entities[entity] = entities.get(entity, 0) + value

        # Sort descending
        sorted_entities = sorted(entities.items(), key=lambda x: x[1], reverse=True)
        grand_total = sum(v for _, v in sorted_entities)

        if grand_total == 0:
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"error": "Total is zero — cannot calculate concentration"})}
                ]
            }

        # Top N analysis
        cumulative = 0
        top_entities = []
        for i, (entity, value) in enumerate(sorted_entities[:top_n]):
            cumulative += value
            top_entities.append(
                {
                    "rank": i + 1,
                    "entity": entity,
                    "value": round(value, 2),
                    "pct_of_total": round(value / grand_total * 100, 1),
                    "cumulative_pct": round(cumulative / grand_total * 100, 1),
                }
            )

        # Concentration metrics
        top_1_pct = sorted_entities[0][1] / grand_total * 100 if sorted_entities else 0
        top_5_total = sum(v for _, v in sorted_entities[:5])
        top_10_total = sum(v for _, v in sorted_entities[:10])
        top_20_total = sum(v for _, v in sorted_entities[:20])

        # Herfindahl index (concentration measure)
        hhi = sum((v / grand_total * 100) ** 2 for _, v in sorted_entities)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "total_entities": len(entities),
                            "grand_total": round(grand_total, 2),
                            "concentration": {
                                "top_1_pct": round(top_1_pct, 1),
                                "top_5_pct": round(top_5_total / grand_total * 100, 1),
                                "top_10_pct": round(top_10_total / grand_total * 100, 1),
                                "top_20_pct": round(top_20_total / grand_total * 100, 1),
                                "herfindahl_index": round(hhi, 0),
                                "risk_level": (
                                    "HIGH"
                                    if top_1_pct > 25
                                    else "MODERATE"
                                    if top_5_total / grand_total > 0.5
                                    else "LOW"
                                ),
                            },
                            "top_entities": top_entities,
                        },
                        indent=2,
                    ),
                }
            ]
        }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": json.dumps({"error": str(e)})}]
        }
