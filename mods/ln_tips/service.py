"""
Seeder tip service.

Uses AssetFabric possession maps to decide who holds an asset, then
applies a simple policy and records tips on the mesh ledger.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer

from .tipper import Tipper, default_tipper, TipResult
from .ledger import TipLedger

logger = logging.getLogger("aurora.ln_tips")


class TipPolicy:
    def __init__(self, sats_per_seed: int = 10, max_recipients: int = 5):
        self.sats_per_seed = int(os.getenv("AURORA_LN_TIP_SATS", str(sats_per_seed)))
        self.max_recipients = int(os.getenv("AURORA_LN_TIP_MAX_RECIPIENTS", str(max_recipients)))


class TipService:
    def __init__(self, comms: CommsLayer, tipper: Optional[Tipper] = None, policy: Optional[TipPolicy] = None):
        self.comms = comms
        self.tipper = tipper or default_tipper()
        self.policy = policy or TipPolicy()
        self.ledger = TipLedger(comms)

    def reward_seeder(
        self,
        asset_id: str,
        node_id: str,
        *,
        amount_sats: Optional[int] = None,
        memo: Optional[str] = None,
        ln_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        amount = amount_sats if amount_sats is not None else self.policy.sats_per_seed
        memo = memo or f"aurora seeder tip asset={asset_id[:12]}"
        result: TipResult = self.tipper.tip(
            node_id=node_id, amount_sats=amount, memo=memo, ln_address=ln_address
        )
        entry = {
            "ts": time.time(),
            "asset_id": asset_id,
            "node_id": node_id,
            "amount_sats": amount,
            "ok": result.ok,
            "payment_id": result.payment_id,
            "method": result.method,
            "error": result.error,
        }
        self.ledger.record(entry)
        return entry

    def reward_holders(self, asset_id: str) -> List[Dict[str, Any]]:
        """Tip nodes that currently report possession of the asset."""
        holders: List[str] = []
        try:
            from mods.asset_fabric.fabric import AssetFabric
            fabric = AssetFabric(self.comms)
            sp = fabric.swarm_possession(asset_id)
            holders = list(sp.get("holders") or [])
        except Exception as e:
            logger.debug(f"reward_holders possession lookup failed: {e}")

        holders = holders[: self.policy.max_recipients]
        out = []
        for node in holders:
            out.append(self.reward_seeder(asset_id, node))
        return out

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.ledger.recent(limit)
