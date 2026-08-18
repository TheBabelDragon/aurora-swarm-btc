"""Dashboard-local MiningEngine — single source of truth for Start/Stop."""

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
# When user hits Stop, stay stopped until they hit Start (no silent restart)
_user_stopped = False


def _fmt(hs: float, running: bool) -> str:
    if running and hs <= 0:
        return "warming up…"
    if not running:
        return "idle"
    if hs >= 1e12:
        return f"{hs/1e12:.3f} TH/s"
    if hs >= 1e9:
        return f"{hs/1e9:.3f} GH/s"
    if hs >= 1e6:
        return f"{hs/1e6:.2f} MH/s"
    if hs >= 1e3:
        return f"{hs/1e3:.2f} KH/s"
    if hs > 0:
        return f"{hs:.0f} H/s"
    return "warming up…"


def wallet_configured() -> str:
    return (os.getenv("MINING_WALLET") or DEFAULT_MINING_WALLET).strip()


def is_user_stopped() -> bool:
    return bool(_user_stopped)


def get_local_engine(comms: Any):
    global _engine
    with _lock:
        if _engine is not None:
            return _engine
        from mods.mining_engine.engine import MiningEngine

        _engine = MiningEngine(
            comms,
            worker_id=os.getenv("AURORA_NODE_ID") or getattr(comms, "node_id", "dashboard"),
            worker_name=os.getenv("WORKER_NAME") or getattr(comms, "node_id", "dashboard"),
            pool_url=os.getenv("POOL_URL", DEFAULT_POOL_URL),
            wallet=wallet_configured(),
            intensity=os.getenv("INTENSITY", DEFAULT_INTENSITY),
            gpus=int(os.getenv("GPUS_PER_POD", "1")),
            facility_domain=os.getenv("FACILITY_DOMAIN", "dashboard"),
            binary=os.getenv("BFGMINER_BIN", "bfgminer"),
        )
        return _engine


def _publish_stopped(comms: Any, eng: Any):
    """Force Redis + status readers to see stopped — no stale RUNNING."""
    try:
        nid = getattr(comms, "node_id", "dashboard")
        payload = {
            "hashrate_hs": 0.0,
            "hashrate_display": "idle",
            "running": False,
            "status": "stopped",
            "backend": getattr(getattr(eng, "backend", None), "kind", "cpu_stratum"),
        }
        comms.set_state(f"worker:{nid}:hashrate", payload, expire=120)
        # do not wipe cluster total — other nodes may still mine
    except Exception as e:
        logger.debug(f"publish stopped: {e}")


def start_local(comms: Any) -> dict:
    global _user_stopped
    with _lock:
        _user_stopped = False
    wallet = wallet_configured()
    eng = get_local_engine(comms)
    ok = eng.start()
    st = eng.status()
    hs = float(st.get("hashrate_hs") or 0)
    running = bool(st.get("running"))
    return {
        "ok": ok,
        "mode": "local_engine",
        "backend": st.get("backend"),
        "wallet": wallet,
        "pool": eng.cfg.pool_url,
        "worker": eng.cfg.worker_name,
        "running": running,
        "hashrate_display": _fmt(hs, running),
        "hashrate_hs": hs,
        "error": st.get("error") or "",
        "user_stopped": False,
        "status": st,
    }


def stop_local(comms: Any) -> dict:
    global _user_stopped
    with _lock:
        _user_stopped = True
    eng = get_local_engine(comms)
    eng.stop()
    _publish_stopped(comms, eng)
    st = eng.status()
    # Force running false even if backend lag
    return {
        "ok": True,
        "mode": "local_engine",
        "backend": st.get("backend"),
        "running": False,
        "hashrate_display": "idle",
        "hashrate_hs": 0.0,
        "error": st.get("error") or "",
        "user_stopped": True,
        "status": {**st, "running": False, "hashrate_hs": 0.0, "hashrate_display": "idle"},
    }


def local_status(comms: Any) -> dict:
    """Authoritative local mining status — used by every panel."""
    eng = get_local_engine(comms)
    st = eng.status()
    hs = float(st.get("hashrate_hs") or 0)
    running = bool(st.get("running")) and not _user_stopped
    if _user_stopped:
        running = False
        hs = 0.0
    return {
        "ok": True,
        "engine_built": True,
        "backend": st.get("backend") or "cpu_stratum",
        "wallet": eng.cfg.wallet,
        "pool": eng.cfg.pool_url,
        "running": running,
        "user_stopped": bool(_user_stopped),
        "hashrate_hs": hs if running else 0.0,
        "hashrate_display": _fmt(hs if running else 0.0, running),
        "error": st.get("error") or "",
        "status": st,
    }
