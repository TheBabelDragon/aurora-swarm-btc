"""Pure helpers for Redis URL redaction and dashboard API-key checks.

Kept free of FastAPI imports so unit tests can run without the web stack.
"""
from __future__ import annotations

import os
from typing import Any, Optional, Tuple


def redact_redis(url: str) -> str:
    """Sanitize Redis URL: never return username/password. Host/port/db kept."""
    if not url:
        return ""
    try:
        if "://" in url and "@" in url:
            scheme, rest = url.split("://", 1)
            host_part = rest.split("@", 1)[1]
            return f"{scheme}://***@{host_part}"
        return url
    except Exception:
        return "redis://***"


def dashboard_api_key() -> str:
    return (os.getenv("AURORA_DASHBOARD_API_KEY") or "").strip()


def check_dashboard_auth(headers: Any) -> Tuple[bool, Optional[str]]:
    """Return (ok, error_detail).

    headers: mapping with optional X-API-Key / Authorization.
    When AURORA_DASHBOARD_API_KEY is unset, always ok.
    """
    expected = dashboard_api_key()
    if not expected:
        return True, None
    get = headers.get if hasattr(headers, "get") else lambda k, d=None: d
    provided = (get("X-API-Key") or get("x-api-key") or "").strip()
    if not provided:
        auth = (get("Authorization") or get("authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    if provided != expected:
        return False, "valid X-API-Key required"
    return True, None
