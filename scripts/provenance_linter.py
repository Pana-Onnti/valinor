#!/usr/bin/env python3
"""
Provenance linter (VAL-192 N4) — CI guardrail for the memory write-path.

Asserts that every staged/merged refinement proposal carries provenance
(run_id, client_tag, generated_at, confidence). A learning without provenance
cannot enter the memory governed by N4 — that's the whole point of the
write-path: no anonymous knowledge compounds with authority.

Run over stored profile JSONs, or import `lint_profile` / `lint_profiles` from a
pytest gate (see tests/test_n4_writepath.py). Exit 1 on any violation.

Refs: VAL-192 (N4)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.memory.client_profile import has_provenance  # noqa: E402


_REVIEW_QUEUES = ("pending_refinements", "pending_escalations")


def lint_profile(profile_dict: Dict) -> List[str]:
    """Return a list of violation strings for one profile dict (empty = clean)."""
    violations: List[str] = []
    client = profile_dict.get("client_name", "?")
    for queue in _REVIEW_QUEUES:
        for rec in profile_dict.get(queue, []) or []:
            if not has_provenance(rec):
                pid = rec.get("proposal_id", "?") if isinstance(rec, dict) else "?"
                violations.append(
                    f"{client}: {queue} {pid} missing provenance "
                    f"(need run_id, client_tag, generated_at, confidence)"
                )
    return violations


def lint_profiles(profile_dicts: List[Dict]) -> List[str]:
    out: List[str] = []
    for p in profile_dicts:
        out.extend(lint_profile(p))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="VAL-192 N4 provenance linter")
    ap.add_argument("paths", nargs="*",
                    help="profile JSON files (default: /tmp/valinor_profiles/*.json)")
    args = ap.parse_args(argv)
    paths = [Path(p) for p in args.paths] or sorted(Path("/tmp/valinor_profiles").glob("*.json"))

    violations: List[str] = []
    for p in paths:
        try:
            violations.extend(lint_profile(json.loads(p.read_text(encoding="utf-8"))))
        except Exception as exc:  # noqa: BLE001
            print(f"skip {p}: {exc}", file=sys.stderr)

    if violations:
        print("PROVENANCE LINT FAILED:", file=sys.stderr)
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print(f"provenance lint OK ({len(paths)} profile(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
