"""Mesh-visible tip ledger."""

from __future__ import annotations

import time
from typing import Any, Dict, List

from comms.layer import CommsLayer

LEDGER_KEY = "ln:tips:ledger"


class TipLedger:
    def __init__(self, comms: CommsLayer):
        self.comms = comms

    def _load(self) -> List[Dict[str, Any]]:
        raw = self.comms.get_state(LEDGER_KEY)
        if isinstance(raw, dict) and "items" in raw:
            return list(raw["items"])
        if isinstance(raw, list):
            return raw
        return []

    def _save(self, items: List[Dict[str, Any]]):
        self.comms.set_state(LEDGER_KEY, {"items": items[-500:], "updated_at": time.time()}, expire=0)

    def record(self, entry: Dict[str, Any]):
        items = self._load()
        items.append(entry)
        self._save(items)

    def recent(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self._load()[-limit:]
