"""
Epoch state roots for Aurora — externalize selected commitments to Bitcoin.

Bitcoin does not store assets. It timestamps a root over:
  - verified possession summary
  - topology snapshot
  - redundancy policy
  - optional BVL supply

commit_epoch() → mesh record + soft btc_anchor.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer

logger = logging.getLogger("aurora.assets.epoch")


def _canon(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def _sha(obj: Any) -> str:
    return hashlib.sha256(_canon(obj)).hexdigest()


class EpochBuilder:
    def __init__(self, comms: CommsLayer):
        self.comms = comms
        self.node_id = comms.node_id

    def build(
        self,
        *,
        verified_registry: Optional[Dict[str, Any]] = None,
        topology: Optional[List[Dict[str, Any]]] = None,
        policy: Optional[Dict[str, Any]] = None,
        bvl_supply: Optional[float] = None,
        note: str = "",
    ) -> Dict[str, Any]:
        body = {
            "v": 1,
            "kind": "aurora_epoch",
            "ts": int(time.time()),
            "by": self.node_id,
            "verified_registry": verified_registry or {},
            "topology": topology or [],
            "policy": policy or {},
            "bvl_supply": bvl_supply,
            "note": note,
        }
        body["registry_root"] = _sha(body["verified_registry"])
        body["topology_root"] = _sha(body["topology"])
        body["policy_root"] = _sha(body["policy"])
        body["epoch_root"] = _sha(
            {
                "registry_root": body["registry_root"],
                "topology_root": body["topology_root"],
                "policy_root": body["policy_root"],
                "bvl_supply": bvl_supply,
                "ts": body["ts"],
                "by": body["by"],
            }
        )
        return body

    def from_local_state(
        self,
        *,
        possession: Any = None,
        topology_registry: Any = None,
        policy: Any = None,
        note: str = "",
    ) -> Dict[str, Any]:
        verified: Dict[str, Any] = {}
        if possession is not None:
            # possession.verified: asset → node → VerifiedPossession
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

        return self.build(
            verified_registry=verified,
            topology=topo_list,
            policy=pol,
            bvl_supply=bvl_supply,
            note=note,
        )

    def commit(self, epoch: Dict[str, Any], *,
               request_broadcast: bool = False) -> Dict[str, Any]:
        """Store on mesh; optionally anchor via btc_anchor."""
        root = epoch.get("epoch_root") or ""
        asset_id = f"epoch-{root[:32]}" if root else f"epoch-{int(time.time())}"
        try:
            self.comms.set_state(f"epoch:{asset_id}", epoch, expire=0)
            self.comms.set_state("epoch:latest", {"asset_id": asset_id, "root": root, "ts": epoch.get("ts")}, expire=0)
        except Exception as e:
            logger.warning(f"epoch mesh store: {e}")

        anchor_rec = None
        try:
            from mods.btc_anchor.anchor import AssetAnchor

            anc = AssetAnchor(self.comms)
            # Prefer record() if present; else minimal path
            if hasattr(anc, "record"):
                rec = anc.record(
                    asset_id,
                    commitment=root,
                    note="Aurora epoch state root",
                    meta={"kind": "epoch", "ts": epoch.get("ts")},
                )
                if request_broadcast and hasattr(anc, "request_broadcast"):
                    anc.request_broadcast(asset_id)
                anchor_rec = rec.to_dict() if rec and hasattr(rec, "to_dict") else rec
            else:
                # Fallback: store commitment-shaped note in mesh only
                anchor_rec = {"commitment": root, "status": "mesh_only"}
        except Exception as e:
            logger.debug(f"epoch anchor soft-fail: {e}")
            anchor_rec = {"error": str(e), "commitment": root}

        return {"ok": True, "asset_id": asset_id, "epoch_root": root, "anchor": anchor_rec, "epoch": epoch}


def commit_epoch(comms: CommsLayer, **kwargs) -> Dict[str, Any]:
    """Convenience: build from local state and commit."""
    b = EpochBuilder(comms)
    epoch = b.from_local_state(**{k: v for k, v in kwargs.items() if k != "request_broadcast"})
    return b.commit(epoch, request_broadcast=bool(kwargs.get("request_broadcast")))
