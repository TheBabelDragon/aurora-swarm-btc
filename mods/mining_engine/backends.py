"""Miner backends — bfgminer when present, else pure-Python stratum CPU."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional, TextIO

logger = logging.getLogger("aurora.mining.backend")


@dataclass
class MinerConfig:
    pool_url: str
    wallet: str
    worker_name: str
    intensity: str = "19"
    gpus: int = 1
    binary: str = "bfgminer"
    cpu_threads: int = 0  # 0 = auto


class BfgminerBackend:
    def __init__(self, cfg: MinerConfig):
        self.cfg = cfg
        self.proc: Optional[subprocess.Popen] = None
        self.kind = "bfgminer"

    def available(self) -> bool:
        path = self.cfg.binary
        return bool(shutil.which(path) or (os.path.isfile(path) and os.access(path, os.X_OK)))

    def build_cmd(self) -> List[str]:
        cmd = [
            self.cfg.binary,
            "-o",
            self.cfg.pool_url,
            "-u",
            f"{self.cfg.wallet}.{self.cfg.worker_name}",
            "-p",
            "x",
            "--no-getwork",
            "-S",
            "opencl:auto",
            "--intensity",
            str(self.cfg.intensity),
            "--api-listen",
            "--quiet",
        ]
        if self.cfg.gpus > 1:
            cmd.extend(["--set", f"gpu_count={self.cfg.gpus}"])
        return cmd

    def start(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        if not self.available():
            return False
        try:
            self.proc = subprocess.Popen(
                self.build_cmd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            return True
        except Exception as e:
            logger.error(f"bfgminer start failed: {e}")
            self.proc = None
            return False

    def stop(self, timeout: float = 10.0):
        if not self.proc or self.proc.poll() is not None:
            self.proc = None
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def stdout(self) -> Optional[TextIO]:
        return self.proc.stdout if self.proc else None

    def set_intensity(self, intensity: str):
        self.cfg.intensity = str(intensity)


class _QueueReader:
    """File-like readline() over a queue.Queue of text lines."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def readline(self):
        try:
            return self.q.get(timeout=0.5)
        except queue.Empty:
            return ""


class CpuStratumBackend:
    """Always available — pure Python stratum + CPU SHA256d."""

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

        threads = self.cfg.cpu_threads
        if threads <= 0:
            threads = max(1, min(4, (os.cpu_count() or 2)))
        user = f"{self.cfg.wallet}.{self.cfg.worker_name}"
        self._miner = StratumCpuMiner(
            pool_url=self.cfg.pool_url,
            username=user,
            password="x",
            threads=threads,
            line_queue=self._q,
        )
        ok = self._miner.start()
        if ok:
            logger.info(f"CPU stratum backend started user={user[:20]}… threads={threads}")
        return ok

    def stop(self, timeout: float = 10.0):
        if self._miner:
            self._miner.stop()
        self._miner = None

    def running(self) -> bool:
        return bool(self._miner and self._miner.running())

    def stdout(self):
        return self._reader

    def set_intensity(self, intensity: str):
        # Map intensity 14–20 → thread count nudge
        self.cfg.intensity = str(intensity)
        try:
            i = int(float(intensity))
            self.cfg.cpu_threads = max(1, min(16, i - 12))
        except Exception:
            pass


def select_backend(cfg: MinerConfig):
    """Prefer bfgminer; always fall back to CPU stratum."""
    prefer = (os.getenv("AURORA_MINER_BACKEND") or "auto").lower()
    if prefer == "cpu":
        return CpuStratumBackend(cfg)
    if prefer == "bfgminer":
        return BfgminerBackend(cfg)
    bfg = BfgminerBackend(cfg)
    if bfg.available():
        logger.info("backend: bfgminer")
        return bfg
    logger.info("backend: cpu_stratum (bfgminer not found)")
    return CpuStratumBackend(cfg)
