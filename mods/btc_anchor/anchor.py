"""
AssetAnchor — attestation service for swarm assets.

Pipeline:
  1. prepare / record     → mesh AnchorRecord (always)
  2. request_broadcast    → enqueue for on-chain write
  3. process_queue        → single-asset Broadcaster
  4. process_queue_batched → Merkle root + one batch payload
  5. mark_broadcast       → upgrade record with txid when confirmed
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from comms.layer import CommsLayer, SwarmMessage

from .commitment import compute_commitment, short_id
from .records import AnchorRecord
from .queue import BroadcastQueue
from .broadcaster import Broadcaster, default_broadcaster, BroadcastResult
from .merkle import merkle_root, merkle_proof, batch_op_return_payload

logger = logging.getLogger("aurora.btc_anchor")

STATE_PREFIX = "asset:anchor:"


class AssetAnchor:
    def __init__(self, comms: CommsLayer, broadcaster: Optional[Broadcaster] = None):
        self.comms = comms
        self.node_id = comms.node_id
        self.queue = BroadcastQueue(comms)
        self.broadcaster = broadcaster or default_broadcaster()

    def prepare(
        self,
        manifest_or_dict: Union[Dict[str, Any], Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        if hasattr(manifest_or_dict, "to_dict"):
            data = manifest_or_dict.to_dict()
        else:
            data = dict(manifest_or_dict)
        return compute_commitment(data, extra=extra)

    def record(
        self,
        asset_id: str,
        commitment: Optional[str] = None,
        manifest_or_dict: Optional[Union[Dict[str, Any], Any]] = None,
        note: str = "",
        meta: Optional[Dict[str, Any]] = None,
        request_broadcast: bool = False,
    ) -> AnchorRecord:
        asset_id = str(asset_id).strip().lower()
        if not commitment:
            if not manifest_or_dict:
                raise ValueError("Either commitment or manifest_or_dict is required")
            commitment = self.prepare(manifest_or_dict)

        rec = AnchorRecord(
            asset_id=asset_id,
            commitment=commitment,
            status="recorded",
            created_by=self.node_id,
            method="mesh_record",
            note=note or "Mesh-recorded content commitment",
            meta=meta or {},
        )

        self.comms.set_state(f"{STATE_PREFIX}{asset_id}", rec.to_dict(), expire=0)

        try:
            msg = SwarmMessage(
                type="asset.anchored",
                payload=rec.to_dict(),
                source=self.node_id,
            )
            self.comms.publish_message("asset.anchored", msg)
        except Exception as e:
            logger.debug(f"Could not publish asset.anchored: {e}")

        if request_broadcast:
            self.request_broadcast(asset_id, commitment=commitment)

        logger.info(
            f"Anchored asset {asset_id[:12]}… commitment={short_id(commitment)}… "
            f"status={rec.status} broadcast_queued={request_broadcast}"
        )
        return rec

    def get(self, asset_id: str) -> Optional[AnchorRecord]:
        asset_id = str(asset_id).strip().lower()
        raw = self.comms.get_state(f"{STATE_PREFIX}{asset_id}")
        if not raw or not isinstance(raw, dict):
            return None
        try:
            return AnchorRecord.from_dict(raw)
        except Exception:
            return None

    def list_anchors(self, limit: int = 50) -> List[AnchorRecord]:
        out: List[AnchorRecord] = []
        try:
            keys = self.comms.r.keys(f"aurora:{STATE_PREFIX}*") if hasattr(self.comms, "r") else []
            for k in keys[:limit]:
                key = k.replace("aurora:", "", 1) if k.startswith("aurora:") else k
                if key.endswith("queue") or ":queue" in key:
                    continue
                raw = self.comms.get_state(key)
                if isinstance(raw, dict) and "commitment" in raw:
                    try:
                        out.append(AnchorRecord.from_dict(raw))
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"list_anchors scan failed: {e}")
        return out

    def anchor_manifest(
        self,
        manifest_or_dict: Union[Dict[str, Any], Any],
        note: str = "",
        request_broadcast: bool = False,
    ) -> Optional[AnchorRecord]:
        try:
            if hasattr(manifest_or_dict, "to_dict"):
                data = manifest_or_dict.to_dict()
                asset_id = data.get("asset_id")
            else:
                data = dict(manifest_or_dict)
                asset_id = data.get("asset_id") or data.get("infohash")
            if not asset_id:
                raise ValueError("manifest missing asset_id")
            commitment = self.prepare(data)
            return self.record(
                asset_id,
                commitment=commitment,
                manifest_or_dict=data,
                note=note,
                request_broadcast=request_broadcast,
            )
        except Exception as e:
            logger.warning(f"anchor_manifest failed: {e}")
            return None

    def request_broadcast(self, asset_id: str, commitment: Optional[str] = None) -> bool:
        asset_id = str(asset_id).strip().lower()
        rec = self.get(asset_id)
        if not commitment:
            commitment = rec.commitment if rec else None
        if not commitment:
            logger.warning(f"request_broadcast: no commitment for {asset_id[:12]}")
            return False
        self.queue.enqueue(asset_id, commitment)
        if rec and rec.status == "recorded":
            rec.status = "pending_broadcast"
            rec.note = "Queued for broadcast"
            self.comms.set_state(f"{STATE_PREFIX}{asset_id}", rec.to_dict(), expire=0)
        return True

    def process_queue(self, max_items: int = 5) -> List[Dict[str, Any]]:
        results = []
        pending = self.queue.list_pending()[:max_items]
        for item in pending:
            asset_id = item["asset_id"]
            rec = self.get(asset_id)
            if not rec:
                rec = AnchorRecord(
                    asset_id=asset_id,
                    commitment=item["commitment"],
                    status="pending_broadcast",
                    created_by=self.node_id,
                )
            result: BroadcastResult = self.broadcaster.broadcast(rec)
            if result.ok and result.txid:
                self.queue.mark(asset_id, "submitted", txid=result.txid)
                self.mark_broadcast(
                    asset_id,
                    txid=result.txid,
                    network=result.network,
                    method=result.method,
                )
                results.append({"asset_id": asset_id, "ok": True, "txid": result.txid})
            else:
                self.queue.mark(asset_id, "pending", error=result.error)
                results.append({"asset_id": asset_id, "ok": False, "error": result.error})
        return results

    def process_queue_batched(self, max_items: int = 32) -> Dict[str, Any]:
        """
        Batch pending commitments into one Merkle root and one broadcast attempt.

        Each asset still gets an individual mesh upgrade with the shared batch txid
        and a stored Merkle proof for later inclusion checks.
        """
        pending = self.queue.list_pending()[:max_items]
        if not pending:
            return {"ok": True, "count": 0, "message": "empty queue"}

        commitments = [p["commitment"] for p in pending]
        asset_ids = [p["asset_id"] for p in pending]
        root = merkle_root(commitments)
        payload = batch_op_return_payload(root, len(commitments))

        # Build a synthetic batch record for the broadcaster
        batch_rec = AnchorRecord(
            asset_id="batch:" + root[:16],
            commitment=root,
            status="pending_broadcast",
            created_by=self.node_id,
            method="merkle_batch",
            meta={
                "batch": True,
                "count": len(commitments),
                "asset_ids": asset_ids,
                "op_return_hex": payload.hex(),
            },
        )
        result = self.broadcaster.broadcast(batch_rec)
        out = {
            "ok": result.ok,
            "count": len(pending),
            "root": root,
            "txid": result.txid,
            "error": result.error,
            "assets": [],
        }
        if not result.ok or not result.txid:
            for p in pending:
                self.queue.mark(p["asset_id"], "pending", error=result.error)
            return out

        for i, p in enumerate(pending):
            proof = merkle_proof(commitments, i)
            self.queue.mark(p["asset_id"], "submitted", txid=result.txid)
            rec = self.get(p["asset_id"])
            if rec:
                rec.meta = dict(rec.meta or {})
                rec.meta["merkle_root"] = root
                rec.meta["merkle_proof"] = proof
                rec.meta["batch"] = True
                self.comms.set_state(f"{STATE_PREFIX}{p['asset_id']}", rec.to_dict(), expire=0)
            self.mark_broadcast(
                p["asset_id"],
                txid=result.txid,
                network=result.network,
                method="merkle_batch_" + (result.method or "broadcast"),
            )
            out["assets"].append({"asset_id": p["asset_id"], "proof_len": len(proof)})

        logger.info(f"Batch anchored {len(pending)} assets root={root[:16]}… txid={result.txid}")
        return out

    def mark_broadcast(
        self,
        asset_id: str,
        txid: str,
        network: str = "bitcoin",
        method: str = "op_return",
    ) -> Optional[AnchorRecord]:
        rec = self.get(asset_id)
        if not rec:
            return None
        if txid.startswith("log:"):
            rec.status = "submitted"
            rec.note = f"Log-broadcast (not on-chain): {txid}"
        else:
            rec.status = "confirmed"
            rec.note = f"Broadcast confirmed: {txid}"
        rec.txid = txid
        rec.network = network
        rec.method = method
        self.comms.set_state(f"{STATE_PREFIX}{asset_id}", rec.to_dict(), expire=0)
        logger.info(f"Anchor {rec.status} for {asset_id[:12]}… txid={txid}")
        return rec
