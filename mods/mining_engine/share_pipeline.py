"""
Parse miner stdout → hashrate telemetry + progressive mining provenance.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora.mining.shares")

HASH_RE = re.compile(r"(\d+\.?\d*)\s*(H|KH|MH|GH|TH)/s", re.I)
MULT = {"H": 1.0, "KH": 1e3, "MH": 1e6, "GH": 1e9, "TH": 1e12}


def parse_hashrate_hs(line: str) -> Optional[float]:
    m = HASH_RE.search(line)
    if not m:
        return None
    unit = m.group(2).upper()
    mult = 1.0 if unit == "H" else MULT.get(unit, 1.0)
    return float(m.group(1)) * mult


def format_hashrate(hs: float) -> str:
    if hs >= 1e12:
        return f"{hs/1e12:.3f} TH/s"
    if hs >= 1e9:
        return f"{hs/1e9:.3f} GH/s"
    if hs >= 1e6:
        return f"{hs/1e6:.2f} MH/s"
    if hs >= 1e3:
        return f"{hs/1e3:.2f} KH/s"
    return f"{hs:.0f} H/s"


def parse_hashrate_ghs(line: str) -> Optional[float]:
    hs = parse_hashrate_hs(line)
    if hs is None:
        return None
    return hs / 1e9


def looks_accepted(line: str) -> bool:
    low = line.lower()
    return ("accepted" in low or "share submitted" in low) and "reject" not in low


def looks_rejected(line: str) -> bool:
    return "reject" in line.lower()


class SharePipeline:
    def __init__(
        self,
        comms: Any,
        *,
        worker_id: str,
        pool_id: str = "",
        facility_domain: str = "unknown",
        on_hashrate: Optional[Callable[[float], None]] = None,
    ):
        self.comms = comms
        self.worker_id = worker_id
        self.pool_id = pool_id
        self.facility_domain = facility_domain
        self.on_hashrate = on_hashrate
        self.shares_accepted = 0
        self.shares_rejected = 0
        self.last_hashrate_hs = 0.0
        self.last_hashrate_ghs = 0.0
        self.last_hashrate_display = "0 H/s"
        self._last_share_ts = 0.0

    def _epoch(self) -> int:
        return int(time.time()) // 3600

    def handle_line(self, line: str):
        hs = parse_hashrate_hs(line)
        if hs is not None and hs > 0:
            self.last_hashrate_hs = hs
            self.last_hashrate_ghs = hs / 1e9
            self.last_hashrate_display = format_hashrate(hs)
            if self.on_hashrate:
                try:
                    self.on_hashrate(self.last_hashrate_ghs)
                except Exception:
                    pass
            try:
                payload = {
                    "hashrate_hs": self.last_hashrate_hs,
                    "hashrate_ghs": self.last_hashrate_ghs,
                    "hashrate_display": self.last_hashrate_display,
                    "ts": time.time(),
                    "status": "mining",
                }
                self.comms.set_state(f"worker:{self.worker_id}:hashrate", payload, expire=120)
                # cluster totals used by legacy /status bus readers
                self.comms.set_state("cluster:total_hashrate_hs", self.last_hashrate_hs)
                self.comms.set_state("cluster:total_hashrate_ghs", self.last_hashrate_ghs)
                self.comms.set_state("cluster:total_hashrate_btc", self.last_hashrate_hs / 1e12)
                self.comms.publish_telemetry(payload)
            except Exception as e:
                logger.debug(f"hashrate publish: {e}")

        if looks_accepted(line):
            self.shares_accepted += 1
            self._last_share_ts = time.time()
            self._record_share(accepted=True)
            try:
                cur = self.comms.get_state("cluster:shares_accepted", 0) or 0
                self.comms.set_state("cluster:shares_accepted", int(cur) + 1)
            except Exception:
                pass

        if looks_rejected(line):
            self.shares_rejected += 1

    def _record_share(self, accepted: bool):
        try:
            from mods.mining_provenance.models import EvidenceLevel
            from mods.mining_provenance.service import MiningProvenance

            mp = MiningProvenance(self.comms)
            ev = mp.observe_share(
                worker_id=self.worker_id,
                epoch=self._epoch(),
                pool_id=self.pool_id,
                difficulty=0.0,
                facility_domain=self.facility_domain,
            )
            if accepted:
                mp.upgrade_evidence(ev.event_id, EvidenceLevel.POOL_ACCEPTED)
        except Exception as e:
            logger.debug(f"provenance share: {e}")

    def snapshot(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "hashrate_hs": self.last_hashrate_hs,
            "hashrate_ghs": self.last_hashrate_ghs,
            "hashrate_display": self.last_hashrate_display,
            "shares_accepted": self.shares_accepted,
            "shares_rejected": self.shares_rejected,
            "last_share_ts": self._last_share_ts,
        }
