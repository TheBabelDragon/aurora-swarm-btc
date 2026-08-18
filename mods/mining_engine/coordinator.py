"""Fleet mining coordinator — shared Redis view of mining posture."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger("aurora.mining.coord")

FLEET_KEY = "mining:fleet"


class MiningCoordinator:
    def __init__(self, comms: Any):
        self.comms = comms

    def publish_worker(self, worker_id: str, snapshot: Dict[str, Any]):
        body = {
            **snapshot,
            "worker_id": worker_id,
            "ts": time.time(),
        }
        try:
            self.comms.set_state(f"mining:worker:{worker_id}", body, expire=180)
            # index
            idx = self.comms.get_state(FLEET_KEY) or {"workers": []}
            if not isinstance(idx, dict):
                idx = {"workers": []}
            workers = list(idx.get("workers") or [])
            if worker_id not in workers:
                workers.append(worker_id)
            idx["workers"] = workers[-64:]
            idx["updated"] = time.time()
            self.comms.set_state(FLEET_KEY, idx, expire=0)
        except Exception as e:
            logger.debug(f"publish_worker: {e}")

    def fleet_view(self) -> Dict[str, Any]:
        workers: List[Dict[str, Any]] = []
        try:
            idx = self.comms.get_state(FLEET_KEY) or {}
            ids = list((idx or {}).get("workers") or [])
            for wid in ids:
                raw = self.comms.get_state(f"mining:worker:{wid}")
                if isinstance(raw, dict):
                    workers.append(raw)
        except Exception as e:
            logger.debug(f"fleet_view: {e}")
        total_gh = sum(float(w.get("hashrate_ghs") or 0) for w in workers)
        return {
            "workers": workers,
            "worker_count": len(workers),
            "total_hashrate_ghs": round(total_gh, 4),
            "ts": time.time(),
        }
