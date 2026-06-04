"""
Outbound-host SSRF guard (VAL-108 / VAL-174).

Reject any host that IS, or RESOLVES TO, a private / loopback / link-local /
reserved address — in every IP encoding (dotted/decimal/hex/octal/IPv6/
IPv4-mapped) and for hostnames that resolve to internal addresses. Shared by the
onboarding test-connection endpoint and the nl-query inline-DSN path so the two
cannot drift.
"""
from __future__ import annotations

import re
import socket
import ipaddress

from fastapi import HTTPException

_ALLOWED_HOSTNAME = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$')

# Names that always point at a host-local / internal target — blocked by name
# (offline-safe; getaddrinfo would catch most of these too).
_BLOCKED_HOSTNAMES = {
    "localhost", "localhost.localdomain", "ip6-localhost",
    "metadata", "metadata.google.internal",
    "instance-data", "instance-data.ec2.internal",
}


def ip_is_blocked(ip_str: str) -> bool:
    """True if ip_str parses to a private/loopback/link-local/reserved/multicast/unspecified IP."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def validate_outbound_host(host: str) -> None:
    """
    Zero-trust SSRF guard: reject any host that IS, or RESOLVES TO, a private /
    loopback / link-local / reserved address. Uses ipaddress + getaddrinfo, so IP
    literals in every encoding and hostnames that resolve to internal addresses are
    all caught — not just dotted-quad regexes. Raises HTTPException(400) on violation.
    """
    if not host or len(host) > 253:
        raise HTTPException(status_code=400, detail="Invalid host value")

    h = host.strip().lower().strip("[]")  # tolerate IPv6 brackets
    if h in _BLOCKED_HOSTNAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Host '{host}' is not allowed (zero-trust policy)",
        )

    # Direct IP literal (dotted IPv4 / IPv6) that is internal.
    if ip_is_blocked(h):
        raise HTTPException(
            status_code=400,
            detail=f"Host '{host}' is in a reserved/private range (zero-trust policy)",
        )

    # Resolve to IP(s). getaddrinfo also canonicalizes integer/hex/octal IP forms
    # (e.g. 2130706433, 0x7f000001 -> 127.0.0.1), so encoded-loopback bypasses get
    # caught here. Unresolvable at validation time -> don't hard-fail (connect will).
    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(h, None)}
    except (socket.gaierror, OSError, UnicodeError):
        resolved = set()
    for ip_str in resolved:
        if ip_is_blocked(ip_str):
            raise HTTPException(
                status_code=400,
                detail=f"Host '{host}' resolves to a reserved/private address (zero-trust policy)",
            )

    # Hostnames that didn't resolve must still look like hostnames.
    if not resolved and not _ALLOWED_HOSTNAME.match(h):
        raise HTTPException(status_code=400, detail=f"Invalid hostname format: '{host}'")
