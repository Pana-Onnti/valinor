"""
Structured exception types for the Valinor adapter pipeline.
"""


class ValinorError(Exception):
    """Base exception for all Valinor pipeline errors."""
    pass


class SSHConnectionError(ValinorError):
    """Raised when an SSH tunnel or remote host connection fails."""
    pass


class DatabaseConnectionError(ValinorError):
    """Raised when the database connection cannot be established."""
    pass


class PipelineTimeoutError(ValinorError):
    """Raised when the analysis pipeline exceeds the allowed time budget."""
    pass


class DQGateHaltError(ValinorError):
    """
    Raised when the Data Quality Gate decides to HALT analysis.

    Attributes:
        dq_score: Overall DQ score (0-100) that triggered the halt.
        gate_decision: The gate decision string (should be "HALT").
    """

    def __init__(self, msg: str, dq_score=None, gate_decision=None):
        super().__init__(msg)
        self.dq_score = dq_score
        self.gate_decision = gate_decision
