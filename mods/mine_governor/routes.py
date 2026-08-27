"""HTTP face for the governor — status + local command."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import Form

from .apply import apply_command
from .history import last, recent

logger = logging.getLogger("aurora.mine_governor.routes")


def install_governor_routes(app: Any, *, get_comms: Optional[Callable[[], Any]] = None):
    @app.get("/mining/governor")
    def governor_status():
        comms = get_comms() if get_comms else None
        nid = getattr(comms, "node_id", None) if comms else None
        try:
            from dashboard.mining_standalone import _snapshot

            snap = _snapshot()
        except Exception:
            snap = {}
        return {
            "ok": True,
            "mod": "mine_governor",
            "version": "0.2.0",
            "node_id": nid,
            "mining": {
                "running": snap.get("running"),
                "hashrate_display": snap.get("hashrate_display"),
                "cpu_threads": snap.get("cpu_threads"),
                "authorized": snap.get("authorized"),
            },
            "last": last(),
            "recent": recent(12),
        }

    @app.post("/mining/governor/command")
    def governor_command(
        action: str = Form(...),
        factor: Optional[float] = Form(None),
        threads: Optional[int] = Form(None),
    ):
        out = apply_command(action, factor=factor, threads=threads)
        from .history import record

        record(action, out)
        return {"ok": bool(out.get("ok")), "result": out}

    logger.info("mine_governor routes mounted")
