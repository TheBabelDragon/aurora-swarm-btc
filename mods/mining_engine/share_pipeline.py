"""
Parse miner stdout → hashrate telemetry + progressive mining provenance.

Accepted shares become OBSERVED_SHARE events; optional pool-accept line
upgrades evidence without pretending Bitcoin encodes hardware id.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("aurora.mining.shares")

HASH_RE = re.compile(r"(\d+\.?\d*)\s*(KH|MH|GH|TH)/s", re.I)
MULT = {"KH": 1e3, "MH": 1e6, "GH": 1e9, "TH": 1e12}


def parse_hashrate_ghs(line: str) -> Optional[float]:
    m = HASH_RE.search(line)
    if not m:
        return None
    return float(m.group(1)) * MULT.get(m.group(2).upper(), 1.0) / 1e9


def looks_accepted(line: str) -> bool:
    low = line.lower()
    return "accepted" in low and "reject" not in low


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
        self.last_hashrate_ghs = 0.0
        self._last_share_ts = 0.0

    def _epoch(self) -> int:
        return int(time.time()) // 3600

    def handle_line(self, line: str):
        gh = parse_hashrate_ghs(line)
        if gh is not None and gh > 0:
            self.last_hashrate_ghs = round(gh, 4)
            if self.on_hashrate:
                try:
                    self.on_hashrate(self.last_hashrate_ghs)
                except Exception:
                    pass
            try:
                self.comms.set_state(
                    f"worker:{self.worker_id}:hashrate",
                    {
                        "hashrate_ghs": self.last_hashrate_ghs,
                        "ts": time.time(),
                        "status": "mining",
                    },
                    expire=120,
                )
                self.comms.publish_telemetry(
                    {"hashrate_ghs": self.last_hashrate_ghs, "status": "mining"}
                )
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
            "hashrate_ghs": self.last_hashrate_ghs,
            "shares_accepted": self.shares_accepted,
            "shares_rejected": self.shares_rejected,
            "last_share_ts": self._last_share_ts,
        }
