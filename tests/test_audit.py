"""
Audit log integration for the N4 memory-review decisions (VAL-192).

emit_audit_event is the single, best-effort append to the Redis FIFO; the
approve/reject endpoints emit a `memory_review` event with provenance + the
decision. Covered offline with a fake redis (no real Redis needed).
"""

from __future__ import annotations

import json


class _FakeRedis:
    def __init__(self):
        self.items = []
        self.trimmed = None

    async def lpush(self, key, val):
        self.items.insert(0, val)
        return len(self.items)

    async def ltrim(self, key, start, end):
        self.trimmed = (start, end)
        return True


# ── emit_audit_event ──────────────────────────────────────────────────────────

async def test_emit_appends_and_stamps_timestamp():
    from api.audit import emit_audit_event
    r = _FakeRedis()
    ok = await emit_audit_event({"event_type": "memory_review", "action": "approve"}, redis_client=r)
    assert ok is True
    assert len(r.items) == 1
    evt = json.loads(r.items[0])
    assert evt["action"] == "approve"
    assert "timestamp" in evt


async def test_emit_trims_to_cap():
    from api.audit import emit_audit_event, AUDIT_LOG_CAP
    r = _FakeRedis()
    await emit_audit_event({"event_type": "x"}, redis_client=r)
    assert r.trimmed == (0, AUDIT_LOG_CAP - 1)


async def test_emit_best_effort_on_failure():
    from api.audit import emit_audit_event

    class _BoomRedis:
        async def lpush(self, *a):
            raise RuntimeError("redis down")

        async def ltrim(self, *a):
            return True

    ok = await emit_audit_event({"event_type": "x"}, redis_client=_BoomRedis())
    assert ok is False                      # never raises


async def test_emit_uses_get_redis_when_no_client(monkeypatch):
    import api.deps
    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake

    monkeypatch.setattr(api.deps, "get_redis", _fake_get_redis)
    from api.audit import emit_audit_event
    ok = await emit_audit_event({"event_type": "x"})
    assert ok is True and len(fake.items) == 1


# ── the memory-review audit helper ────────────────────────────────────────────

async def test_review_audit_event_shape_for_escalation(monkeypatch):
    import api.audit as audit_mod
    captured = {}

    async def _fake_emit(event, redis_client=None):
        captured.update(event)
        return True

    monkeypatch.setattr(audit_mod, "emit_audit_event", _fake_emit)
    from api.routers.clients import _emit_review_audit
    rec = {"proposal_id": "pe_1", "run_id": "job9", "confidence": 0.8,
           "finding_id": "f1", "from_severity": "MEDIUM", "to_severity": "HIGH"}
    await _emit_review_audit("approve", "pending_escalations", "Gloria_SA", rec, "loren")

    assert captured["event_type"] == "memory_review"
    assert captured["action"] == "approve"
    assert captured["queue"] == "pending_escalations"
    assert captured["client_name"] == "Gloria_SA"
    assert captured["proposal_id"] == "pe_1"
    assert captured["reviewed_by"] == "loren"
    assert captured["from_severity"] == "MEDIUM" and captured["to_severity"] == "HIGH"
    assert captured["run_id"] == "job9" and captured["confidence"] == 0.8


async def test_review_audit_event_includes_reason_on_reject(monkeypatch):
    import api.audit as audit_mod
    captured = {}

    async def _fake_emit(event, redis_client=None):
        captured.update(event)
        return True

    monkeypatch.setattr(audit_mod, "emit_audit_event", _fake_emit)
    from api.routers.clients import _emit_review_audit
    rec = {"proposal_id": "pr_2", "run_id": "job9", "confidence": 0.9}
    await _emit_review_audit("reject", "pending_refinements", "Gloria_SA", rec,
                             "loren", reason="hallucinated weight")

    assert captured["action"] == "reject"
    assert captured["queue"] == "pending_refinements"
    assert captured["reason"] == "hallucinated weight"
    # escalation-only fields are absent for a refinement event
    assert "from_severity" not in captured
