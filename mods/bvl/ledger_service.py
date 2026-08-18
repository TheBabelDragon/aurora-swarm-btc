"""
Babel Value Ledger — public service API.

Balances and supply live on shared Redis (expire=0). Global accuracy requires
all nodes to use the same REDIS_URL.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer, SwarmMessage

from .ledger import BAL_PREFIX, BVLLedger
from .policy import BVLPolicy

logger = logging.getLogger("aurora.bvl")


class BabelLedger:
    def __init__(self, comms: CommsLayer, policy: Optional[BVLPolicy] = None):
        self.comms = comms
        self.node_id = comms.node_id
        self.ledger = BVLLedger(comms)
        self.policy = policy or BVLPolicy()

    def balance(self, node_id: Optional[str] = None) -> float:
        return self.ledger.get_balance(node_id or self.node_id)

    def supply(self) -> float:
        return self.ledger.get_supply()

    def all_balances(self) -> Dict[str, float]:
        """Scan Redis for bvl:bal:* — global view on shared mesh."""
        out: Dict[str, float] = {}
        try:
            # keys stored as aurora:bvl:bal:NODE
            r = self.comms.r
            for key in r.scan_iter(match="aurora:bvl:bal:*", count=200):
                k = key.decode() if isinstance(key, bytes) else str(key)
                node = k.split("aurora:bvl:bal:")[-1]
                try:
                    out[node] = float(r.get(key) or 0)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"all_balances: {e}")
            # fallback: peers only
            try:
                for n in self.comms.get_active_nodes() or []:
                    nid = n.get("node_id") or ""
                    if nid:
                        out[nid] = self.ledger.get_balance(nid)
            except Exception:
                pass
        return out

    def _claim_key(self, reason: str, node_id: str, asset_id: str) -> str:
        return f"bvl:claim:{reason}:{node_id}:{asset_id}"

    def _already_claimed(self, reason: str, node_id: str, asset_id: str) -> bool:
        if not asset_id:
            return True
        try:
            return bool(self.comms.get_state(self._claim_key(reason, node_id, asset_id)))
        except Exception:
            return False

    def _mark_claimed(self, reason: str, node_id: str, asset_id: str) -> None:
        try:
            self.comms.set_state(
                self._claim_key(reason, node_id, asset_id),
                {"ts": time.time(), "reason": reason, "node_id": node_id, "asset_id": asset_id},
                expire=0,  # persistent claim
            )
        except Exception as e:
            logger.warning(f"claim mark failed: {e}")

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

    def reward_seed(
        self,
        node_id: Optional[str] = None,
        asset_id: str = "",
        amount: Optional[float] = None,
        *,
        force_system: bool = False,
    ) -> Dict[str, Any]:
        nid = node_id or self.node_id
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return {"ok": False, "error": "asset_id required for seed mint"}
        if self._already_claimed("seed_hold", nid, asset_id):
            return {"ok": False, "error": "already claimed", "reason": "seed_hold", "asset_id": asset_id, "to": nid}
        amt = amount if amount is not None else self.policy.seed_hold
        out = self._credit(nid, amt, reason="seed_hold", meta={"asset_id": asset_id, "system": True})
        if out.get("ok"):
            self._mark_claimed("seed_hold", nid, asset_id)
        return out

    def reward_attest(
        self,
        node_id: Optional[str] = None,
        asset_id: str = "",
        *,
        force_system: bool = False,
    ) -> Dict[str, Any]:
        nid = node_id or self.node_id
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return {"ok": False, "error": "asset_id required for attest mint"}
        if self._already_claimed("attest", nid, asset_id):
            return {"ok": False, "error": "already claimed", "reason": "attest", "asset_id": asset_id, "to": nid}
        out = self._credit(
            nid,
            self.policy.attest,
            reason="attest",
            meta={"asset_id": asset_id, "system": True},
        )
        if out.get("ok"):
            self._mark_claimed("attest", nid, asset_id)
        return out

    def reward_uptime(self, node_id: Optional[str] = None, epoch_key: str = "") -> Dict[str, Any]:
        nid = node_id or self.node_id
        epoch_key = (epoch_key or "").strip() or f"tick-{int(time.time()) // 3600}"
        if self._already_claimed("uptime", nid, epoch_key):
            return {"ok": False, "error": "already claimed", "reason": "uptime", "asset_id": epoch_key}
        out = self._credit(nid, self.policy.uptime_tick, reason="uptime", meta={"epoch": epoch_key, "system": True})
        if out.get("ok"):
            self._mark_claimed("uptime", nid, epoch_key)
        return out

    def score_holders(self, asset_id: str) -> List[Dict[str, Any]]:
        asset_id = (asset_id or "").strip()
        if not asset_id:
            return [{"ok": False, "error": "asset_id required"}]
        holders: List[str] = []
        try:
            from mods.asset_fabric.fabric import AssetFabric

            fabric = AssetFabric(self.comms)
            holders = list(fabric.swarm_possession(asset_id).get("holders") or [])
        except Exception as e:
            logger.debug(f"score_holders: {e}")
        return [self.reward_seed(h, asset_id=asset_id) for h in holders]

    def transfer(self, to_node: str, amount: float, memo: str = "") -> Dict[str, Any]:
        from_node = self.node_id
        to_node = (to_node or "").strip()
        if not to_node:
            return {"ok": False, "error": "to_node required"}
        if to_node == from_node:
            return {"ok": False, "error": "cannot transfer to self"}
        try:
            amount = float(amount)
        except Exception:
            return {"ok": False, "error": "invalid amount"}
        if amount <= 0:
            return {"ok": False, "error": "amount must be positive"}
        max_tx = float(getattr(self.policy, "max_transfer", 1_000_000) or 1_000_000)
        if amount > max_tx:
            return {"ok": False, "error": "amount exceeds max_transfer", "max": max_tx}
        memo = (memo or "")[:200]
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
        result = {"ok": True, "burned": burned, "sats_requested": sats, "tip": tip_entry}
        self.ledger.append(
            {"type": "settle", "node": node, "amount_bvl": amount_bvl, "sats": sats, "tip": tip_entry, "ts": time.time()}
        )
        return result

    def status(self) -> Dict[str, Any]:
        balances = self.all_balances()
        return {
            "node_id": self.node_id,
            "balance": self.balance(),
            "supply": self.supply(),
            "balances_global": balances,
            "balance_sum": round(sum(balances.values()), 6),
            "mint_policy": "system_events_only",
            "persistence": "redis_shared_expire_0",
            "policy": {
                "seed_hold": self.policy.seed_hold,
                "attest": self.policy.attest,
                "uptime_tick": self.policy.uptime_tick,
                "settle_sats_per_bvl": self.policy.settle_sats_per_bvl,
            },
        }

    def recent(self, limit: int = 30) -> List[Dict[str, Any]]:
        return self.ledger.recent(limit)
