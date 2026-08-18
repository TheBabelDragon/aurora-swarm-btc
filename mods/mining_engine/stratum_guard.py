"""
Additive safety wraps for StratumCpuMiner — does not replace the module.
Prevents stacked worker threads if start() is called while already running.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("aurora.mining.stratum_guard")
_patched = False


def apply_stratum_guards() -> bool:
    global _patched
    if _patched:
        return True
    try:
        from .stratum_cpu import StratumCpuMiner
    except Exception as e:
        logger.warning(f"stratum_guard import: {e}")
        return False

    if getattr(StratumCpuMiner, "_aurora_guarded", False):
        _patched = True
        return True

    _orig_start = StratumCpuMiner.start
    _orig_running = StratumCpuMiner.running

    def start(self) -> bool:
        try:
            workers = getattr(self, "_workers", None) or []
            alive = [w for w in workers if getattr(w, "is_alive", lambda: False)()]
            sock = getattr(self, "_sock", None)
            stop = getattr(self, "_stop", None)
            if alive and sock is not None and stop is not None and not stop.is_set():
                logger.info("stratum start skipped — already running (%s workers)", len(alive))
                return True
        except Exception:
            pass
        return _orig_start(self)

    def running(self) -> bool:
        try:
            base = _orig_running(self)
            if not base:
                return False
            workers = getattr(self, "_workers", None) or []
            if workers and not any(w.is_alive() for w in workers):
                return False
            return True
        except Exception:
            return _orig_running(self)

    StratumCpuMiner.start = start  # type: ignore
    StratumCpuMiner.running = running  # type: ignore
    StratumCpuMiner._aurora_guarded = True  # type: ignore
    _patched = True
    logger.info("stratum start/running guards applied")
    return True
