"""
N5 enforcement — the analyst citation directive is inert by default (VAL-192).

The A/B enabler (`citation_directive` param on run_analyst) must not change the
prompt unless explicitly passed — prod behavior is unchanged. Offline: the LLM
call is monkeypatched to capture the prompt.
"""

from __future__ import annotations


def _patch_query(monkeypatch, rec):
    from valinor.agents import analyst

    async def fake_query(prompt, options=None):
        rec["prompt"] = prompt

        class _Block:
            text = "[]"

        class _Msg:
            content = [_Block()]

        yield _Msg()

    monkeypatch.setattr(analyst, "query", fake_query)


async def test_citation_directive_inert_by_default(monkeypatch):
    from valinor.agents import analyst
    rec: dict = {}
    _patch_query(monkeypatch, rec)
    await analyst.run_analyst({"results": {}}, {"entities": {}}, None, {}, model="haiku")
    assert "MARKER_CITE" not in rec["prompt"]


async def test_citation_directive_injected_when_set(monkeypatch):
    from valinor.agents import analyst
    rec: dict = {}
    _patch_query(monkeypatch, rec)
    await analyst.run_analyst(
        {"results": {}}, {"entities": {}}, None, {}, model="haiku",
        citation_directive="MARKER_CITE el query_id exacto",
    )
    assert "MARKER_CITE el query_id exacto" in rec["prompt"]
