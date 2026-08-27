"""Apply a planned command to mining_standalone."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from .control import plan

logger = logging.getLogger("aurora.mine_governor")


def _cpus() -> int:
    return int(os.cpu_count() or 2)


def _current_threads() -> int:
    return int(os.getenv("AURORA_CPU_THREADS", "0") or 0) or _cpus()


def apply_command(action: str, **kwargs) -> Dict[str, Any]:
    p = plan(
        action,
        current_threads=_current_threads(),
        cpus=_cpus(),
        factor=kwargs.get("factor"),
        threads=kwargs.get("threads") or kwargs.get("intensity"),
    )
    if not p.get("ok"):
        return p
    how = p.get("apply")
    try:
        from dashboard import mining_standalone as ms
    except Exception as e:
        p["applied"] = False
        p["error"] = f"standalone unavailable: {e}"
        return p

    if how == "stop":
        try:
            ms.request_stop(reason=f"governor:{action}")
            p["applied"] = True
        except Exception as e:
            p["applied"] = False
            p["error"] = str(e)
    elif how == "start":
        try:
            ms.request_start(reason=f"governor:{action}")
            p["applied"] = True
        except Exception as e:
            p["applied"] = False
            p["error"] = str(e)
    elif how == "restart":
        try:
            ms.request_stop(reason=f"governor:{action}")
            ms.request_start(reason=f"governor:{action}")
            p["applied"] = True
        except Exception as e:
            p["applied"] = False
            p["error"] = str(e)
    elif how == "threads":
        n = int(p["threads"])
        os.environ["AURORA_CPU_THREADS"] = str(n)
        try:
            ms.request_stop(reason=f"governor:threads={n}")
            # force engine rebuild with new thread count
            if hasattr(ms, "rebuild_engine"):
                ms.rebuild_engine()
            ms.request_start(reason=f"governor:threads={n}")
            p["applied"] = True
        except Exception as e:
            p["applied"] = False
            p["error"] = str(e)
    else:
        p["applied"] = False
        p["snapshot"] = getattr(ms, "_snapshot", lambda: {})()
    return p
