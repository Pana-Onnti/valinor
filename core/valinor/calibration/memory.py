"""
Calibration Memory — Tracks accuracy across runs per client.

Stores calibration scores in JSON files, one per client.
Detects regressions and trends.

Storage format: calibration/<client>.json
{
  "client": "gloria",
  "scores": [
    {
      "period": "2024-12",
      "overall_score": 92.5,
      "query_coverage_pct": 0.93,
      "verification_rate": 0.85,
      "timestamp": "2026-03-21T22:00:00Z",
      "checks": [...]
    }
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import structlog

from valinor.calibration.evaluator import CalibrationScore

logger = structlog.get_logger()


class CalibrationMemory:
    """Persists calibration scores per client and provides trend analysis."""

    def __init__(self, storage_dir: str = "calibration"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _client_path(self, client: str) -> Path:
        """Return the JSON file path for a client."""
        safe_name = client.replace("/", "_").replace("\\", "_")
        return self.storage_dir / f"{safe_name}.json"

    def _load(self, client: str) -> dict:
        """Load the client's calibration file, or return empty structure."""
        path = self._client_path(client)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {"client": client, "scores": []}

    def _save(self, client: str, data: dict) -> None:
        """Save the client's calibration data."""
        path = self._client_path(client)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def record(self, client: str, period: str, score: CalibrationScore) -> None:
        """Append a calibration score to the client's history."""
        data = self._load(client)

        entry = {
            "period": period,
            "overall_score": score.overall_score,
            "query_coverage_pct": score.query_coverage_pct,
            "baseline_completeness_pct": score.baseline_completeness_pct,
            "verification_rate": score.verification_rate,
            "error_rate": score.error_rate,
            "timestamp": score.timestamp,
            "checks": [asdict(c) for c in score.checks],
            "recommendations": score.recommendations,
        }

        data["scores"].append(entry)
        self._save(client, data)

        logger.info(
            "calibration.memory.recorded",
            client=client,
            period=period,
            overall_score=score.overall_score,
        )

    def get_history(self, client: str) -> list[dict]:
        """Return all calibration scores for a client, newest first."""
        data = self._load(client)
        return list(reversed(data["scores"]))

    def detect_regression(self, client: str, score: CalibrationScore) -> dict | None:
        """Compare current score with last score. Return regression details if found.

        Regression = current score < previous score - 5 points.
        """
        history = self.get_history(client)
        if not history:
            return None

        last_score = history[0]["overall_score"]
        if score.overall_score < last_score - 5.0:
            regression = {
                "previous_score": last_score,
                "current_score": score.overall_score,
                "delta": round(score.overall_score - last_score, 2),
                "severity": "critical" if score.overall_score < last_score - 15.0 else "warning",
            }
            logger.warning(
                "calibration.memory.regression_detected",
                client=client,
                **regression,
            )
            return regression

        return None

    def get_trend(self, client: str, last_n: int = 5) -> dict:
        """Return trend analysis: improving, stable, degrading.

        Compare average of last N scores with previous N.
        """
        history = self.get_history(client)  # newest first
        if len(history) < 2:
            return {"trend": "insufficient_data", "data_points": len(history)}

        recent = [h["overall_score"] for h in history[:last_n]]
        previous = [h["overall_score"] for h in history[last_n : last_n * 2]]

        if not previous:
            # Not enough data for full comparison, use simple slope
            avg_recent = sum(recent) / len(recent)
            oldest = recent[-1]
            newest = recent[0]
            diff = newest - oldest

            if diff > 3.0:
                trend = "improving"
            elif diff < -3.0:
                trend = "degrading"
            else:
                trend = "stable"

            return {
                "trend": trend,
                "data_points": len(recent),
                "avg_recent": round(avg_recent, 2),
                "newest": newest,
                "oldest": oldest,
            }

        avg_recent = sum(recent) / len(recent)
        avg_previous = sum(previous) / len(previous)
        diff = avg_recent - avg_previous

        if diff > 3.0:
            trend = "improving"
        elif diff < -3.0:
            trend = "degrading"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "data_points": len(history),
            "avg_recent": round(avg_recent, 2),
            "avg_previous": round(avg_previous, 2),
            "delta": round(diff, 2),
        }

    def get_cross_client_summary(self) -> dict:
        """Return latest score for each client — bird's eye view."""
        summary = {}
        for path in self.storage_dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                client = data.get("client", path.stem)
                scores = data.get("scores", [])
                if scores:
                    latest = scores[-1]
                    summary[client] = {
                        "overall_score": latest["overall_score"],
                        "period": latest["period"],
                        "timestamp": latest["timestamp"],
                        "error_rate": latest.get("error_rate", 0),
                    }
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("calibration.memory.corrupt_file", path=str(path), error=str(e))
                continue

        return summary
