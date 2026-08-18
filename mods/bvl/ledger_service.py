"""
Babel Value Ledger — public service API.

BVL is mesh-native swarm credit:
  mint  → earn for useful work (seed, attest, uptime)
  transfer → peer to peer on the mesh
  burn / settle → optional bridge into ln_tips (sats)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer, SwarmMessage

from .ledger import BVLLedger
from .policy import BVLPolicy

logger = logging.getLogger("aurora.bvl")


class BabelLedger:
    def __init__(self, comms: CommsLayer, policy: Optional[BVLPolicy] = None):
        self.comms = comms
        self.node_id = comms.node_id
        self.ledger = BVLLedger(comms)
        self.policy = policy or BVLPolicy()

    # ------------------------------------------------------------------
    # Balances
    # ------------------------------------------------------------------

    def balance(self, node_id: Optional[str] = None) -> float:
        return self.ledger.get_balance(node_id or self.node_id)

    def supply(self) -> float:
        return self.ledger.get_supply()

    def _credit(self, node_id: str, amount: float, reason: str, meta: Optional[Dict] = None) -> Dict[str, Any]:
        if amount <= 0:
            return {"ok": False, "error": "amount must be positive"}
        bal = self.ledger.get_balance(node_id) + amount
        self.ledger.set_balance(node_id, bal)
        supply = self.ledger.get_supply() + amount
        self.ledger.set_supply(supply)
        entry = {
            "type": "mint",
            "to": node_id,
            "amount": amount,
            "reason": reason,
            "balance_after": bal,
            "supply_after": supply,
            "meta": meta or {},
            "by": self.node_id,
            "ts": time.time(),
        }
        self.ledger.append(entry)
        self._emit(entry)
        logger.info(f"BVL mint {amount} → {node_id} ({reason}) bal={bal}")
        return {"ok": True, **entry}

    def _debit(self, node_id: str, amount: float, reason: str, meta: Optional[Dict] = None) -> Dict[str, Any]:
        if amount <= 0:
            return {"ok": False, "error": "amount must be positive"}
        bal = self.ledger.get_balance(node_id)
        if bal < amount:
            return {"ok": False, "error": "insufficient BVL", "balance": bal}
        bal -= amount
        self.ledger.set_balance(node_id, bal)
        supply = max(0.0, self.ledger.get_supply() - amount)
        self.ledger.set_supply(supply)
        entry = {
            "type": "burn",
            "from": node_id,
            "amount": amount,
            "reason": reason,
            "balance_after": bal,
            "supply_after": supply,
            "meta": meta or {},
            "by": self.node_id,
            "ts": time.time(),
        }
        self.ledger.append(entry)
        self._emit(entry)
        return {"ok": True, **entry}

    def _emit(self, entry: Dict[str, Any]):
        try:
            msg = SwarmMessage(type="bvl.event", payload=entry, source=self.node_id)
            self.comms.publish_message("bvl.event", msg)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Earn
    # ------------------------------------------------------------------

    def reward_seed(self, node_id: Optional[str] = None, asset_id: str = "", amount: Optional[float] = None) -> Dict[str, Any]:
        amt = amount if amount is not None else self.policy.seed_hold
        return self._credit(
            node_id or self.node_id,
            amt,
            reason="seed_hold",
            meta={"asset_id": asset_id},
        )

    def reward_attest(self, node_id: Optional[str] = None, asset_id: str = "") -> Dict[str, Any]:
        return self._credit(
            node_id or self.node_id,
            self.policy.attest,
            reason="attest",
            meta={"asset_id": asset_id},
        )

    def reward_uptime(self, node_id: Optional[str] = None) -> Dict[str, Any]:
        return self._credit(
            node_id or self.node_id,
            self.policy.uptime_tick,
            reason="uptime",
        )

    def score_holders(self, asset_id: str) -> List[Dict[str, Any]]:
        """Mint seed rewards for every node that holds the asset."""
        holders: List[str] = []
        try:
            from mods.asset_fabric.fabric import AssetFabric

            fabric = AssetFabric(self.comms)
            holders = list(fabric.swarm_possession(asset_id).get("holders") or [])
        except Exception as e:
            logger.debug(f"score_holders: {e}")
        out = []
        for h in holders:
            out.append(self.reward_seed(h, asset_id=asset_id))
        return out

    # ------------------------------------------------------------------
    # Transfer / settle
    # ------------------------------------------------------------------

    def transfer(self, to_node: str, amount: float, memo: str = "") -> Dict[str, Any]:
        from_node = self.node_id
        fee = self.policy.transfer_fee
        total = amount + fee
        bal = self.ledger.get_balance(from_node)
        if bal < total:
            return {"ok": False, "error": "insufficient BVL", "balance": bal, "need": total}

        self.ledger.set_balance(from_node, bal - total)
        to_bal = self.ledger.get_balance(to_node) + amount
        self.ledger.set_balance(to_node, to_bal)
        if fee > 0:
            supply = max(0.0, self.ledger.get_supply() - fee)
            self.ledger.set_supply(supply)
        else:
            supply = self.ledger.get_supply()

        entry = {
            "type": "transfer",
            "from": from_node,
            "to": to_node,
            "amount": amount,
            "fee": fee,
            "memo": memo,
            "supply_after": supply,
            "ts": time.time(),
            "by": self.node_id,
        }
        self.ledger.append(entry)
        self._emit(entry)
        return {"ok": True, **entry, "from_balance": bal - total, "to_balance": to_bal}

    def settle_to_sats(
        self,
        amount_bvl: float,
        *,
        tip_node: Optional[str] = None,
        asset_id: str = "",
    ) -> Dict[str, Any]:
        """
        Burn BVL and attempt an ln_tips reward (sats) to tip_node (default: self).

        Soft dependency: if ln_tips missing, burn still happens and settlement is recorded as pending.
        """
        node = tip_node or self.node_id
        burned = self._debit(node, amount_bvl, reason="settle_to_sats", meta={"asset_id": asset_id})
        if not burned.get("ok"):
            return burned

        sats = int(amount_bvl * self.policy.settle_sats_per_bvl)
        tip_entry = None
        try:
            from mods.ln_tips.service import TipService

            tips = TipService(self.comms)
            tip_entry = tips.reward_seeder(
                asset_id or "bvl-settle",
                node,
                amount_sats=max(1, sats),
                memo=f"BVL settle {amount_bvl}",
            )
        except Exception as e:
            tip_entry = {"ok": False, "error": str(e)}

        result = {
            "ok": True,
            "burned": burned,
            "sats_requested": sats,
            "tip": tip_entry,
        }
        self.ledger.append(
            {
                "type": "settle",
                "node": node,
                "amount_bvl": amount_bvl,
                "sats": sats,
                "tip": tip_entry,
                "ts": time.time(),
            }
        )
        return result

    def status(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "balance": self.balance(),
            "supply": self.supply(),
            "policy": {
                "seed_hold": self.policy.seed_hold,
                "attest": self.policy.attest,
                "uptime_tick": self.policy.uptime_tick,
                "settle_sats_per_bvl": self.policy.settle_sats_per_bvl,
            },
        }

    def recent(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self.ledger.recent(limit)
