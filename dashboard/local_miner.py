"""
Dashboard-local MiningEngine singleton.

Uses DEFAULT_MINING_WALLET when MINING_WALLET env is unset.
Pool auth is wallet.worker → payouts to that address.
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
    if not eng.backend.available():
        return {
            "ok": False,
            "error": "bfgminer not found on this host/container — install or mount binary",
            "wallet": wallet,
            "hint": "Arch: install bfgminer; set BFGMINER_PATH for compose mount",
        }
    ok = eng.start()
    return {
        "ok": ok,
        "mode": "local_engine",
        "wallet": wallet,
        "pool": eng.cfg.pool_url,
        "worker": eng.cfg.worker_name,
        "running": eng.backend.running(),
        "status": eng.status(),
    }


def stop_local(comms: Any) -> dict:
    eng = get_local_engine(comms)
    if eng is None:
        return {"ok": True, "mode": "local_engine", "running": False, "note": "no engine"}
    eng.stop()
    return {"ok": True, "mode": "local_engine", "running": False, "status": eng.status()}


def local_status(comms: Any) -> dict:
    wallet = wallet_configured()
    eng = None
    with _lock:
        eng = _engine
    if eng is None:
        from mods.mining_engine.backends import BfgminerBackend, MinerConfig

        cfg = MinerConfig(
            pool_url=os.getenv("POOL_URL", DEFAULT_POOL_URL),
            wallet=wallet,
            worker_name=os.getenv("WORKER_NAME", "dashboard"),
            binary=os.getenv("BFGMINER_BIN", "bfgminer"),
        )
        return {
            "wallet": wallet,
            "pool": cfg.pool_url,
            "backend_available": BfgminerBackend(cfg).available(),
            "running": False,
            "engine_built": False,
        }
    st = eng.status()
    return {
        "wallet": wallet,
        "pool": eng.cfg.pool_url,
        "backend_available": eng.backend.available(),
        "running": eng.backend.running(),
        "engine_built": True,
        **st,
    }
