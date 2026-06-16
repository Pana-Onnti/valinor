"""
N5 — active re-query is the deterministic citation lever (VAL-192).

The uncited MEASURED claims are computed aggregates absent from the raw query
results (diagnosed in slice 4). Active re-query (VerificationEngine strategy 4)
re-computes them against the live DB — turning an offline-UNVERIFIABLE claim into
a VERIFIED + cited one, with ZERO LLM variance. This proves the lever on a
self-contained SQLite DB (no real client data, no network).

The catch the slice surfaced: strategy 4 needs ``connection_string`` + ``entity_map``,
which run.py / valinor_adapter currently do NOT pass to VerificationEngine — so
active re-query never fires in prod today.
"""

from __future__ import annotations

import sqlite3

from valinor.verification import VerificationEngine, AtomicClaim, active_requery_enabled
from valinor.quality.agent_grounding_metrics import score_agent_claims


def test_active_requery_flag(monkeypatch):
    monkeypatch.delenv("VALINOR_ACTIVE_REQUERY", raising=False)
    assert active_requery_enabled() is False           # OFF by default → prod intact
    monkeypatch.setenv("VALINOR_ACTIVE_REQUERY", "1")
    assert active_requery_enabled() is True
    monkeypatch.setenv("VALINOR_ACTIVE_REQUERY", "0")
    assert active_requery_enabled() is False


def _make_db(path: str, n_rows: int) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, amount REAL)")
    con.executemany("INSERT INTO sales (amount) VALUES (?)",
                    [(100.0 + i,) for i in range(n_rows)])
    con.commit()
    con.close()


_ENTITY_MAP = {
    "entities": {
        "sales": {
            "table": "sales", "type": "TRANSACTIONAL",
            "key_columns": {"pk": "id"}, "base_filter": "",
        }
    }
}


def _count_claim(value: float):
    return AtomicClaim(
        claim_id="c1", finding_id="F1",
        claim_text=f"hay {int(value)} registros (count)",
        claim_type="numeric", claimed_value=value, claimed_unit="count",
    )


def test_offline_count_claim_is_uncited(tmp_path):
    # No connection_string → strategy 4 can't fire; a computed count isn't a raw
    # cell → UNVERIFIABLE, no verification_query → uncited.
    eng = VerificationEngine({"results": {}}, {}, None)
    r = eng._verify_claim(_count_claim(12))
    assert r.status == "UNVERIFIABLE" and r.verification_query is None
    audit = score_agent_claims([r])
    assert audit.uncited == 1 and audit.cited == 0


def test_active_requery_cites_the_same_claim(tmp_path):
    db = tmp_path / "gloria_synth.db"
    _make_db(str(db), 12)
    eng = VerificationEngine(
        {"results": {}}, {}, None,
        connection_string=f"sqlite:///{db}", entity_map=_ENTITY_MAP,
    )
    r = eng._verify_claim(_count_claim(12))
    # active re-query recomputed COUNT(sales.id)=12 → cited, with the SQL as citation
    assert r.status == "VERIFIED"
    assert r.verification_query is not None
    audit = score_agent_claims([r])
    assert audit.cited == 1 and audit.uncited == 0


def test_active_requery_fails_a_wrong_count(tmp_path):
    # The lever can't fabricate a citation: a wrong value is FAILED, not cited.
    db = tmp_path / "gloria_synth.db"
    _make_db(str(db), 12)
    eng = VerificationEngine(
        {"results": {}}, {}, None,
        connection_string=f"sqlite:///{db}", entity_map=_ENTITY_MAP,
    )
    r = eng._verify_claim(_count_claim(999))
    assert r.status in ("FAILED", "UNVERIFIABLE")
    assert score_agent_claims([r]).cited == 0
