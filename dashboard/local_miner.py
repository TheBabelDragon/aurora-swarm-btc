"""Dashboard-local MiningEngine — always startable CPU path."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from mods.mining_engine.defaults import (
    DEFAULT_INTENSITY,
    DEFAULT_MINING_WALLET,
    DEFAULT_POOL_URL,
)

logger = logging.getLogger("aurora-dashboard.local_miner")

_lock = threading.Lock()
_engine = None


def wallet_configured() -> str:
    return (os.getenv("MINING_WALLET") or DEFAULT_MINING_WALLET).strip()


def get_local_engine(comms: Any):
    global _engine
    with _lock:
        if _engine is not None:
            return _engine
        from mods.mining_engine.engine import MiningEngine

        _engine = MiningEngine(
            comms,
            worker_id=os.getenv("AURORA_NODE_ID", "dashboard"),
            worker_name=os.getenv("WORKER_NAME", os.getenv("AURORA_NODE_ID", "dashboard")),
            pool_url=os.getenv("POOL_URL", DEFAULT_POOL_URL),
            wallet=wallet_configured(),
            intensity=os.getenv("INTENSITY", DEFAULT_INTENSITY),
            gpus=int(os.getenv("GPUS_PER_POD", "1")),
            facility_domain=os.getenv("FACILITY_DOMAIN", "dashboard"),
            binary=os.getenv("BFGMINER_BIN", "bfgminer"),
        )
        return _engine


def start_local(comms: Any) -> dict:
    wallet = wallet_configured()
    eng = get_local_engine(comms)
    ok = eng.start()
    st = eng.status()
    return {
        "ok": ok,
        "mode": "local_engine",
        "backend": st.get("backend"),
        "wallet": wallet,
        "pool": eng.cfg.pool_url,
        "worker": eng.cfg.worker_name,
        "running": st.get("running"),
        "hashrate_display": st.get("hashrate_display"),
        "hashrate_hs": st.get("hashrate_hs"),
        "error": st.get("error"),
        "status": st,
    }


def stop_local(comms: Any) -> dict:
    eng = get_local_engine(comms)
    eng.stop()
    st = eng.status()
    return {"ok": True, "running": False, "status": st, "backend": st.get("backend")}


def local_status(comms: Any) -> dict:
    wallet = wallet_configured()
    eng = None
    with _lock:
        eng = _engine
    if eng is None:
        return {
            "wallet": wallet,
            "pool": os.getenv("POOL_URL", DEFAULT_POOL_URL),
            "backend": "cpu_stratum",
            "backend_available": True,
            "running": False,
            "engine_built": False,
            "hashrate_hs": 0.0,
            "hashrate_ghs": 0.0,
            "hashrate_display": "0 H/s",
        }
    st = eng.status()
    return {
        "wallet": wallet,
        "pool": eng.cfg.pool_url,
        "backend": st.get("backend"),
        "backend_available": True,
        "running": bool(st.get("running")),
        "engine_built": True,
        "hashrate_hs": st.get("hashrate_hs") or 0,
        "hashrate_ghs": st.get("hashrate_ghs") or 0,
        "hashrate_display": st.get("hashrate_display") or "0 H/s",
        "error": st.get("error") or "",
        **st,
    }
