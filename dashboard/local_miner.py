"""
Dashboard-local MiningEngine singleton.

Always startable: bfgminer if present, else pure-Python stratum CPU.
Default wallet when MINING_WALLET unset.
"""

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
        wallet = wallet_configured()
        from mods.mining_engine.engine import MiningEngine

        _engine = MiningEngine(
            comms,
            worker_id=os.getenv("AURORA_NODE_ID", "dashboard"),
            worker_name=os.getenv("WORKER_NAME", os.getenv("AURORA_NODE_ID", "dashboard")),
            pool_url=os.getenv("POOL_URL", DEFAULT_POOL_URL),
            wallet=wallet,
            intensity=os.getenv("INTENSITY", DEFAULT_INTENSITY),
            gpus=int(os.getenv("GPUS_PER_POD", "1")),
            facility_domain=os.getenv("FACILITY_DOMAIN", "dashboard"),
            binary=os.getenv("BFGMINER_BIN", "bfgminer"),
        )
        return _engine


def start_local(comms: Any) -> dict:
    wallet = wallet_configured()
    eng = get_local_engine(comms)
    if eng is None:
        return {"ok": False, "error": "could not build MiningEngine"}
    ok = eng.start()
    return {
        "ok": ok,
        "mode": "local_engine",
        "backend": getattr(eng.backend, "kind", "unknown"),
        "wallet": wallet,
        "pool": eng.cfg.pool_url,
        "worker": eng.cfg.worker_name,
        "running": eng.backend.running(),
        "status": eng.status(),
        "note": (
            "using pure-Python CPU stratum (no bfgminer required)"
            if getattr(eng.backend, "kind", "") == "cpu_stratum"
            else "using bfgminer"
        ),
    }


def stop_local(comms: Any) -> dict:
    eng = get_local_engine(comms)
    if eng is None:
        return {"ok": True, "mode": "local_engine", "running": False, "note": "no engine"}
    eng.stop()
    return {
        "ok": True,
        "mode": "local_engine",
        "backend": getattr(eng.backend, "kind", "unknown"),
        "running": False,
        "status": eng.status(),
    }


def local_status(comms: Any) -> dict:
    wallet = wallet_configured()
    eng = None
    with _lock:
        eng = _engine
    if eng is None:
        from mods.mining_engine.backends import MinerConfig, select_backend

        cfg = MinerConfig(
            pool_url=os.getenv("POOL_URL", DEFAULT_POOL_URL),
            wallet=wallet,
            worker_name=os.getenv("WORKER_NAME", "dashboard"),
            binary=os.getenv("BFGMINER_BIN", "bfgminer"),
        )
        be = select_backend(cfg)
        return {
            "wallet": wallet,
            "pool": cfg.pool_url,
            "backend": getattr(be, "kind", "unknown"),
            "backend_available": True,  # CPU always; bfgminer optional
            "running": False,
            "engine_built": False,
        }
    st = eng.status()
    return {
        "wallet": wallet,
        "pool": eng.cfg.pool_url,
        "backend": getattr(eng.backend, "kind", "unknown"),
        "backend_available": True,
        "running": eng.backend.running(),
        "engine_built": True,
        **st,
    }
