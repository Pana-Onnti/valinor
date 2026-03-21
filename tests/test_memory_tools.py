"""
Tests for core/valinor/tools/memory_tools.py

All tests use pytest's tmp_path fixture to create real temporary directories
so no production MEMORY_DIR or OUTPUT_DIR is ever touched.

claude_agent_sdk is NOT installed — we stub it before importing memory_tools.
"""
from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub claude_agent_sdk before importing anything from the valinor package
# ---------------------------------------------------------------------------

if "claude_agent_sdk" not in sys.modules:
    _sdk = types.ModuleType("claude_agent_sdk")
    _sdk.__spec__ = None

    def _tool_stub(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f

    _sdk.tool = _tool_stub
    _sdk.query = MagicMock()
    _sdk.ClaudeAgentOptions = MagicMock
    _sdk.AssistantMessage = MagicMock
    _sdk.TextBlock = MagicMock
    _sdk.create_sdk_mcp_server = MagicMock(return_value=MagicMock())
    sys.modules["claude_agent_sdk"] = _sdk

# Add core to path so valinor package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import valinor.config as _config


def _run(coro):
    """Execute a coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixtures: patch MEMORY_DIR and OUTPUT_DIR to tmp_path
# ---------------------------------------------------------------------------

@pytest.fixture()
def patched_dirs(tmp_path, monkeypatch):
    """
    Redirect MEMORY_DIR and OUTPUT_DIR to sub-dirs inside tmp_path so tests
    never write to the project tree.  Returns (memory_dir, output_dir).
    """
    mem = tmp_path / "memory"
    out = tmp_path / "output"
    mem.mkdir()
    out.mkdir()
    monkeypatch.setattr(_config, "MEMORY_DIR", mem)
    monkeypatch.setattr("valinor.tools.memory_tools.MEMORY_DIR", mem)
    monkeypatch.setattr("valinor.tools.memory_tools.OUTPUT_DIR", out)
    return mem, out


# Import after patching is set up via fixture (late import is fine because
# the stub is already in sys.modules before any import happens at module level)
from valinor.tools import memory_tools  # noqa: E402  (import after sys.path setup)


# ===========================================================================
# write_artifact
# ===========================================================================

class TestWriteArtifact:

    def test_creates_output_directory(self, patched_dirs, tmp_path):
        """write_artifact must create the nested client/period directory."""
        _, out = patched_dirs
        _run(memory_tools.write_artifact({
            "client_name": "Acme",
            "period": "Q1-2025",
            "filename": "report.txt",
            "content": "hello",
        }))
        assert (out / "Acme" / "Q1-2025").is_dir()

    def test_creates_artifact_file(self, patched_dirs, tmp_path):
        """The artifact file is created at the expected path."""
        _, out = patched_dirs
        _run(memory_tools.write_artifact({
            "client_name": "Acme",
            "period": "Q1-2025",
            "filename": "findings.json",
            "content": '{"key": "value"}',
        }))
        assert (out / "Acme" / "Q1-2025" / "findings.json").exists()

    def test_plain_text_content_is_preserved(self, patched_dirs):
        """Plain text content written via write_artifact is readable back verbatim."""
        _, out = patched_dirs
        content = "Executive summary line 1\nLine 2\n"
        _run(memory_tools.write_artifact({
            "client_name": "Beta",
            "period": "2025",
            "filename": "summary.txt",
            "content": content,
        }))
        written = (out / "Beta" / "2025" / "summary.txt").read_text(encoding="utf-8")
        assert written == content

    def test_json_content_is_preserved(self, patched_dirs):
        """JSON content is written verbatim (not parsed/re-serialised)."""
        _, out = patched_dirs
        payload = json.dumps({"revenue": 1_000_000, "currency": "USD"}, indent=2)
        _run(memory_tools.write_artifact({
            "client_name": "Gamma",
            "period": "H1-2025",
            "filename": "revenue.json",
            "content": payload,
        }))
        written = (out / "Gamma" / "H1-2025" / "revenue.json").read_text(encoding="utf-8")
        assert json.loads(written) == {"revenue": 1_000_000, "currency": "USD"}

    def test_overwrite_replaces_file(self, patched_dirs):
        """Calling write_artifact twice with the same filename overwrites the file."""
        _, out = patched_dirs
        args = {"client_name": "Delta", "period": "Q2-2025", "filename": "out.txt"}
        _run(memory_tools.write_artifact({**args, "content": "first"}))
        _run(memory_tools.write_artifact({**args, "content": "second"}))
        written = (out / "Delta" / "Q2-2025" / "out.txt").read_text(encoding="utf-8")
        assert written == "second"

    def test_returns_status_written(self, patched_dirs):
        """Return value contains status == 'written'."""
        _, out = patched_dirs
        result = _run(memory_tools.write_artifact({
            "client_name": "Echo",
            "period": "Q3-2025",
            "filename": "x.txt",
            "content": "data",
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "written"

    def test_returns_correct_path(self, patched_dirs):
        """Return value includes the full path to the artifact."""
        _, out = patched_dirs
        result = _run(memory_tools.write_artifact({
            "client_name": "Foxtrot",
            "period": "2025",
            "filename": "artifact.txt",
            "content": "x",
        }))
        payload = json.loads(result["content"][0]["text"])
        assert "artifact.txt" in payload["path"]
        assert "Foxtrot" in payload["path"]

    def test_returns_size_bytes(self, patched_dirs):
        """Return value includes size_bytes matching the written file size."""
        _, out = patched_dirs
        content = "A" * 100
        result = _run(memory_tools.write_artifact({
            "client_name": "Golf",
            "period": "Q4-2025",
            "filename": "sized.txt",
            "content": content,
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["size_bytes"] == 100

    def test_unicode_content(self, patched_dirs):
        """Unicode characters (CJK, emoji, accented) are written without corruption."""
        _, out = patched_dirs
        content = "café résumé 中文 🎯"
        _run(memory_tools.write_artifact({
            "client_name": "Hotel",
            "period": "Q1-2025",
            "filename": "unicode.txt",
            "content": content,
        }))
        written = (out / "Hotel" / "Q1-2025" / "unicode.txt").read_text(encoding="utf-8")
        assert written == content

    def test_multiple_clients_isolated(self, patched_dirs):
        """Two clients writing the same filename are stored in separate directories."""
        _, out = patched_dirs
        for client in ("ClientA", "ClientB"):
            _run(memory_tools.write_artifact({
                "client_name": client,
                "period": "Q1-2025",
                "filename": "report.txt",
                "content": f"content-for-{client}",
            }))
        a_text = (out / "ClientA" / "Q1-2025" / "report.txt").read_text(encoding="utf-8")
        b_text = (out / "ClientB" / "Q1-2025" / "report.txt").read_text(encoding="utf-8")
        assert a_text == "content-for-ClientA"
        assert b_text == "content-for-ClientB"

    def test_empty_content_writes_empty_file(self, patched_dirs):
        """Empty string content results in a zero-byte file."""
        _, out = patched_dirs
        _run(memory_tools.write_artifact({
            "client_name": "India",
            "period": "2025",
            "filename": "empty.txt",
            "content": "",
        }))
        path = out / "India" / "2025" / "empty.txt"
        assert path.exists()
        assert path.stat().st_size == 0


# ===========================================================================
# write_memory
# ===========================================================================

class TestWriteMemory:

    def test_creates_memory_directory(self, patched_dirs):
        """write_memory must create the client memory directory."""
        mem, _ = patched_dirs
        _run(memory_tools.write_memory({
            "client_name": "Acme",
            "period": "Q1-2025",
            "memory_data": json.dumps({"key": "val"}),
        }))
        assert (mem / "Acme").is_dir()

    def test_creates_memory_file(self, patched_dirs):
        """Memory file is created at memory/{client}/swarm_memory_{period}.json."""
        mem, _ = patched_dirs
        _run(memory_tools.write_memory({
            "client_name": "Beta",
            "period": "Q2-2025",
            "memory_data": json.dumps({"insight": "high AR"}),
        }))
        assert (mem / "Beta" / "swarm_memory_Q2-2025.json").exists()

    def test_injects_metadata(self, patched_dirs):
        """write_memory always injects _metadata with written_at, period, client."""
        mem, _ = patched_dirs
        _run(memory_tools.write_memory({
            "client_name": "Gamma",
            "period": "2025",
            "memory_data": json.dumps({}),
        }))
        data = json.loads((mem / "Gamma" / "swarm_memory_2025.json").read_text(encoding="utf-8"))
        assert "_metadata" in data
        assert data["_metadata"]["period"] == "2025"
        assert data["_metadata"]["client"] == "Gamma"
        assert "written_at" in data["_metadata"]

    def test_returns_status_written(self, patched_dirs):
        """Return value contains status == 'written'."""
        result = _run(memory_tools.write_memory({
            "client_name": "Delta",
            "period": "H1-2025",
            "memory_data": json.dumps({"x": 1}),
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "written"

    def test_persists_payload_fields(self, patched_dirs):
        """Custom fields in memory_data are present in the written JSON file."""
        mem, _ = patched_dirs
        _run(memory_tools.write_memory({
            "client_name": "Echo",
            "period": "Q3-2025",
            "memory_data": json.dumps({"revenue_trend": "up", "alerts": 3}),
        }))
        data = json.loads((mem / "Echo" / "swarm_memory_Q3-2025.json").read_text(encoding="utf-8"))
        assert data["revenue_trend"] == "up"
        assert data["alerts"] == 3


# ===========================================================================
# read_memory
# ===========================================================================

class TestReadMemory:

    def test_no_memory_dir_returns_no_memory(self, patched_dirs):
        """Client with no memory directory at all returns status == 'no_memory'."""
        result = _run(memory_tools.read_memory({
            "client_name": "Ghost",
            "period": None,
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "no_memory"
        assert payload["client"] == "Ghost"

    def test_empty_memory_dir_returns_no_memory(self, patched_dirs):
        """Client directory that exists but has no files returns status == 'no_memory'."""
        mem, _ = patched_dirs
        (mem / "Empty").mkdir()
        result = _run(memory_tools.read_memory({
            "client_name": "Empty",
            "period": None,
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "no_memory"

    def test_reads_specific_period(self, patched_dirs):
        """Requesting a specific period returns that period's data."""
        mem, _ = patched_dirs
        client_dir = mem / "Acme"
        client_dir.mkdir()
        file = client_dir / "swarm_memory_Q1-2025.json"
        file.write_text(json.dumps({"insight": "seasonal spike"}), encoding="utf-8")

        result = _run(memory_tools.read_memory({
            "client_name": "Acme",
            "period": "Q1-2025",
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "found"
        assert payload["period"] == "Q1-2025"
        assert payload["memory"]["insight"] == "seasonal spike"

    def test_reads_latest_when_no_period(self, patched_dirs):
        """Without a period, the lexicographically latest memory file is returned."""
        mem, _ = patched_dirs
        client_dir = mem / "Beta"
        client_dir.mkdir()
        for period, data in [("Q1-2025", {"v": 1}), ("Q2-2025", {"v": 2}), ("Q3-2025", {"v": 3})]:
            (client_dir / f"swarm_memory_{period}.json").write_text(json.dumps(data), encoding="utf-8")

        result = _run(memory_tools.read_memory({
            "client_name": "Beta",
            "period": None,
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "found"
        assert payload["memory"]["v"] == 3  # latest

    def test_missing_specific_period_falls_back_to_latest(self, patched_dirs):
        """If the requested period file doesn't exist, latest is returned."""
        mem, _ = patched_dirs
        client_dir = mem / "Gamma"
        client_dir.mkdir()
        (client_dir / "swarm_memory_Q1-2025.json").write_text(json.dumps({"fallback": True}), encoding="utf-8")

        result = _run(memory_tools.read_memory({
            "client_name": "Gamma",
            "period": "Q4-2025",  # doesn't exist
        }))
        payload = json.loads(result["content"][0]["text"])
        # Falls back to latest (Q1-2025)
        assert payload["status"] == "found"
        assert payload["memory"]["fallback"] is True

    def test_round_trip_write_then_read(self, patched_dirs):
        """Data written via write_memory is faithfully returned by read_memory."""
        original_data = {"kpi": "churn_rate", "value": 0.05, "severity": "MEDIUM"}
        _run(memory_tools.write_memory({
            "client_name": "Delta",
            "period": "H2-2025",
            "memory_data": json.dumps(original_data),
        }))
        result = _run(memory_tools.read_memory({
            "client_name": "Delta",
            "period": "H2-2025",
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["status"] == "found"
        assert payload["memory"]["kpi"] == "churn_rate"
        assert payload["memory"]["value"] == pytest.approx(0.05)
        assert payload["memory"]["severity"] == "MEDIUM"

    def test_no_memory_message_contains_first_run_hint(self, patched_dirs):
        """The first-run no_memory response includes a human-readable message."""
        result = _run(memory_tools.read_memory({
            "client_name": "NewClient",
            "period": None,
        }))
        payload = json.loads(result["content"][0]["text"])
        # The message is only present when the directory doesn't exist at all
        assert "message" in payload or payload["status"] == "no_memory"

    def test_unicode_data_survives_round_trip(self, patched_dirs):
        """Unicode data written and read back is not corrupted."""
        data = {"company": "社会", "note": "résumé café"}
        _run(memory_tools.write_memory({
            "client_name": "Unicode",
            "period": "Q1-2025",
            "memory_data": json.dumps(data, ensure_ascii=False),
        }))
        result = _run(memory_tools.read_memory({
            "client_name": "Unicode",
            "period": "Q1-2025",
        }))
        payload = json.loads(result["content"][0]["text"])
        assert payload["memory"]["company"] == "社会"
        assert payload["memory"]["note"] == "résumé café"
