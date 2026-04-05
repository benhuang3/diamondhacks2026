"""SSRF defenses for user-supplied URLs.

Two layers:

* :func:`validate_public_url` — sync/cheap. Enforces scheme, hostname
  presence, and blocks IP literals / hostnames that point at private,
  loopback, link-local, or cloud-metadata ranges. Safe to call from Pydantic
  validators (no DNS).
* :func:`resolve_public_url` — async. Performs DNS resolution and rejects
  hostnames that resolve to any disallowed IP. Call this immediately before
  actually fetching the URL.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hostnames that are not IPs but should always be treated as dangerous.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata",
    }
)


class UnsafeURLError(ValueError):
    """Raised when a URL fails SSRF validation."""


def _ip_is_disallowed(ip: ipaddress._BaseAddress) -> bool:
    """Reject any non-globally-routable IP."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(raw: str) -> str:
    """Raise UnsafeURLError if *raw* is not a safe public http(s) URL.

    Returns the URL unchanged on success. Does not perform DNS resolution.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise UnsafeURLError("url must be a non-empty string")

    parsed = urlparse(raw.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise UnsafeURLError("url scheme must be http or https")

    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeURLError("url must include a hostname")

    if host in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError("url host is not allowed")

    # If the host is an IP literal, enforce immediately.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and _ip_is_disallowed(ip):
        raise UnsafeURLError("url resolves to a non-public address")

    # Block the AWS/GCP/Azure IMDS hostname family even if it's an IP we
    # already covered above, for defense in depth.
    if host == "169.254.169.254":
        raise UnsafeURLError("url host is not allowed")

    return raw.strip()


async def resolve_public_url(raw: str) -> str:
    """Validate + DNS-resolve, rejecting any non-public IP.

    Use this right before actually fetching the URL. Raises UnsafeURLError on
    any violation, including DNS resolution failure.
    """
    url = validate_public_url(raw)
    host = urlparse(url).hostname or ""

    # If host is already an IP literal, validate_public_url covered it.
    try:
        ipaddress.ip_address(host)
        return url
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"url host did not resolve: {host}") from e

    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _ip_is_disallowed(ip):
            raise UnsafeURLError("url resolves to a non-public address")

    return url
