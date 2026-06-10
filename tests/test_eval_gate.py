"""
Regression gate for the narrator-grounding instrument (VAL-192 N1).

`pytest` must fail when a code change degrades the instrument's test-split
accuracy on the golden set below the committed baseline. This is the "eval as
regression gate, not report" rule of the epic: the gate runs on the TEST split
only — tune against train, never against test.

Pure offline: golden cases are synthetic, no LLM, no DB, <1s.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_golden_gate_passes():
    """eval.py golden --gate must exit 0 against the committed baseline."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "eval.py"), "golden", "--gate"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, (
        f"instrument regression — eval gate failed:\n{proc.stdout}\n{proc.stderr}"
    )


def test_baseline_is_committed_and_sane():
    baseline = json.loads(
        (ROOT / "evals" / "narrator_grounding" / "baseline.json").read_text()
    )
    assert baseline["gate_metric"] == "case_accuracy/test/default"
    assert 0.9 <= baseline["value"] <= 1.0
