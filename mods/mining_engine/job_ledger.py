"""
Job ledger — checksum + score every mining.notify (they yearn for interesting work).

Not financial advice; just swarm memory of what the pool asked us to hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aurora.mining.jobs")

LEDGER_KEY = "mining:job_ledger"
MAX_ENTRIES = 200


def checksum_job(params: Any) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def score_job(params: Any) -> float:
    """
    Lightweight 'interestingness' score — entropy proxy from job bytes.
    Higher = more varied merkle/prevhash material (fun metric, not profit).
    """
    raw = json.dumps(params, sort_keys=True).encode()
    if not raw:
        return 0.0
    # byte histogram entropy-ish
    counts = [0] * 256
    for b in raw:
        counts[b] += 1
    import math

    n = len(raw)
    h = 0.0
    for c in counts:
        if c:
            p = c / n
            h -= p * math.log2(p)
    # normalize roughly 0–8 → 0–5 scale
    return round(min(5.0, h / 1.6), 3)


class JobLedger:
    def __init__(self, comms: Any):
        self.comms = comms

    def record(
        self,
        params: Any,
        *,
        coin: str = "BTC",
        pool_host: str = "",
        extra: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        entry = {
            "type": "job",
            "coin": coin,
            "checksum": checksum_job(params),
            "score": score_job(params),
            "pool": pool_host,
            "time": time.time(),
            "job_id": None,
        }
        if isinstance(params, list) and params:
            entry["job_id"] = params[0]
        if extra:
            entry["extra"] = extra
        try:
            raw = self.comms.get_state(LEDGER_KEY) or []
            if not isinstance(raw, list):
                raw = []
            raw.insert(0, entry)
            self.comms.set_state(LEDGER_KEY, raw[:MAX_ENTRIES])
            # bump yearn entropy slightly when high-score jobs arrive
            if entry["score"] >= 3.0:
                try:
                    ent = float(self.comms.get_state("entropy") or 0)
                    self.comms.set_state("entropy", min(5.0, ent + 0.05))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"ledger write: {e}")
        return entry

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            raw = self.comms.get_state(LEDGER_KEY) or []
            if isinstance(raw, list):
                return raw[:limit]
        except Exception:
            pass
        return []

    def stats(self) -> Dict[str, Any]:
        items = self.recent(100)
        if not items:
            return {"count": 0, "avg_score": 0.0, "max_score": 0.0}
        scores = [float(i.get("score") or 0) for i in items]
        return {
            "count": len(items),
            "avg_score": round(sum(scores) / len(scores), 3),
            "max_score": max(scores),
            "latest": items[0],
        }
