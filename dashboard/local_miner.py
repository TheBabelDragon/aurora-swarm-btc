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


def _fmt(hs: float, running: bool) -> str:
    if running and hs <= 0:
        return "warming up…"
    if not running and hs <= 0:
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
    return "measuring…" if running else "idle"


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


def start_local(comms: Any) -> dict:
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
        "error": st.get("error"),
        "status": st,
    }


def stop_local(comms: Any) -> dict:
    eng = get_local_engine(comms)
    eng.stop()
    st = eng.status()
    return {"ok": True, "running": False, "status": st, "backend": st.get("backend"), "hashrate_display": "idle"}


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
            "hashrate_display": "idle",
            "error": "",
        }
    st = eng.status()
    hs = float(st.get("hashrate_hs") or 0)
    running = bool(st.get("running"))
    # publish for mesh
    try:
        comms.set_state(
            f"worker:{comms.node_id}:hashrate",
            {
                "hashrate_hs": hs,
                "hashrate_display": _fmt(hs, running),
                "running": running,
                "backend": st.get("backend"),
            },
            expire=90,
        )
    except Exception:
        pass
    return {
        "wallet": wallet,
        "pool": eng.cfg.pool_url,
        "backend": st.get("backend") or "cpu_stratum",
        "backend_available": True,
        "running": running,
        "engine_built": True,
        "hashrate_hs": hs,
        "hashrate_ghs": hs / 1e9,
        "hashrate_display": _fmt(hs, running),
        "error": st.get("error") or "",
        **{k: v for k, v in st.items() if k not in ("hashrate_display",)},
    }
