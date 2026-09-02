"""
Epoch state roots for Aurora — externalize selected commitments to Bitcoin.

epoch = Bitcoin-chain-relative artifact time.

    epoch:
        chain = bitcoin
        height = H
        block_hash = HASH
        work = W

An epoch tick is deterministic from the anchor/chain state.
Do not derive epoch from time.time(), datetime.now(), peer arrival,
Redis arrival, or torrent completion. Those remain observational metadata.

Bitcoin does not store assets. It timestamps a root over:
  - verified possession summary
  - topology snapshot
  - redundancy policy
  - optional BVL supply
  - optional mining provenance snapshot

commit_epoch() → mesh record + soft btc_anchor.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer

logger = logging.getLogger("aurora.assets.epoch")


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def _sha(obj: Any) -> str:
    return hashlib.sha256(_canon(obj)).hexdigest()


@dataclass(frozen=True)
class ChainEpoch:
    """Bitcoin-chain-relative artifact time. Never a wall clock."""

    chain: str
    height: int
    block_hash: str
    work: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain": self.chain,
            "height": self.height,
            "block_hash": self.block_hash,
            "work": self.work,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChainEpoch":
        return cls(
            chain=str(d.get("chain") or "bitcoin"),
            height=int(d["height"]),
            block_hash=str(d["block_hash"]),
            work=str(d.get("work") or "0"),
        )

    @classmethod
    def from_tip(cls, tip: Any) -> Optional["ChainEpoch"]:
        if tip is None:
            return None
        d = tip.to_dict() if hasattr(tip, "to_dict") else dict(tip)
        if d.get("height") is None or not d.get("block_hash"):
            return None
        return cls(
            chain=str(d.get("chain") or "bitcoin"),
            height=int(d["height"]),
            block_hash=str(d["block_hash"]),
            work=str(d.get("work") or "0"),
        )


class EpochBuilder:
    def __init__(self, comms: CommsLayer, *, chain: Any = None):
        self.comms = comms
        self.node_id = comms.node_id
        self.chain = chain

    def chain_epoch(self) -> Optional[ChainEpoch]:
        if self.chain is not None and hasattr(self.chain, "tip"):
            return ChainEpoch.from_tip(self.chain.tip())
        # Prefer an already-stored latest chain coordinate if one exists.
        try:
            raw = self.comms.get_state("epoch:chain")
            if isinstance(raw, dict) and raw.get("height") is not None:
                return ChainEpoch.from_dict(raw)
        except Exception:
            pass
        return None

    def build(
        self,
        *,
        verified_registry: Optional[Dict[str, Any]] = None,
        topology: Optional[List[Dict[str, Any]]] = None,
        policy: Optional[Dict[str, Any]] = None,
        bvl_supply: Optional[float] = None,
        mining_snapshot: Optional[Dict[str, Any]] = None,
        note: str = "",
        chain_epoch: Optional[ChainEpoch] = None,
    ) -> Dict[str, Any]:
        ce = chain_epoch if chain_epoch is not None else self.chain_epoch()
        body: Dict[str, Any] = {
            "v": 1,
            "kind": "aurora_epoch",
            "by": self.node_id,
            "verified_registry": verified_registry or {},
            "topology": topology or [],
            "policy": policy or {},
            "bvl_supply": bvl_supply,
            "mining_snapshot": mining_snapshot or {},
            "note": note,
        }
        if ce is not None:
            body["epoch"] = ce.to_dict()
            body["chain"] = ce.chain
            body["height"] = ce.height
            body["block_hash"] = ce.block_hash
            body["work"] = ce.work
        else:
            # Unanchored swarm root: no authoritative Bitcoin epoch.
            body["epoch"] = None
        body["registry_root"] = _sha(body["verified_registry"])
        body["topology_root"] = _sha(body["topology"])
        body["policy_root"] = _sha(body["policy"])
        body["mining_root"] = _sha(body.get("mining_snapshot") or {})
        root_input = {
            "registry_root": body["registry_root"],
            "topology_root": body["topology_root"],
            "policy_root": body["policy_root"],
            "bvl_supply": bvl_supply,
            "mining_root": body["mining_root"],
            "by": body["by"],
        }
        if ce is not None:
            root_input["epoch"] = ce.to_dict()
        body["epoch_root"] = _sha(root_input)
        return body

    def from_local_state(
        self,
        *,
        possession: Any = None,
        topology_registry: Any = None,
        policy: Any = None,
        note: str = "",
        mining_epoch: Optional[int] = None,
        chain_epoch: Optional[ChainEpoch] = None,
    ) -> Dict[str, Any]:
        verified: Dict[str, Any] = {}
        if possession is not None:
            try:
                for asset_id, nodes in getattr(possession, "verified", {}).items():
                    verified[asset_id] = {
                        nid: sorted(vp.verified_pieces)
                        for nid, vp in nodes.items()
                    }
            except Exception as e:
                logger.debug(f"verified registry: {e}")

        topo_list: List[Dict[str, Any]] = []
        if topology_registry is not None:
            try:
                topo_list = topology_registry.to_list()
            except Exception:
                pass

        pol = {}
        if policy is not None:
            pol = policy.to_dict() if hasattr(policy, "to_dict") else dict(policy)

        bvl_supply = None
        try:
            from mods.bvl.ledger_service import BabelLedger

            bvl_supply = BabelLedger(self.comms).supply()
        except Exception:
            pass

        mining_snapshot = None
        try:
            from mods.mining_provenance.service import MiningProvenance

            # Mining snapshot index is observational. Prefer Bitcoin height when known.
            ce = chain_epoch if chain_epoch is not None else self.chain_epoch()
            ep = int(mining_epoch if mining_epoch is not None else (ce.height if ce else 0))
            mining_snapshot = MiningProvenance(self.comms).epoch_snapshot(ep)
        except Exception:
            pass

        return self.build(
            verified_registry=verified,
            topology=topo_list,
            policy=pol,
            bvl_supply=bvl_supply,
            mining_snapshot=mining_snapshot,
            note=note,
            chain_epoch=chain_epoch,
        )

    def commit(self, epoch: Dict[str, Any], *,
               request_broadcast: bool = False) -> Dict[str, Any]:
        root = epoch.get("epoch_root") or ""
        height = epoch.get("height")
        asset_id = f"epoch-{root[:32]}" if root else f"epoch-{height or 'unanchored'}"
        try:
            self.comms.set_state(f"epoch:{asset_id}", epoch, expire=0)
            latest = {"asset_id": asset_id, "root": root, "epoch": epoch.get("epoch")}
            self.comms.set_state("epoch:latest", latest, expire=0)
            if epoch.get("epoch"):
                self.comms.set_state("epoch:chain", epoch["epoch"], expire=0)
        except Exception as e:
            logger.warning(f"epoch mesh store: {e}")

        anchor_rec = None
        try:
            from mods.btc_anchor.anchor import AssetAnchor

            anc = AssetAnchor(self.comms, chain=self.chain)
            if hasattr(anc, "record"):
                rec = anc.record(
                    asset_id,
                    commitment=root,
                    note="Aurora epoch state root",
                    meta={"kind": "epoch", "chain_epoch": epoch.get("epoch")},
                )
                if request_broadcast and hasattr(anc, "request_broadcast"):
                    anc.request_broadcast(asset_id)
                anchor_rec = rec.to_dict() if rec and hasattr(rec, "to_dict") else rec
            else:
                anchor_rec = {"commitment": root, "status": "mesh_only"}
        except Exception as e:
            logger.debug(f"epoch anchor soft-fail: {e}")
            anchor_rec = {"error": str(e), "commitment": root}

        return {
            "ok": True,
            "asset_id": asset_id,
            "epoch_root": root,
            "epoch": epoch.get("epoch"),
            "anchor": anchor_rec,
            "body": epoch,
        }


def commit_epoch(comms: CommsLayer, **kwargs) -> Dict[str, Any]:
    chain = kwargs.pop("chain", None)
    b = EpochBuilder(comms, chain=chain)
    broadcast = bool(kwargs.pop("request_broadcast", False))
    epoch = b.from_local_state(**kwargs)
    return b.commit(epoch, request_broadcast=broadcast)
