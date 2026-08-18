"""
Live BVL economy — mint credits from real swarm events.

Hooks:
  asset.complete / torrent complete  → reward_seed to completing node
  asset.anchored                     → reward_attest to anchoring node

Optional:
  attest_supply() → commit circulating supply into btc_anchor
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, Optional

from comms.layer import CommsLayer

from .ledger_service import BabelLedger

logger = logging.getLogger("aurora.bvl.economy")


class EconomyReactor:
    def __init__(self, comms: CommsLayer, ledger: Optional[BabelLedger] = None):
        self.comms = comms
        self.ledger = ledger or BabelLedger(comms)
        self.node_id = comms.node_id
        self._started = False
        self._lock = threading.Lock()

    def start(self):
        if self._started:
            return
        self._started = True
        try:
            self.comms.subscribe("asset.complete", self._on_asset_complete)
        except Exception as e:
            logger.debug(f"subscribe asset.complete: {e}")
        try:
            self.comms.subscribe("asset.anchored", self._on_asset_anchored)
        except Exception as e:
            logger.debug(f"subscribe asset.anchored: {e}")
        # Also listen for generic swarm events if published under events channel patterns
        try:
            self.comms.subscribe("bvl.tick", self._on_uptime_tick)
        except Exception:
            pass
        logger.info("BVL EconomyReactor listening for asset.complete / asset.anchored")

    def _on_asset_complete(self, msg: Any):
        try:
            payload = msg.get("payload", msg) if isinstance(msg, dict) else {}
            if not isinstance(payload, dict):
                return
            asset_id = (
                payload.get("infohash")
                or payload.get("asset_id")
                or ""
            )
            node = payload.get("node_id") or payload.get("source") or self.node_id
            if not asset_id:
                return
            with self._lock:
                self.ledger.reward_seed(str(node), asset_id=str(asset_id))
            logger.info(f"BVL auto seed reward → {node} for {str(asset_id)[:12]}…")
        except Exception as e:
            logger.debug(f"_on_asset_complete: {e}")

    def _on_asset_anchored(self, msg: Any):
        try:
            payload = msg.get("payload", msg) if isinstance(msg, dict) else {}
            if not isinstance(payload, dict):
                return
            asset_id = payload.get("asset_id") or ""
            node = payload.get("created_by") or payload.get("source") or self.node_id
            with self._lock:
                self.ledger.reward_attest(str(node), asset_id=str(asset_id))
            logger.info(f"BVL auto attest reward → {node} for {str(asset_id)[:12]}…")
        except Exception as e:
            logger.debug(f"_on_asset_anchored: {e}")

    def _on_uptime_tick(self, msg: Any):
        try:
            with self._lock:
                self.ledger.reward_uptime()
        except Exception:
            pass

    def pulse_uptime(self):
        """Call from a worker loop to mint a small uptime tick for this node."""
        with self._lock:
            return self.ledger.reward_uptime()

    def supply_snapshot(self) -> Dict[str, Any]:
        """Canonical supply snapshot for attestation."""
        body = {
            "v": 1,
            "unit": "BVL",
            "supply": self.ledger.supply(),
            "node": self.node_id,
            "ts": int(time.time()),
        }
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        body["commitment"] = hashlib.sha256(raw).hexdigest()
        return body

    def attest_supply(self) -> Dict[str, Any]:
        """
        Record a content commitment of current BVL supply via btc_anchor.

        Soft dependency — returns a mesh-only snapshot if anchor is missing.
        """
        snap = self.supply_snapshot()
        try:
            from mods.btc_anchor.anchor import AssetAnchor

            anc = AssetAnchor(self.comms)
            # Use commitment field as asset-ish id prefix for the record
            asset_id = "bvl-supply-" + snap["commitment"][:32]
            rec = anc.record(
                asset_id,
                commitment=snap["commitment"],
                note="BVL circulating supply snapshot",
                meta=snap,
            )
            return {"ok": True, "snapshot": snap, "anchor": rec.to_dict() if rec else None}
        except Exception as e:
            logger.debug(f"attest_supply soft-fail: {e}")
            # Still store on mesh
            try:
                self.comms.set_state("bvl:supply_snapshot", snap, expire=86400)
            except Exception:
                pass
            return {"ok": True, "snapshot": snap, "anchor": None, "note": str(e)}


def start_economy(comms: CommsLayer) -> EconomyReactor:
    reactor = EconomyReactor(comms)
    reactor.start()
    return reactor
