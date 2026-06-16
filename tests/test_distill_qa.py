"""
N6 distillation QA dataset gate (VAL-192).

`pytest` must catch: a low-quality / inconsistent QA artifact, a missing
provenance tag, a hint-pack changed without regenerating (staleness), or the
anti-pattern of distilling CLIENT NUMBERS (distillation is cache, not grounding).
Pure CPU, offline. Mirrors tests/test_eval_gate.py.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "evals" / "distill" / "qa_pairs.jsonl"
MANIFEST = ROOT / "evals" / "distill" / "manifest.json"
FREQUENT = ROOT / "evals" / "distill" / "frequent_subset.json"
HINTS = ROOT / "core" / "valinor" / "discovery" / "erp_hints"

_SPEC = importlib.util.spec_from_file_location(
    "gen_distill_qa", ROOT / "scripts" / "gen_distill_qa.py")
_GEN = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_GEN)


def _pairs():
    return [json.loads(line) for line in QA.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_artifact_nonempty_and_split():
    pairs = _pairs()
    assert len(pairs) >= 20
    splits = {p["split"] for p in pairs}
    assert splits == {"train", "test"}
    assert any(p["split"] == "test" for p in pairs)


def test_every_pair_self_consistent_and_provenanced():
    for p in _pairs():
        assert _GEN._self_consistent(p), f"inconsistent pair: {p['id']}"
        prov = p.get("provenance", {})
        assert prov.get("pack") and prov.get("section") and prov.get("key"), f"no provenance: {p['id']}"


def test_no_client_numbers_distilled():
    # The headline anti-pattern: distillation is CACHE (schema/ontology facts),
    # NOT grounding. No pair may carry a currency value or a bare-number fact.
    for p in _pairs():
        ans = p["reference_answer"]
        assert "€" not in ans and "$" not in ans, f"currency in answer: {p['id']}"
        for f in p["required_facts"]:
            assert not re.fullmatch(r"[\d.,]+", str(f)), f"bare-number fact: {p['id']}"


def test_pack_hashes_match_no_staleness():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for pack_id, recorded in manifest["pack_hashes"].items():
        current = hashlib.sha1((HINTS / f"{pack_id}.yaml").read_bytes()).hexdigest()[:16]
        assert current == recorded, (
            f"hint pack {pack_id}.yaml changed since QA was generated — "
            f"re-run scripts/gen_distill_qa.py (distilled knowledge would be stale)")


def test_frequent_subset_ids_exist_in_golden():
    import yaml
    payload = json.loads(FREQUENT.read_text(encoding="utf-8"))
    assert payload["n_frequent"] >= 1
    golden = yaml.safe_load((ROOT / "evals" / "golden" / "global_questions.yaml").read_text())
    qs = golden["questions"] if isinstance(golden, dict) else golden
    ids = {q["id"] for q in qs}
    for qid in payload["frequent_question_ids"]:
        assert qid in ids, f"frequent id {qid} not in golden set"


def test_generator_is_deterministic():
    # Same packs → same split assignment (stable content-hash split).
    pairs = _pairs()
    sample = pairs[0]
    assert _GEN._split(sample["id"]) == sample["split"]
