"""
VAL-192 N3 v5 — 3 samples protocol test.

Verifies that eval.py graphrag:
  - Accepts a list of N answers per (qid, arm) in community.json
  - Scores each sample independently with judge_layer0
  - Reports the MEDIAN score as the final score for the (qid, arm)
  - Emits one CSV row per sample with a `sample` column (0-based)
  - Stays fully backwards-compatible with string answers in flat.json

Synthetic data only: no client data, no LLM, no DB.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _build_fixtures(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build minimal synthetic eval fixtures. Returns (dir, questions, references)."""
    # The numeric fact we test with — chosen so it doesn't accidentally appear elsewhere
    REF_VALUE = 42.0

    # Questions YAML: 1 question, 1 numeric required_fact via placeholder
    questions = {
        "version": 1,
        "questions": [
            {
                "id": "qt1-sampling-test",
                "split": "train",
                "question": "What is the answer to the ultimate question?",
                "seed_entities": ["answer", "question"],
                "required_facts": [
                    {
                        "fact": "the answer",
                        "expected": "{REF:qt1.the_answer}",
                        "tolerance_pct": 1.0,
                    }
                ],
                "must_not_include": [],
            }
        ],
    }
    questions_path = tmp_path / "global_questions.yaml"
    questions_path.write_text(yaml.dump(questions), encoding="utf-8")

    # References JSON
    references = {"qt1": {"the_answer": REF_VALUE}}
    references_path = tmp_path / "references.json"
    references_path.write_text(json.dumps(references), encoding="utf-8")

    # Answer dir
    out_dir = tmp_path / "answers"
    out_dir.mkdir()

    # flat.json — single string (compat mode, sample=0)
    # Contains the correct number so flat score = 1.00
    flat_answers = {"qt1-sampling-test": f"The answer is {REF_VALUE:.1f} exactly."}
    (out_dir / "flat.json").write_text(json.dumps(flat_answers), encoding="utf-8")

    # community.json — list of 3 samples
    # sample 0: correct number → score 1.0
    # sample 1: correct number → score 1.0
    # sample 2: wrong number (9999) → score 0.0
    # median([1.0, 1.0, 0.0]) = 1.0
    community_answers = {
        "qt1-sampling-test": [
            f"The answer is {REF_VALUE:.1f}.",       # correct
            f"The number is {REF_VALUE:.1f} confirmed.",  # correct
            "The answer is 9999.",                   # wrong
        ]
    }
    (out_dir / "community.json").write_text(json.dumps(community_answers), encoding="utf-8")

    return out_dir, questions_path, references_path


def test_sampling_median_and_csv_rows(tmp_path):
    """
    community arm has 3 samples: 2 correct (score=1.0), 1 wrong (score=0.0).
    Median = 1.0 → table shows community=1.00.
    CSV must have 3 rows for community (sample 0,1,2) and 1 row for flat (sample 0).
    """
    out_dir, questions_path, references_path = _build_fixtures(tmp_path)
    csv_path = tmp_path / "results.csv"

    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "eval.py"),
            "graphrag",
            "--dir", str(out_dir),
            "--references", str(references_path),
            "--questions", str(questions_path),
            "--csv", str(csv_path),
            # no --split so all questions are active
            # no --judge: layer 0 only (deterministic, no LLM)
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, (
        f"eval.py graphrag failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )

    # ── Table check: community median must be 1.00 ──────────────────────────
    # The printed table line for qt1-sampling-test should show community=1.00
    found_community_100 = any(
        "qt1-sampling-test" in line and "1.00" in line
        for line in proc.stdout.splitlines()
    )
    assert found_community_100, (
        f"Expected community=1.00 in table for qt1-sampling-test.\n"
        f"stdout:\n{proc.stdout}"
    )

    # ── CSV check: 3 rows for community (samples 0,1,2), 1 row for flat ─────
    assert csv_path.exists(), "CSV file was not created"
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert "sample" in rows[0], f"CSV must have 'sample' column, got: {list(rows[0].keys())}"

    community_rows = [r for r in rows if r["arm"] == "community" and r["question"] == "qt1-sampling-test"]
    flat_rows = [r for r in rows if r["arm"] == "flat" and r["question"] == "qt1-sampling-test"]

    assert len(community_rows) == 3, (
        f"Expected 3 community rows (one per sample), got {len(community_rows)}"
    )
    assert len(flat_rows) == 1, (
        f"Expected 1 flat row (string compat), got {len(flat_rows)}"
    )

    # sample indices must be 0, 1, 2 for community
    sample_indices = sorted(int(r["sample"]) for r in community_rows)
    assert sample_indices == [0, 1, 2], (
        f"Expected sample indices [0,1,2] for community, got {sample_indices}"
    )

    # flat row must be sample=0
    assert flat_rows[0]["sample"] == "0", (
        f"Expected flat sample=0, got {flat_rows[0]['sample']}"
    )

    # Individual community sample scores: 2 correct (1.0) and 1 wrong (0.0)
    community_scores = sorted(float(r["score"]) for r in community_rows)
    assert community_scores == [0.0, 1.0, 1.0], (
        f"Expected community sample scores [0.0, 1.0, 1.0], got {community_scores}"
    )
