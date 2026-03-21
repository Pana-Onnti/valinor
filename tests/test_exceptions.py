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


# ── 16. Exception messages are preserved ─────────────────────────────────────
def test_exception_message_preserved():
    msg = "critical pipeline failure"
    err = PipelineTimeoutError(msg)
    assert str(err) == msg or msg in str(err)


# ── 17. SSHConnectionError carries host info if provided ─────────────────────
def test_ssh_connection_error_message():
    err = SSHConnectionError("Connection refused to bastion.example.com")
    assert "bastion" in str(err) or "Connection" in str(err)


# ── 18. Multiple exception types in single except clause ─────────────────────
def test_catch_multiple_valinor_errors():
    errors = [
        SSHConnectionError("ssh"),
        DatabaseConnectionError("db"),
        PipelineTimeoutError("timeout"),
    ]
    caught = []
    for e in errors:
        try:
            raise e
        except (SSHConnectionError, DatabaseConnectionError, PipelineTimeoutError):
            caught.append(type(e).__name__)
    assert len(caught) == 3


# ── 19. DQGateHaltError with gate_decision provided ──────────────────────────
def test_dq_gate_halt_error_with_decision():
    decision = {"halted": True, "failed_checks": ["null_ratio"], "score": 0.3}
    err = DQGateHaltError("gate halted", gate_decision=decision)
    assert err.gate_decision == decision
    assert err.gate_decision["halted"] is True


# ── 20. ValinorError is hashable / usable in sets ────────────────────────────
def test_valinor_error_in_exception_tracking():
    seen_types = set()
    for exc_class in [SSHConnectionError, DatabaseConnectionError, PipelineTimeoutError]:
        try:
            raise exc_class("test")
        except ValinorError as e:
            seen_types.add(type(e))
    assert len(seen_types) == 3


# ── 21. Full MRO: SSHConnectionError → ValinorError → Exception → BaseException ─
def test_ssh_connection_error_full_mro():
    mro = SSHConnectionError.__mro__
    names = [c.__name__ for c in mro]
    assert names == ["SSHConnectionError", "ValinorError", "Exception", "BaseException", "object"]


# ── 22. All subclasses are instances of Exception ───────────────────────────
def test_all_subclasses_are_instances_of_exception():
    for exc_class in (SSHConnectionError, DatabaseConnectionError, PipelineTimeoutError, DQGateHaltError):
        exc = exc_class("msg")
        assert isinstance(exc, Exception)
        assert isinstance(exc, BaseException)


# ── 23. Catching specific type does not catch sibling type ──────────────────
def test_specific_catch_does_not_catch_sibling():
    caught = []
    try:
        raise SSHConnectionError("ssh only")
    except DatabaseConnectionError:
        caught.append("db")
    except SSHConnectionError:
        caught.append("ssh")
    assert caught == ["ssh"]


# ── 24. Exception with empty string message ──────────────────────────────────
def test_exception_with_empty_string_message():
    for exc_class in (ValinorError, SSHConnectionError, DatabaseConnectionError, PipelineTimeoutError):
        exc = exc_class("")
        assert exc.args[0] == ""
        assert str(exc) == ""


# ── 25. Exception re-raise preserves original type ──────────────────────────
def test_reraise_preserves_exact_type():
    original = PipelineTimeoutError("timed out")
    caught = None
    try:
        try:
            raise original
        except ValinorError:
            raise
    except Exception as e:
        caught = e
    assert type(caught) is PipelineTimeoutError
    assert caught is original


# ── 26. DQGateHaltError dq_score defaults to None ───────────────────────────
def test_dq_gate_halt_error_dq_score_default():
    err = DQGateHaltError("no score")
    assert err.dq_score is None


# ── 27. DQGateHaltError stores both dq_score and gate_decision simultaneously ─
def test_dq_gate_halt_error_both_attributes():
    err = DQGateHaltError("halt", dq_score=55.0, gate_decision="HALT")
    assert err.dq_score == 55.0
    assert err.gate_decision == "HALT"
    assert err.args[0] == "halt"


# ── 28. repr() of each exception contains the class name ────────────────────
def test_repr_contains_class_name():
    for exc_class in (ValinorError, SSHConnectionError, DatabaseConnectionError, PipelineTimeoutError, DQGateHaltError):
        exc = exc_class("some message")
        assert exc_class.__name__ in repr(exc)


# ── 29. Chained exception stores original as __cause__ ──────────────────────
def test_chained_exception_stores_cause():
    original = ValueError("root cause")
    try:
        try:
            raise original
        except ValueError as e:
            raise SSHConnectionError("wrapped") from e
    except SSHConnectionError as exc:
        assert exc.__cause__ is original
        assert isinstance(exc.__cause__, ValueError)
        assert str(exc.__cause__) == "root cause"


# ── 30. raise X from Y — __suppress_context__ is True ───────────────────────
def test_chained_exception_suppresses_context():
    try:
        try:
            raise RuntimeError("inner")
        except RuntimeError as e:
            raise DatabaseConnectionError("outer") from e
    except DatabaseConnectionError as exc:
        assert exc.__suppress_context__ is True


# ── 31. DQGateHaltError can be raised and caught as both ValinorError and Exception ─
def test_dq_gate_halt_caught_as_valinor_and_exception():
    raised_as_valinor = False
    try:
        raise DQGateHaltError("halt", dq_score=10.0)
    except ValinorError:
        raised_as_valinor = True
    assert raised_as_valinor

    raised_as_exception = False
    try:
        raise DQGateHaltError("halt again")
    except Exception:
        raised_as_exception = True
    assert raised_as_exception


# ── 32. All exception classes are distinct types (not aliases) ───────────────
def test_exception_classes_are_distinct_objects():
    classes = [ValinorError, SSHConnectionError, DatabaseConnectionError, PipelineTimeoutError, DQGateHaltError]
    # Each pair must be a different class object
    for i, a in enumerate(classes):
        for b in classes[i + 1:]:
            assert a is not b
