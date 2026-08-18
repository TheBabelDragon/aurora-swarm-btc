"""Append-only mesh ledger for BVL events."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from comms.layer import CommsLayer

LEDGER_KEY = "bvl:ledger"
BAL_PREFIX = "bvl:bal:"
SUPPLY_KEY = "bvl:supply"


class BVLLedger:
    def __init__(self, comms: CommsLayer):
        self.comms = comms

    def _load_items(self) -> List[Dict[str, Any]]:
        raw = self.comms.get_state(LEDGER_KEY)
        if isinstance(raw, dict) and "items" in raw:
            return list(raw["items"])
        if isinstance(raw, list):
            return raw
        return []

    def append(self, entry: Dict[str, Any]):
        items = self._load_items()
        entry = dict(entry)
        entry.setdefault("ts", time.time())
        items.append(entry)
        self.comms.set_state(
            LEDGER_KEY,
            {"items": items[-2000:], "updated_at": time.time()},
            expire=0,
        )

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._load_items()[-limit:]

    def get_balance(self, node_id: str) -> float:
        raw = self.comms.get_state(f"{BAL_PREFIX}{node_id}")
        try:
            return float(raw or 0)
        except Exception:
            return 0.0

    def set_balance(self, node_id: str, amount: float):
        self.comms.set_state(f"{BAL_PREFIX}{node_id}", float(amount), expire=0)

    def get_supply(self) -> float:
        try:
            return float(self.comms.get_state(SUPPLY_KEY) or 0)
        except Exception:
            return 0.0

    def set_supply(self, amount: float):
        self.comms.set_state(SUPPLY_KEY, float(amount), expire=0)
