"""Miner backends — CPU path is the official hasher."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Optional, TextIO

from .defaults import resolve_pool_url, stratum_user
from .mine_log import mine_log

logger = logging.getLogger("aurora.mining.backend")


@dataclass
class MinerConfig:
    pool_url: str
    wallet: str
    worker_name: str
    intensity: str = "19"
    gpus: int = 1
    binary: str = "bfgminer"
    cpu_threads: int = 0
    coin: str = "BTC"
    comms: Any = field(default=None, repr=False)


def _default_workers() -> int:
    cpus = os.cpu_count() or 2
    explicit = int(os.getenv("AURORA_CPU_THREADS", "0") or 0)
    if explicit > 0:
        return explicit
    # Official default: one hasher per core (oversubscribe via env if wanted)
    mult = int(os.getenv("AURORA_CPU_OVERSUBSCRIBE", "1") or 1)
    mult = max(1, min(mult, 8))
    return max(1, cpus * mult)


class BfgminerBackend:
    def __init__(self, cfg: MinerConfig):
        self.cfg = cfg
        self.proc: Optional[subprocess.Popen] = None
        self.kind = "bfgminer"
        self._last_hs = 0.0

    def available(self) -> bool:
        path = self.cfg.binary
        return bool(shutil.which(path) or (os.path.isfile(path) and os.access(path, os.X_OK)))

    def start(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        if not self.available():
            return False
        user = stratum_user(self.cfg.wallet, self.cfg.worker_name)
        cmd = [
            self.cfg.binary, "-o", resolve_pool_url(self.cfg.wallet, self.cfg.pool_url),
            "-u", user, "-p", "x", "--no-getwork", "-S", "opencl:auto",
            "--intensity", str(self.cfg.intensity), "--quiet",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            mine_log("info", f"bfgminer start user={user}")
            return True
        except Exception as e:
            logger.error("bfgminer start: %s", e)
            mine_log("error", f"bfgminer start {e}")
            return False

    def stop(self, timeout: float = 10.0):
        if not self.proc or self.proc.poll() is not None:
            self.proc = None
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except Exception:
            self.proc.kill()
        self.proc = None

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stdout(self) -> Optional[TextIO]:
        return self.proc.stdout if self.proc else None

    def set_intensity(self, intensity: str):
        self.cfg.intensity = str(intensity)

    def get_hashrate_hs(self) -> float:
        return float(self._last_hs)


class _QueueReader:
    def __init__(self, q: queue.Queue):
        self.q = q

    def readline(self):
        try:
            return self.q.get(timeout=0.3)
        except queue.Empty:
            return ""


class CpuStratumBackend:
    def __init__(self, cfg: MinerConfig):
        self.cfg = cfg
        self.kind = "cpu_stratum"
        self._miner = None
        self._q: queue.Queue = queue.Queue(maxsize=500)
        self._reader = _QueueReader(self._q)

    def available(self) -> bool:
        return True

    def start(self) -> bool:
        if self._miner and self._miner.running():
            return True
        from .stratum_cpu import StratumCpuMiner

        threads = self.cfg.cpu_threads if self.cfg.cpu_threads > 0 else _default_workers()
        pool = resolve_pool_url(self.cfg.wallet, self.cfg.pool_url)
        user = stratum_user(self.cfg.wallet, self.cfg.worker_name)
        self.cfg.pool_url = pool
        self._miner = StratumCpuMiner(
            pool_url=pool,
            username=user,
            password="x",
            threads=threads,
            line_queue=self._q,
            comms=self.cfg.comms,
            coin=self.cfg.coin or "BTC",
        )
        ok = self._miner.start()
        mine_log("info", f"cpu start ok={ok} user={user} pool={pool} workers={threads}")
        return ok

    def stop(self, timeout: float = 10.0):
        if self._miner:
            self._miner.stop()
        self._miner = None
        mine_log("info", "cpu miner stopped")

    def running(self) -> bool:
        return bool(self._miner and self._miner.running())

    def stdout(self):
        return self._reader

    def set_intensity(self, intensity: str):
        self.cfg.intensity = str(intensity)

    def get_hashrate_hs(self) -> float:
        if self._miner:
            return float(self._miner.get_hashrate_hs())
        return 0.0

    def last_error(self) -> str:
        if self._miner:
            return getattr(self._miner, "last_error", "") or ""
        return ""

    def official_status(self) -> dict:
        m = self._miner
        if not m:
            return {}
        return {
            "authorized": bool(getattr(m, "authorized", False)),
            "job_ready": bool(getattr(m, "job_ready", False)),
            "shares_submitted": int(getattr(m, "shares_submitted", 0) or 0),
            "shares_accepted": int(getattr(m, "shares_accepted", 0) or 0),
            "shares_rejected": int(getattr(m, "shares_rejected", 0) or 0),
            "username": getattr(m, "username", ""),
            "difficulty": getattr(m, "_difficulty", None),
        }


def select_backend(cfg: MinerConfig):
    prefer = (os.getenv("AURORA_MINER_BACKEND") or "cpu").lower()
    if prefer == "bfgminer":
        return BfgminerBackend(cfg)
    return CpuStratumBackend(cfg)
