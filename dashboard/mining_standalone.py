"""
Mining Start/Stop/Status with ZERO Redis and ZERO blocking on the request path.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("aurora-dashboard.mining_standalone")

_lock = threading.Lock()
_miner = None
_running = False
_starting = False
_user_stopped = True
_last_error = ""
_hashrate_hs = 0.0
_wallet = ""
_pool = ""
_job_ready = False
_backend = "cpu_stratum"


class _NullComms:
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
    running = (_running and not _user_stopped) or (_starting and not _user_stopped)
    hs = _hashrate_hs if running else 0.0
    return {
        "ok": True,
        "running": running,
        "starting": bool(_starting),
        "user_stopped": bool(_user_stopped),
        "backend": _backend,
        "hashrate_hs": hs,
        "hashrate_display": _fmt(hs, running),
        "wallet": _wallet,
        "pool": _pool,
        "error": _last_error or "",
        "job_ready": bool(_job_ready),
        "offline": os.getenv("AURORA_MINE_OFFLINE", "0") in ("1", "true", "True"),
        "engine_built": True,
    }


def _ensure_miner():
    global _miner, _wallet, _pool, _backend
    if _miner is not None:
        return _miner
    os.environ.setdefault("AURORA_MINER_BACKEND", "cpu")
    from mods.mining_engine.defaults import DEFAULT_INTENSITY, DEFAULT_MINING_WALLET, DEFAULT_POOL_URL
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
        cpu_threads=int(os.getenv("AURORA_CPU_THREADS", "0") or 0),
    )
    _backend = getattr(getattr(_miner, "backend", None), "kind", "cpu_stratum")
    return _miner


def _bg_start():
    global _running, _starting, _last_error, _hashrate_hs, _job_ready
    try:
        eng = _ensure_miner()
        ok = eng.start()
        st = {}
        try:
            st = eng.status() or {}
        except Exception:
            st = {}
        _hashrate_hs = float(st.get("hashrate_hs") or 0)
        _job_ready = bool(getattr(getattr(eng, "backend", None), "_miner", None) and getattr(eng.backend._miner, "job_ready", False))
        if not ok:
            _last_error = st.get("error") or _last_error or "pool connect failed — set POOL_URL or AURORA_MINE_OFFLINE=1"
            _running = False
        else:
            _running = True
            if st.get("error"):
                _last_error = st.get("error")
            else:
                _last_error = ""
    except Exception as e:
        _last_error = str(e)
        _running = False
        logger.exception("bg start")
    finally:
        _starting = False


def _bg_poll():
    global _hashrate_hs, _running, _last_error, _job_ready
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
            inner = getattr(getattr(_miner, "backend", None), "_miner", None)
            _job_ready = bool(getattr(inner, "job_ready", False) or getattr(inner, "offline", False))
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
            _running = True
        threading.Thread(target=_bg_start, name="mine-start", daemon=True).start()
        return {**_snapshot(), "ok": True}

    @app.post("/mining/engine/stop")
    def mining_stop():
        global _user_stopped, _starting, _running, _hashrate_hs, _last_error, _job_ready
        with _lock:
            _user_stopped = True
            _starting = False
            _running = False
            _hashrate_hs = 0.0
            _job_ready = False
            _last_error = ""
        try:
            if _miner is not None:
                _miner.stop()
        except Exception as e:
            logger.warning("stop: %s", e)
        return _snapshot()

    @app.get("/mining/ping")
    def mining_ping():
        return {"ok": True, "ts": time.time()}

    if not _poll_started:
        _poll_started = True
        threading.Thread(target=_bg_poll, name="mine-poll", daemon=True).start()

    logger.info("mining_standalone routes mounted (cpu default, no redis)")
