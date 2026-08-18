"""
AssetAnchor — optional attestation service for swarm assets.

v0.1 scope:
  - Deterministic content commitment
  - Record the commitment on the mesh (visible to all nodes)
  - Query / list anchors
  - Explicit extension point for a real Bitcoin broadcaster later

This does NOT require wallet keys or network fees to be useful today.
It establishes the attestation object and the place where on-chain
settlement will plug in.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Union

from comms.layer import CommsLayer, SwarmMessage

from .commitment import compute_commitment, short_id
from .records import AnchorRecord

logger = logging.getLogger("aurora.btc_anchor")

STATE_PREFIX = "asset:anchor:"


class AssetAnchor:
    def __init__(self, comms: CommsLayer):
        self.comms = comms
        self.node_id = comms.node_id

    def prepare(
        self,
        manifest_or_dict: Union[Dict[str, Any], Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Compute the commitment for a manifest (dict or AssetManifest-like)."""
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
    ) -> AnchorRecord:
        """
        Create (or refresh) a mesh-visible anchor record.

        If commitment is omitted, it is derived from manifest_or_dict.
        """
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
            note=note or "Mesh-recorded content commitment (on-chain broadcast pending)",
            meta=meta or {},
        )

        self.comms.set_state(f"{STATE_PREFIX}{asset_id}", rec.to_dict(), expire=0)

        # Notify the mesh so other nodes / dashboard can react
        try:
            msg = SwarmMessage(
                type="asset.anchored",
                payload=rec.to_dict(),
                source=self.node_id,
            )
            self.comms.publish_message("asset.anchored", msg)
        except Exception as e:
            logger.debug(f"Could not publish asset.anchored: {e}")

        logger.info(
            f"Anchored asset {asset_id[:12]}… commitment={short_id(commitment)}… "
            f"status={rec.status}"
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
        """Best-effort scan of mesh state for anchor records."""
        out: List[AnchorRecord] = []
        try:
            keys = self.comms.r.keys(f"aurora:{STATE_PREFIX}*") if hasattr(self.comms, "r") else []
            for k in keys[:limit]:
                key = k.replace("aurora:", "", 1) if k.startswith("aurora:") else k
                raw = self.comms.get_state(key)
                if isinstance(raw, dict) and "commitment" in raw:
                    try:
                        out.append(AnchorRecord.from_dict(raw))
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"list_anchors scan failed: {e}")
        return out

    def mark_broadcast(
        self,
        asset_id: str,
        txid: str,
        network: str = "bitcoin",
        method: str = "op_return",
    ) -> Optional[AnchorRecord]:
        """
        Extension point: call this after a real on-chain write succeeds.

        Future broadcasters (wallet, Electrum, batch service) should use this
        to upgrade a mesh_record into a confirmed attestation.
        """
        rec = self.get(asset_id)
        if not rec:
            return None
        rec.status = "confirmed"
        rec.txid = txid
        rec.network = network
        rec.method = method
        rec.note = f"Broadcast confirmed: {txid}"
        self.comms.set_state(f"{STATE_PREFIX}{asset_id}", rec.to_dict(), expire=0)
        logger.info(f"Anchor confirmed on-chain for {asset_id[:12]}… txid={txid}")
        return rec

    def anchor_manifest(
        self,
        manifest_or_dict: Union[Dict[str, Any], Any],
        note: str = "",
    ) -> Optional[AnchorRecord]:
        """Convenience: prepare + record in one call."""
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
            return self.record(asset_id, commitment=commitment, manifest_or_dict=data, note=note)
        except Exception as e:
            logger.warning(f"anchor_manifest failed: {e}")
            return None
