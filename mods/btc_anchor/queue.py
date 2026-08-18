"""Pending broadcast queue stored on the mesh."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer

logger = logging.getLogger("aurora.btc_anchor.queue")

QUEUE_KEY = "asset:anchor:queue"


class BroadcastQueue:
    def __init__(self, comms: CommsLayer):
        self.comms = comms

    def _load(self) -> List[Dict[str, Any]]:
        raw = self.comms.get_state(QUEUE_KEY)
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict) and "items" in raw:
            return list(raw["items"])
        return []

    def _save(self, items: List[Dict[str, Any]]):
        # Keep last 200 entries
        self.comms.set_state(QUEUE_KEY, {"items": items[-200:], "updated_at": time.time()}, expire=0)

    def enqueue(self, asset_id: str, commitment: str, note: str = "") -> Dict[str, Any]:
        items = self._load()
        # Dedupe pending for same asset
        items = [i for i in items if not (i.get("asset_id") == asset_id and i.get("status") == "pending")]
        entry = {
            "asset_id": asset_id,
            "commitment": commitment,
            "status": "pending",
            "enqueued_at": time.time(),
            "note": note,
            "txid": None,
            "attempts": 0,
        }
        items.append(entry)
        self._save(items)
        logger.info(f"Queued broadcast for {asset_id[:12]}…")
        return entry

    def list_pending(self) -> List[Dict[str, Any]]:
        return [i for i in self._load() if i.get("status") == "pending"]

    def list_all(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._load()[-limit:]

    def mark(
        self,
        asset_id: str,
        status: str,
        txid: Optional[str] = None,
        error: Optional[str] = None,
    ):
        items = self._load()
        for i in items:
            if i.get("asset_id") == asset_id and i.get("status") in ("pending", "submitted"):
                i["status"] = status
                i["attempts"] = int(i.get("attempts") or 0) + 1
                if txid:
                    i["txid"] = txid
                if error:
                    i["error"] = error
                i["updated_at"] = time.time()
        self._save(items)
