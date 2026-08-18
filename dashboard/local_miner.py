"""Local miner — start never blocks the HTTP worker."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

from mods.mining_engine.defaults import (
    DEFAULT_INTENSITY,
    DEFAULT_MINING_WALLET,
    DEFAULT_POOL_URL,
)

logger = logging.getLogger("aurora-dashboard.local_miner")

_lock = threading.Lock()
_engine = None
_user_stopped = False
_start_in_progress = False
_last_error = ""


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
            # comms optional for hashing — avoid redis on hot path if possible
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
    """Kick off mining in a background thread — returns immediately."""
    global _user_stopped, _start_in_progress, _last_error
    with _lock:
        _user_stopped = False
        if _start_in_progress:
            return {
                "ok": True,
                "running": True,
                "hashrate_display": "warming up…",
                "hashrate_hs": 0.0,
                "backend": "cpu_stratum",
                "wallet": wallet_configured(),
                "pool": os.getenv("POOL_URL", DEFAULT_POOL_URL),
                "error": "",
                "starting": True,
            }
        _start_in_progress = True
        _last_error = ""

    eng = get_local_engine(comms)

    # Already running?
    try:
        st0 = eng.status()
        if st0.get("running") and not _user_stopped:
            with _lock:
                _start_in_progress = False
            return {
                "ok": True,
                "already": True,
                "running": True,
                "hashrate_display": _fmt(float(st0.get("hashrate_hs") or 0), True),
                "hashrate_hs": float(st0.get("hashrate_hs") or 0),
                "backend": st0.get("backend") or "cpu_stratum",
                "wallet": eng.cfg.wallet,
                "pool": eng.cfg.pool_url,
                "error": "",
            }
    except Exception:
        pass

    def _bg():
        global _start_in_progress, _last_error
        try:
            ok = eng.start()
            if not ok:
                err = ""
                try:
                    err = eng.status().get("error") or "start returned false"
                except Exception:
                    err = "start returned false"
                _last_error = err
                logger.warning(f"background start failed: {err}")
        except Exception as e:
            _last_error = str(e)
            logger.exception("background start")
        finally:
            with _lock:
                _start_in_progress = False

    threading.Thread(target=_bg, name="mine-start", daemon=True).start()
    return {
        "ok": True,
        "running": True,
        "starting": True,
        "hashrate_display": "warming up…",
        "hashrate_hs": 0.0,
        "backend": "cpu_stratum",
        "wallet": wallet_configured(),
        "pool": getattr(eng.cfg, "pool_url", DEFAULT_POOL_URL),
        "error": "",
    }


def stop_local(comms: Any) -> dict:
    global _user_stopped, _start_in_progress, _last_error
    with _lock:
        _user_stopped = True
        _start_in_progress = False
        _last_error = ""
    try:
        eng = get_local_engine(comms)
        eng.stop()
    except Exception as e:
        logger.warning(f"stop: {e}")
    return {
        "ok": True,
        "running": False,
        "hashrate_display": "idle",
        "hashrate_hs": 0.0,
        "user_stopped": True,
        "error": "",
    }


def local_status(comms: Any) -> dict:
    """Instant status — never waits on pool."""
    global _last_error
    try:
        eng = get_local_engine(comms)
        st = eng.status()
        hs = float(st.get("hashrate_hs") or 0)
        running = bool(st.get("running")) and not _user_stopped
        if _user_stopped:
            running = False
            hs = 0.0
        if _start_in_progress and not _user_stopped:
            running = True
        err = st.get("error") or _last_error or ""
        return {
            "ok": True,
            "engine_built": True,
            "backend": st.get("backend") or "cpu_stratum",
            "wallet": getattr(eng.cfg, "wallet", wallet_configured()),
            "pool": getattr(eng.cfg, "pool_url", DEFAULT_POOL_URL),
            "running": running,
            "starting": bool(_start_in_progress),
            "user_stopped": bool(_user_stopped),
            "hashrate_hs": hs if running else 0.0,
            "hashrate_display": _fmt(hs if running else 0.0, running),
            "error": err if not running else (err or ""),
        }
    except Exception as e:
        logger.exception("local_status")
        return {
            "ok": True,
            "engine_built": False,
            "running": bool(_start_in_progress) and not _user_stopped,
            "hashrate_hs": 0.0,
            "hashrate_display": "warming up…" if _start_in_progress else "idle",
            "error": str(e),
            "user_stopped": bool(_user_stopped),
        }
