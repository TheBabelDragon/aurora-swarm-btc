"""
AssetAnchor — attestation service for swarm assets.

Pipeline:
  1. prepare / record     → mesh AnchorRecord (COMMITMENT_PENDING)
  2. request_broadcast    → enqueue for on-chain write
  3. process_queue        → single-asset Broadcaster  → BROADCAST
  4. process_queue_batched → Merkle root + one batch payload
  5. apply_chain_progress → INCLUDED / CONFIRMED at confirmation depth
  6. handle_reorg         → REORGED → RE_ANCHOR_REQUIRED

A locally observed transaction is never a confirmed anchor.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from comms.layer import CommsLayer, SwarmMessage

from .chain import ChainView, NullChain
from .commitment import (
    ARTIFACT_COMMITMENT_VERSION,
    compute_artifact_commitment,
    compute_commitment,
    compute_manifest_hash,
    derive_anchor_id,
    short_id,
)
from .lifecycle import (
    BROADCAST,
    COMMITMENT_PENDING,
    CONFIRMED,
    INCLUDED,
    RE_ANCHOR_REQUIRED,
    REORGED,
    UNANCHORED,
    default_confirmation_depth,
    normalize_status,
    transition,
)
from .records import AnchorRecord
from .queue import BroadcastQueue
from .broadcaster import Broadcaster, default_broadcaster, BroadcastResult
from .merkle import merkle_root, merkle_proof, batch_op_return_payload

logger = logging.getLogger("aurora.btc_anchor")

STATE_PREFIX = "asset:anchor:"
OBSERVED_PREFIX = "asset:anchor:observed:"


class AssetAnchor:
    def __init__(
        self,
        comms: CommsLayer,
        broadcaster: Optional[Broadcaster] = None,
        *,
        chain: Optional[ChainView] = None,
        confirmation_depth: Optional[int] = None,
    ):
        self.comms = comms
        self.node_id = comms.node_id
        self.queue = BroadcastQueue(comms)
        if broadcaster is not None:
            self.broadcaster = broadcaster
        elif chain is not None and not isinstance(chain, NullChain):
            from .broadcaster import LogBroadcaster

            self.broadcaster = LogBroadcaster(network="simulated")
        else:
            self.broadcaster = default_broadcaster()
        self.chain: ChainView = chain if chain is not None else NullChain()
        self.confirmation_depth = int(
            confirmation_depth if confirmation_depth is not None else default_confirmation_depth()
        )

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

    def prepare_artifact(
        self,
        asset_id: str,
        manifest_hash: str,
        artifact_epoch: int,
        commitment_version: int = ARTIFACT_COMMITMENT_VERSION,
    ) -> str:
        return compute_artifact_commitment(
            asset_id,
            manifest_hash,
            artifact_epoch,
            commitment_version=commitment_version,
        )

    def record(
        self,
        asset_id: str,
        commitment: Optional[str] = None,
        manifest_or_dict: Optional[Union[Dict[str, Any], Any]] = None,
        note: str = "",
        meta: Optional[Dict[str, Any]] = None,
        request_broadcast: bool = False,
        *,
        manifest_hash: Optional[str] = None,
        artifact_epoch: Optional[int] = None,
        commitment_version: int = ARTIFACT_COMMITMENT_VERSION,
    ) -> AnchorRecord:
        asset_id = str(asset_id).strip().lower()
        data = None
        if manifest_or_dict is not None:
            data = manifest_or_dict.to_dict() if hasattr(manifest_or_dict, "to_dict") else dict(manifest_or_dict)
            if not manifest_hash:
                manifest_hash = compute_manifest_hash(data)
        if artifact_epoch is None:
            tip = self.chain.tip() if self.chain else None
            artifact_epoch = tip.height if tip else None
        if not commitment:
            if artifact_epoch is not None and manifest_hash:
                commitment = self.prepare_artifact(
                    asset_id, manifest_hash, int(artifact_epoch), commitment_version=commitment_version
                )
            elif data is not None:
                commitment = self.prepare(data)
            else:
                raise ValueError("Either commitment or manifest_or_dict is required")

        rec = AnchorRecord(
            asset_id=asset_id,
            commitment=commitment,
            status=COMMITMENT_PENDING,
            created_at=0.0,
            created_by=self.node_id,
            method="mesh_record",
            note=note or "Mesh-recorded content commitment",
            meta=meta or {},
            manifest_hash=str(manifest_hash or ""),
            artifact_epoch=int(artifact_epoch) if artifact_epoch is not None else None,
            commitment_version=int(commitment_version),
            confirmation_depth=self.confirmation_depth,
            canonical=False,
            observed=True,
        )

        self._store(rec)

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
            for k in keys[: limit * 2]:
                key = k.replace("aurora:", "", 1) if str(k).startswith("aurora:") else k
                if key.endswith("queue") or ":queue" in key or key.startswith(OBSERVED_PREFIX):
                    continue
                if not key.startswith(STATE_PREFIX):
                    continue
                raw = self.comms.get_state(key)
                if isinstance(raw, dict) and "commitment" in raw:
                    try:
                        out.append(AnchorRecord.from_dict(raw))
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"list_anchors scan failed: {e}")
        return out[:limit]

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
            manifest_hash = compute_manifest_hash(data)
            tip = self.chain.tip() if self.chain else None
            epoch = tip.height if tip else None
            if epoch is None:
                # Mesh-only record: still not an authoritative Bitcoin epoch.
                return self.record(
                    asset_id,
                    manifest_or_dict=data,
                    note=note,
                    request_broadcast=request_broadcast,
                    manifest_hash=manifest_hash,
                    artifact_epoch=None,
                )
            commitment = self.prepare_artifact(asset_id, manifest_hash, int(epoch))
            return self.record(
                asset_id,
                commitment=commitment,
                manifest_or_dict=data,
                note=note,
                request_broadcast=request_broadcast,
                manifest_hash=manifest_hash,
                artifact_epoch=int(epoch),
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
        if rec and normalize_status(rec.status) in (COMMITMENT_PENDING, UNANCHORED, RE_ANCHOR_REQUIRED):
            rec.status = transition(rec.status, COMMITMENT_PENDING)
            rec.note = "Queued for broadcast"
            self._store(rec)
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
                    status=COMMITMENT_PENDING,
                    created_by=self.node_id,
                    confirmation_depth=self.confirmation_depth,
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
                self._submit_to_chain(result.txid, rec)
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

        batch_rec = AnchorRecord(
            asset_id="batch:" + root[:16],
            commitment=root,
            status=COMMITMENT_PENDING,
            created_by=self.node_id,
            method="merkle_batch",
            meta={
                "batch": True,
                "count": len(commitments),
                "asset_ids": asset_ids,
                "op_return_hex": payload.hex(),
            },
            confirmation_depth=self.confirmation_depth,
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
                self._store(rec)
            self.mark_broadcast(
                p["asset_id"],
                txid=result.txid,
                network=result.network,
                method="merkle_batch_" + (result.method or "broadcast"),
            )
            out["assets"].append({"asset_id": p["asset_id"], "proof_len": len(proof)})

        self._submit_to_chain(result.txid, batch_rec)
        logger.info(f"Batch anchored {len(pending)} assets root={root[:16]}… txid={result.txid}")
        return out

    def mark_broadcast(
        self,
        asset_id: str,
        txid: str,
        network: str = "bitcoin",
        method: str = "op_return",
    ) -> Optional[AnchorRecord]:
        """Upgrade to BROADCAST. Never to CONFIRMED — that requires chain depth."""
        rec = self.get(asset_id)
        if not rec:
            return None
        rec.status = transition(rec.status, BROADCAST)
        rec.txid = txid
        rec.network = network
        rec.method = method
        rec.canonical = False
        rec.confirmations = 0
        if txid.startswith("log:"):
            rec.note = f"Log-broadcast (not on-chain): {txid}"
        else:
            rec.note = f"Broadcast observed: {txid}"
        self._store(rec)
        logger.info(f"Anchor {rec.status} for {asset_id[:12]}… txid={txid}")
        return rec

    def apply_chain_progress(self) -> List[AnchorRecord]:
        """
        Walk known anchors and advance INCLUDED / CONFIRMED / REORGED from the chain view.
        """
        updated: List[AnchorRecord] = []
        if isinstance(self.chain, NullChain):
            return updated
        for rec in self.list_anchors(limit=200):
            changed = self._sync_record_with_chain(rec)
            if changed:
                self._store(rec)
                updated.append(rec)
        return updated

    def handle_reorg(self) -> List[AnchorRecord]:
        """Re-evaluate canonical status after a chain reorganization."""
        return self.apply_chain_progress()

    def _sync_record_with_chain(self, rec: AnchorRecord) -> bool:
        if not rec.txid:
            return False
        loc = self.chain.tx_location(rec.txid) if hasattr(self.chain, "tx_location") else None
        changed = False
        status = normalize_status(rec.status)

        if loc is None:
            if status in (INCLUDED, CONFIRMED):
                # Was included and the tx is no longer on the canonical chain.
                self._retain_observed(rec)
                rec.status = transition(status, REORGED)
                rec.canonical = False
                rec.confirmations = 0
                rec.note = "Inclusion block left the canonical chain"
                rec.status = transition(rec.status, RE_ANCHOR_REQUIRED)
                rec.note = "Re-anchor required after reorg"
                changed = True
            return changed

        canonical = bool(self.chain.is_canonical(loc.block_hash))
        confs = int(self.chain.confirmations(loc.block_hash)) if canonical else 0
        rec.btc_height = loc.height
        rec.btc_block_hash = loc.block_hash
        rec.btc_work = loc.work
        rec.included_at = loc.timestamp
        rec.confirmations = confs
        rec.canonical = canonical
        if rec.manifest_hash and rec.commitment:
            rec.anchor_id = derive_anchor_id(
                rec.asset_id, rec.manifest_hash, loc.block_hash, rec.commitment
            )

        if not canonical:
            self._retain_observed(rec)
            if status in (INCLUDED, CONFIRMED):
                rec.status = transition(status, REORGED)
                rec.status = transition(rec.status, RE_ANCHOR_REQUIRED)
                rec.note = "Re-anchor required after reorg"
                changed = True
            return True

        if status in (BROADCAST, COMMITMENT_PENDING, RE_ANCHOR_REQUIRED, UNANCHORED):
            rec.status = transition(status if status in (BROADCAST, COMMITMENT_PENDING, RE_ANCHOR_REQUIRED, UNANCHORED) else BROADCAST, INCLUDED)
            rec.note = f"Included at height {loc.height}"
            changed = True
            status = INCLUDED

        if status == INCLUDED and confs >= rec.confirmation_depth:
            rec.status = transition(INCLUDED, CONFIRMED)
            rec.note = f"Confirmed at depth {confs} (need {rec.confirmation_depth})"
            changed = True
        elif status == CONFIRMED and confs < rec.confirmation_depth:
            rec.status = INCLUDED
            rec.note = f"Dropped below confirmation depth ({confs}/{rec.confirmation_depth})"
            changed = True
        else:
            changed = True  # coordinates may have filled in
        return changed

    def _submit_to_chain(self, txid: str, rec: Optional[AnchorRecord]) -> None:
        chain = self.chain
        if chain is None or isinstance(chain, NullChain):
            return
        submit = getattr(chain, "submit_tx", None)
        if not callable(submit):
            return
        try:
            submit(txid, payload=rec.to_dict() if rec else {})
        except Exception as e:
            logger.debug(f"chain submit_tx: {e}")

    def _retain_observed(self, rec: AnchorRecord) -> None:
        """Never delete a historical observation when a reorg invalidates canonical status."""
        rec.observed = True
        try:
            key = f"{OBSERVED_PREFIX}{rec.asset_id}:{rec.anchor_id or rec.commitment[:16]}"
            payload = rec.to_dict()
            payload["canonical"] = False
            payload["observed"] = True
            self.comms.set_state(key, payload, expire=0)
        except Exception as e:
            logger.debug(f"retain observed: {e}")

    def _store(self, rec: AnchorRecord) -> None:
        self.comms.set_state(f"{STATE_PREFIX}{rec.asset_id}", rec.to_dict(), expire=0)
