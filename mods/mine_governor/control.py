"""Pure command map. Safe to unit-test without Redis or the hasher."""

from __future__ import annotations

from typing import Any, Dict, Optional

ACTIONS = {
    "pause",
    "stop",
    "resume",
    "start",
    "restart_miner",
    "restart",
    "adjust_intensity",
    "intensity",
    "threads",
    "set_threads",
    "status",
}


def normalize(action: str) -> str:
    a = (action or "").strip().lower()
    aliases = {
        "restart_miner": "restart",
        "set_threads": "threads",
        "adjust_intensity": "intensity",
    }
    return aliases.get(a, a)


def scale_threads(current: int, factor: Optional[float], explicit: Optional[int], cpus: int) -> int:
    n = int(current or cpus or 1)
    if explicit is not None:
        n = int(explicit)
    elif factor is not None:
        n = max(1, int(round(n * float(factor))))
    return max(1, min(int(cpus or n), n))


def plan(action: str, *, current_threads: int = 1, cpus: int = 1, factor: Any = None, threads: Any = None) -> Dict[str, Any]:
    """What this node should do. Does not touch the hasher."""
    act = normalize(action)
    if act not in {normalize(x) for x in ACTIONS} and act not in ACTIONS:
        return {"ok": False, "action": act, "error": "unknown_action"}
    out: Dict[str, Any] = {"ok": True, "action": act}
    if act in ("pause", "stop"):
        out["apply"] = "stop"
    elif act in ("resume", "start"):
        out["apply"] = "start"
    elif act == "restart":
        out["apply"] = "restart"
    elif act in ("intensity", "threads"):
        exp = int(threads) if threads not in (None, "") else None
        fac = float(factor) if factor not in (None, "") else None
        out["apply"] = "threads"
        out["threads"] = scale_threads(current_threads, fac, exp, cpus)
    else:
        out["apply"] = "status"
    return out
