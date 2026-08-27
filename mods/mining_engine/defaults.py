"""Shared mining defaults."""

import os
import re

DEFAULT_MINING_WALLET = "bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g"
DEFAULT_POOL_URL = "stratum+tcp://stratum.braiins.com:3333"
SOLO_POOL_URL = "stratum+tcp://solo.stratum.braiins.com:3333"
DEFAULT_INTENSITY = "19"

_ADDR = re.compile(r"^(bc1|[13])[a-zA-HJ-NP-Z0-9]{20,}$")
_WORKER = re.compile(r"[^a-zA-Z0-9_@+:-]+")


def looks_like_btc_address(s: str) -> bool:
    return bool(_ADDR.match((s or "").strip()))


def sanitize_worker(name: str) -> str:
    w = _WORKER.sub("-", (name or "aurora").strip())[:24].strip("-") or "aurora"
    return w


def resolve_pool_url(wallet: str, pool_url: str | None = None) -> str:
    """Address wallets go to Braiins SOLO so coinbase/payout can hit the address.

    Explicit POOL_URL always wins.
    """
    explicit = (os.getenv("POOL_URL") or "").strip()
    if explicit:
        return explicit
    if pool_url and pool_url.strip() and pool_url.strip() != DEFAULT_POOL_URL:
        return pool_url.strip()
    if looks_like_btc_address(wallet):
        return SOLO_POOL_URL
    return DEFAULT_POOL_URL


def stratum_user(wallet: str, worker: str) -> str:
    w = (wallet or DEFAULT_MINING_WALLET).strip()
    n = sanitize_worker(worker)
    return f"{w}.{n}"
