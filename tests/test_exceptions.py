"""
Tests for api/adapters/exceptions.py — 15 tests covering exception hierarchy,
attributes, and behaviour of all Valinor pipeline exception types.
"""
import pytest

from api.adapters.exceptions import (
    ValinorError,
    SSHConnectionError,
    DatabaseConnectionError,
    PipelineTimeoutError,
    DQGateHaltError,
)


# ── 1. ValinorError can be raised and caught as Exception ──────────────────────
def test_valinor_error_is_exception():
    with pytest.raises(Exception):
        raise ValinorError("base error")


# ── 2. SSHConnectionError is-a ValinorError ────────────────────────────────────
def test_ssh_connection_error_is_valinor_error():
    assert issubclass(SSHConnectionError, ValinorError)


# ── 3. DatabaseConnectionError is-a ValinorError ──────────────────────────────
def test_database_connection_error_is_valinor_error():
    assert issubclass(DatabaseConnectionError, ValinorError)


# ── 4. PipelineTimeoutError is-a ValinorError ─────────────────────────────────
def test_pipeline_timeout_error_is_valinor_error():
    assert issubclass(PipelineTimeoutError, ValinorError)


# ── 5. DQGateHaltError is-a ValinorError ──────────────────────────────────────
def test_dq_gate_halt_error_is_valinor_error():
    assert issubclass(DQGateHaltError, ValinorError)


# ── 6. DQGateHaltError has dq_score attribute ────────────────────────────────
def test_dq_gate_halt_error_has_dq_score():
    err = DQGateHaltError("halt", dq_score=72.5)
    assert hasattr(err, "dq_score")
    assert err.dq_score == 72.5


# ── 7. DQGateHaltError has gate_decision attribute ───────────────────────────
def test_dq_gate_halt_error_has_gate_decision():
    err = DQGateHaltError("halt", gate_decision="HALT")
    assert hasattr(err, "gate_decision")
    assert err.gate_decision == "HALT"


# ── 8. Each exception type stores its message ────────────────────────────────
@pytest.mark.parametrize(
    "exc_class, msg",
    [
        (ValinorError, "valinor msg"),
        (SSHConnectionError, "ssh msg"),
        (DatabaseConnectionError, "db msg"),
        (PipelineTimeoutError, "timeout msg"),
        (DQGateHaltError, "dq halt msg"),
    ],
)
def test_each_exception_stores_message(exc_class, msg):
    exc = exc_class(msg)
    assert exc.args[0] == msg


# ── 9. Exceptions can be caught by base class ValinorError ───────────────────
def test_subclasses_caught_by_valinor_error():
    for exc_class in (
        SSHConnectionError,
        DatabaseConnectionError,
        PipelineTimeoutError,
        DQGateHaltError,
    ):
        with pytest.raises(ValinorError):
            raise exc_class("test")


# ── 10. SSHConnectionError is NOT a DatabaseConnectionError ──────────────────
def test_ssh_not_database_error():
    assert not issubclass(SSHConnectionError, DatabaseConnectionError)


# ── 11. str(exception) returns the message ───────────────────────────────────
def test_str_returns_message():
    msg = "readable message"
    assert str(ValinorError(msg)) == msg
    assert str(SSHConnectionError(msg)) == msg
    assert str(DatabaseConnectionError(msg)) == msg
    assert str(PipelineTimeoutError(msg)) == msg
    assert str(DQGateHaltError(msg)) == msg


# ── 12. DQGateHaltError with score=0.45 stores correct score ─────────────────
def test_dq_gate_halt_error_score_045():
    err = DQGateHaltError("low score", dq_score=0.45)
    assert err.dq_score == 0.45


# ── 13. Exception type name distinguishes different types ────────────────────
def test_exception_type_names_are_distinct():
    names = {
        ValinorError.__name__,
        SSHConnectionError.__name__,
        DatabaseConnectionError.__name__,
        PipelineTimeoutError.__name__,
        DQGateHaltError.__name__,
    }
    assert len(names) == 5


# ── 14. Can re-raise ValinorError subclasses ─────────────────────────────────
def test_reraise_valinor_subclass():
    def inner():
        raise DatabaseConnectionError("original")

    def outer():
        try:
            inner()
        except ValinorError:
            raise

    with pytest.raises(DatabaseConnectionError, match="original"):
        outer()


# ── 15. DQGateHaltError gate_decision default when not provided ───────────────
def test_dq_gate_halt_error_gate_decision_default():
    err = DQGateHaltError("no decision provided")
    assert err.gate_decision is None
