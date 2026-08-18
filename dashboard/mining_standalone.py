"""
Mining Start/Stop/Status with ZERO Redis and ZERO blocking on the request path.

Mounted on the FastAPI app before CommsLayer exists so the buttons always work
even if mesh/redis/boot is broken.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("aurora-dashboard.mining_standalone")

_lock = threading.Lock()
_miner = None
_running = False
_starting = False
_user_stopped = True  # wait for explicit Start
_last_error = ""
_hashrate_hs = 0.0
_wallet = ""
_pool = ""


class _NullComms:
    """Minimal stub so MiningEngine never needs Redis."""

    def __init__(self):
        self.node_id = os.getenv("AURORA_NODE_ID") or os.getenv("HOSTNAME") or "node"

    def set_state(self, *a, **k):
        return None

    def get_state(self, *a, **k):
        return None

    def publish(self, *a, **k):
        return None

    def publish_message(self, *a, **k):
        return None

    def publish_event(self, *a, **k):
        return None

    def publish_telemetry(self, *a, **k):
        return None

    def register_node(self, *a, **k):
        return None

    def heartbeat(self, *a, **k):
        return None

    def get_active_nodes(self, *a, **k):
        return []

    def get_workers(self, *a, **k):
        return []

    def ping(self):
        return False


def _fmt(hs: float, running: bool) -> str:
    if not running:
        return "idle"
    if hs <= 0:
        return "warming up…"
    if hs >= 1e12:
        return f"{hs/1e12:.3f} TH/s"
    if hs >= 1e9:
        return f"{hs/1e9:.3f} GH/s"
    if hs >= 1e6:
        return f"{hs/1e6:.2f} MH/s"
    if hs >= 1e3:
        return f"{hs/1e3:.2f} KH/s"
    return f"{hs:.0f} H/s"


def _snapshot() -> dict:
    running = _running and not _user_stopped
    if _starting and not _user_stopped:
        running = True
    hs = _hashrate_hs if running else 0.0
    return {
        "ok": True,
        "running": running,
        "starting": bool(_starting),
        "user_stopped": bool(_user_stopped),
        "backend": "cpu_stratum",
        "hashrate_hs": hs,
        "hashrate_display": _fmt(hs, running),
        "wallet": _wallet,
        "pool": _pool,
        "error": _last_error or "",
        "engine_built": True,
    }


def _ensure_miner():
    global _miner, _wallet, _pool
    if _miner is not None:
        return _miner
    from mods.mining_engine.defaults import DEFAULT_MINING_WALLET, DEFAULT_POOL_URL, DEFAULT_INTENSITY
    from mods.mining_engine.engine import MiningEngine

    _wallet = (os.getenv("MINING_WALLET") or DEFAULT_MINING_WALLET).strip()
    _pool = os.getenv("POOL_URL", DEFAULT_POOL_URL)
    null = _NullComms()
    _miner = MiningEngine(
        null,
        worker_id=null.node_id,
        worker_name=null.node_id,
        pool_url=_pool,
        wallet=_wallet,
        intensity=os.getenv("INTENSITY", DEFAULT_INTENSITY),
    )
    return _miner


def _bg_start():
    global _running, _starting, _last_error, _hashrate_hs
    try:
        eng = _ensure_miner()
        ok = eng.start()
        if not ok:
            try:
                _last_error = eng.status().get("error") or "pool connect failed"
            except Exception:
                _last_error = "pool connect failed"
            _running = False
        else:
            _running = True
            _last_error = ""
        # sample once
        try:
            st = eng.status()
            _hashrate_hs = float(st.get("hashrate_hs") or 0)
            if st.get("error"):
                _last_error = st.get("error") or _last_error
        except Exception:
            pass
    except Exception as e:
        _last_error = str(e)
        _running = False
        logger.exception("bg start")
    finally:
        _starting = False


def _bg_poll():
    """Update hashrate without blocking HTTP."""
    global _hashrate_hs, _running, _last_error
    while True:
        time.sleep(2)
        if _user_stopped or not _running:
            continue
        try:
            if _miner is None:
                continue
            st = _miner.status()
            _hashrate_hs = float(st.get("hashrate_hs") or 0)
            _running = bool(st.get("running"))
            if st.get("error"):
                _last_error = st.get("error") or ""
        except Exception as e:
            _last_error = str(e)


_poll_started = False


def install_mining_standalone(app: Any):
    global _poll_started

    @app.get("/mining/engine/status")
    def mining_status():
        return _snapshot()

    @app.post("/mining/engine/start")
    def mining_start():
        global _user_stopped, _starting, _running, _last_error
        with _lock:
            _user_stopped = False
            _last_error = ""
            if _starting:
                return _snapshot()
            if _running:
                return {**_snapshot(), "already": True}
            _starting = True
            _running = True  # optimistic so UI shows RUNNING immediately
        threading.Thread(target=_bg_start, name="mine-start", daemon=True).start()
        return {**_snapshot(), "ok": True}

    @app.post("/mining/engine/stop")
    def mining_stop():
        global _user_stopped, _starting, _running, _hashrate_hs, _last_error
        with _lock:
            _user_stopped = True
            _starting = False
            _running = False
            _hashrate_hs = 0.0
            _last_error = ""
        try:
            if _miner is not None:
                _miner.stop()
        except Exception as e:
            logger.warning(f"stop: {e}")
        return _snapshot()

    @app.get("/mining/ping")
    def mining_ping():
        return {"ok": True, "ts": time.time()}

    if not _poll_started:
        _poll_started = True
        threading.Thread(target=_bg_poll, name="mine-poll", daemon=True).start()

    logger.info("mining_standalone routes mounted (no redis)")
