"""Mining Start/Stop/Status + official log. No Redis on the request path."""

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
_user = ""
_job_ready = False
_authorized = False
_shares = {"submitted": 0, "accepted": 0, "rejected": 0}
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


def _pull_official():
    global _job_ready, _authorized, _shares, _user, _pool
    try:
        inner = getattr(getattr(_miner, "backend", None), "_miner", None)
        backend = getattr(_miner, "backend", None)
        extra = {}
        if backend and hasattr(backend, "official_status"):
            extra = backend.official_status() or {}
        _authorized = bool(extra.get("authorized") or getattr(inner, "authorized", False))
        _job_ready = bool(extra.get("job_ready") or getattr(inner, "job_ready", False))
        _shares = {
            "submitted": int(extra.get("shares_submitted") or getattr(inner, "shares_submitted", 0) or 0),
            "accepted": int(extra.get("shares_accepted") or getattr(inner, "shares_accepted", 0) or 0),
            "rejected": int(extra.get("shares_rejected") or getattr(inner, "shares_rejected", 0) or 0),
        }
        if extra.get("username"):
            _user = extra["username"]
        if getattr(_miner, "cfg", None):
            _pool = getattr(_miner.cfg, "pool_url", _pool) or _pool
    except Exception:
        pass


def _snapshot() -> dict:
    running = (_running and not _user_stopped) or (_starting and not _user_stopped)
    hs = _hashrate_hs if running else 0.0
    from mods.mining_engine.mine_log import log_path

    return {
        "ok": True,
        "running": running,
        "starting": bool(_starting),
        "user_stopped": bool(_user_stopped),
        "backend": _backend,
        "hashrate_hs": hs,
        "hashrate_display": _fmt(hs, running),
        "wallet": _wallet,
        "user": _user or _wallet,
        "pool": _pool,
        "authorized": bool(_authorized),
        "job_ready": bool(_job_ready),
        "shares": dict(_shares),
        "error": _last_error or "",
        "log_path": str(log_path()),
        "offline": os.getenv("AURORA_MINE_OFFLINE", "0") in ("1", "true", "True"),
        "engine_built": True,
    }


def _ensure_miner():
    global _miner, _wallet, _pool, _backend, _user
    if _miner is not None:
        return _miner
    os.environ.setdefault("AURORA_MINER_BACKEND", "cpu")
    from mods.mining_engine.defaults import (
        DEFAULT_INTENSITY,
        DEFAULT_MINING_WALLET,
        resolve_pool_url,
        stratum_user,
    )
    from mods.mining_engine.engine import MiningEngine
    from mods.mining_engine.mine_log import mine_log

    _wallet = (os.getenv("MINING_WALLET") or DEFAULT_MINING_WALLET).strip()
    null = _NullComms()
    _user = stratum_user(_wallet, null.node_id)
    _pool = resolve_pool_url(_wallet, os.getenv("POOL_URL") or "")
    mine_log("info", f"engine build wallet={_wallet} user={_user} pool={_pool}")
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
    global _running, _starting, _last_error, _hashrate_hs
    try:
        eng = _ensure_miner()
        ok = eng.start()
        st = {}
        try:
            st = eng.status() or {}
        except Exception:
            st = {}
        _hashrate_hs = float(st.get("hashrate_hs") or 0)
        _pull_official()
        if not ok:
            _last_error = st.get("error") or _last_error or "pool connect failed"
            _running = False
        else:
            _running = True
            _last_error = st.get("error") or ""
    except Exception as e:
        _last_error = str(e)
        _running = False
        logger.exception("bg start")
    finally:
        _starting = False


def _bg_poll():
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
            _pull_official()
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

    @app.get("/mining/engine/log")
    def mining_log(lines: int = 80):
        from mods.mining_engine.mine_log import log_path, tail

        return {"ok": True, "path": str(log_path()), "lines": tail(lines)}

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
        global _user_stopped, _starting, _running, _hashrate_hs, _last_error, _job_ready, _authorized
        with _lock:
            _user_stopped = True
            _starting = False
            _running = False
            _hashrate_hs = 0.0
            _job_ready = False
            _authorized = False
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

    logger.info("mining_standalone official log routes mounted")
