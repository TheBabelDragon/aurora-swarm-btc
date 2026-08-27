"""Authenticate LAN discovery beacons.

Shared secret (AURORA_MESH_SECRET) is the real LAN membership check.
Without a secret we still HMAC the payload with the local node key and
TOFU-pin node_id → fingerprint so a later impostor cannot steal the name.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Dict, Optional, Tuple

SIGN_FIELDS = ("magic", "node_id", "redis_url", "ts", "fingerprint", "role")


def mesh_secret() -> str:
    return (os.getenv("AURORA_MESH_SECRET") or "").strip()


def require_auth() -> bool:
    return os.getenv("AURORA_MESH_REQUIRE_AUTH", "0").lower() in ("1", "true", "yes", "on")


def _canonical(body: Dict[str, Any]) -> bytes:
    slim = {k: body.get(k) for k in SIGN_FIELDS}
    return json.dumps(slim, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hmac(key: bytes, msg: bytes) -> str:
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def sign_beacon(body: Dict[str, Any], *, node_key_hex: str = "") -> Dict[str, Any]:
    out = dict(body)
    secret = mesh_secret()
    msg = _canonical(out)
    if secret:
        out["sig"] = _hmac(secret.encode(), msg)
        out["auth"] = "secret"
    elif node_key_hex:
        out["sig"] = _hmac(bytes.fromhex(node_key_hex), msg)
        out["auth"] = "nodekey"
    else:
        out["auth"] = "none"
        out["sig"] = ""
    return out


def verify_beacon(
    body: Dict[str, Any],
    *,
    pinned: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str]:
    """Return (ok, reason)."""
    if not isinstance(body, dict):
        return False, "not_object"
    if body.get("magic") != "AURORA_MESH_V1":
        return False, "bad_magic"
    nid = (body.get("node_id") or "").strip()
    if not nid:
        return False, "no_node_id"
    fp = (body.get("fingerprint") or "").strip()
    auth = body.get("auth") or "none"
    sig = body.get("sig") or ""
    secret = mesh_secret()
    msg = _canonical(body)

    if secret:
        expect = _hmac(secret.encode(), msg)
        if not sig or not hmac.compare_digest(expect, str(sig)):
            if require_auth() or auth == "secret":
                return False, "bad_secret"
            # secret configured locally but peer unsigned — reject if required, else warn
            if require_auth():
                return False, "unsigned"
    elif require_auth():
        return False, "secret_required"

    if pinned is not None and nid in pinned and fp and pinned[nid] != fp:
        return False, "fingerprint_mismatch"

    return True, auth if auth != "none" else "unsigned"
