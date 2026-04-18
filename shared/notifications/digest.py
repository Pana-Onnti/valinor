"""
Digest — channel-agnostic notification payload.

A Digest carries enough structured info that each adapter can render it
to the shape its channel requires (HTML email, short WhatsApp text,
webhook JSON body).

Refs: VAL-130 (L3.a)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class Digest:
    """A cross-channel delivery payload."""
    client_name: str
    title: str                           # subject line / WhatsApp header
    summary: str                         # 1-3 sentence summary
    vertical: str = "generic"            # "inventory", "financial", etc.
    severity: Severity = Severity.INFO
    sections: list[dict[str, Any]] = field(default_factory=list)
    # sections: [{"heading": str, "items": [{"text": str, "severity": Severity, ...}]}]
    html_body: Optional[str] = None      # optional pre-rendered HTML for email
    raw_payload: Optional[dict] = None   # structured body for webhook consumers
    metadata: dict[str, Any] = field(default_factory=dict)
