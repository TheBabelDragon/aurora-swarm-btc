"""HTTPS URL normalization and destination policy for the viewer.

Rejects non-HTTPS schemes, embedded credentials, invalid ports, and applies
SSRF defenses consistent with comms.routing.policy. Redirect targets must be
revalidated as new destinations.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlparse, urlunparse

from comms.routing.policy import is_blocked_address

_BLOCKED_PORTS = frozenset({
    22, 23, 25, 111, 135, 139, 445, 1433, 1521, 3306, 5432,
    6379,
    7379,
    11211, 27017, 9200, 9300,
})

_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
    "metadata",
    "instance-data",
})

_HOST_RE = re.compile(
    r"^(?:(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)$"
    r"|^(?:\[[0-9a-fA-F:.]+\])$"
    r"|^(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3})$"
)


class ViewerUrlError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class NormalizedHttpsUrl:
    original: str
    scheme: str
    hostname: str
    port: int
    path: str
    query: str
    fragment: str = ""

    @property
    def netloc(self) -> str:
        if self.port == 443:
            return self.hostname
        host = self.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{host}:{self.port}"

    @property
    def absolute(self) -> str:
        return urlunparse((
            self.scheme,
            self.netloc,
            self.path or "/",
            "",
            self.query,
            "",
        ))

    def to_dict(self) -> dict:
        return {
            "scheme": self.scheme,
            "hostname": self.hostname,
            "port": self.port,
            "path": self.path or "/",
            "query": self.query,
            "absolute": self.absolute,
        }


def normalize_https_url(raw: str, *, max_length: int = 2048) -> NormalizedHttpsUrl:
    if raw is None or not str(raw).strip():
        raise ViewerUrlError("empty_url", "URL is required")
    raw_s = str(raw)
    if any(c in raw_s for c in ("\r", "\n", "\x00")):
        raise ViewerUrlError("invalid_url", "URL contains control characters")
    text = raw_s.strip()
    if len(text) > max_length:
        raise ViewerUrlError("url_too_long", f"URL exceeds {max_length} characters")

    parsed = urlparse(text)
    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        raise ViewerUrlError(
            "unsupported_scheme",
            f"Only https is allowed (got {scheme or 'none'})",
        )

    if parsed.username is not None or parsed.password is not None:
        raise ViewerUrlError("credentials_forbidden", "Embedded credentials are not allowed")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ViewerUrlError("missing_host", "Hostname is required")

    if "%" in hostname:
        hostname = hostname.split("%", 1)[0]

    if hostname in _BLOCKED_HOSTNAMES:
        raise ViewerUrlError("blocked_hostname", f"Hostname {hostname} is not allowed")

    try:
        ip = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        if is_blocked_address(str(ip)):
            raise ViewerUrlError("blocked_address", f"Address {ip} is not allowed")
    else:
        if not _HOST_RE.match(hostname) and not (
            hostname.startswith("[") and hostname.endswith("]")
        ):
            if " " in hostname or hostname.startswith("."):
                raise ViewerUrlError("invalid_hostname", "Malformed hostname")

    try:
        port = parsed.port if parsed.port is not None else 443
    except ValueError as e:
        raise ViewerUrlError("invalid_port", "Invalid port") from e

    if port < 1 or port > 65535:
        raise ViewerUrlError("invalid_port", "Port out of range")
    if port in _BLOCKED_PORTS:
        raise ViewerUrlError("blocked_port", f"Port {port} is not allowed for viewer destinations")

    path = parsed.path or "/"
    query = parsed.query or ""

    return NormalizedHttpsUrl(
        original=text,
        scheme="https",
        hostname=hostname.strip("[]"),
        port=port,
        path=path,
        query=query,
        fragment=parsed.fragment or "",
    )


def validate_resolved_addresses(
    addresses: Sequence[str],
    port: int,
    *,
    allow_private: bool = False,
) -> Tuple[bool, str]:
    if not addresses:
        return False, "no_resolved_addresses"
    if port in _BLOCKED_PORTS:
        return False, f"blocked_port:{port}"
    for addr in addresses:
        a = (addr or "").strip()
        if not a:
            continue
        if is_blocked_address(a, allow_private=allow_private):
            return False, f"blocked_address:{a}"
    return True, "ok"


def is_redirect_safe(location_header: str, *, max_length: int = 2048) -> NormalizedHttpsUrl:
    return normalize_https_url(location_header, max_length=max_length)
