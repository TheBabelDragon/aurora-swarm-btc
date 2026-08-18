"""Miner process backends — bfgminer primary; interface allows swaps."""

from __future__ import annotations

import logging
import os
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


class BfgminerBackend:
    """Spawn/manage host bfgminer; stream stdout for share/hashrate parse."""

    def __init__(self, cfg: MinerConfig):
        self.cfg = cfg
        self.proc: Optional[subprocess.Popen] = None

    def available(self) -> bool:
        return bool(shutil.which(self.cfg.binary) or os.path.isfile(self.cfg.binary))

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
            logger.error(f"miner binary not found: {self.cfg.binary}")
            return False
        cmd = self.build_cmd()
        logger.info(f"starting miner: {' '.join(cmd[:6])}… intensity={self.cfg.intensity}")
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            return True
        except Exception as e:
            logger.error(f"start failed: {e}")
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
