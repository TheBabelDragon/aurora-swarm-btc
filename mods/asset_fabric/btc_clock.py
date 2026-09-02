"""
Narrow adapter: Asset Fabric ↔ BTC Anchor.

    AssetFabric
        → BTCClock
            → BTCAnchor

Never import torrent_manager from this module.
Never let BTCAnchor depend on TorrentManager.

Bitcoin is not the artifact store. Bitcoin is not the torrent protocol.
Bitcoin does not define artifact identity. Bitcoin supplies an independently
verifiable temporal/scarcity anchor.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Union

from comms.layer import CommsLayer

from .artifact_clock import (
    CONFIDENCE_NONE,
    ArtifactClock,
    confidence_from_status,
)

logger = logging.getLogger("aurora.assets.btc_clock")


def _btc_enabled(flag: Optional[bool] = None) -> bool:
    if flag is not None:
        return bool(flag)
    raw = os.getenv("AURORA_BTC_CLOCK", "1").strip().lower()
    return raw not in ("0", "false", "no", "off", "disabled")


class BTCClock:
    """asset_fabric → btc_anchor and btc_anchor → asset_fabric."""

    def __init__(
        self,
        comms: CommsLayer,
        *,
        chain: Any = None,
        confirmation_depth: Optional[int] = None,
        enabled: Optional[bool] = None,
        anchor: Any = None,
    ):
        self.comms = comms
        self.node_id = comms.node_id
        self.enabled = _btc_enabled(enabled)
        self._chain = chain
        self._confirmation_depth = confirmation_depth
        self._anchor = anchor
        self._anchor_tried = anchor is not None

    def _get_anchor(self):
        if not self.enabled:
            return None
        if self._anchor_tried:
            return self._anchor
        self._anchor_tried = True
        try:
            from mods.btc_anchor.anchor import AssetAnchor
            from mods.btc_anchor.chain import NullChain

            chain = self._chain
            if chain is None:
                chain = NullChain()
            self._anchor = AssetAnchor(
                self.comms,
                chain=chain,
                confirmation_depth=self._confirmation_depth,
            )
        except Exception as e:
            logger.debug(f"btc_anchor not available: {e}")
            self._anchor = None
        return self._anchor

    @property
    def chain(self):
        return self._chain

    def current_clock(self) -> Optional[Dict[str, Any]]:
        """Current Bitcoin-chain coordinates. None if the BTC layer is disabled."""
        if not self.enabled:
            return None
        chain = self._chain
        if chain is None:
            anc = self._get_anchor()
            chain = getattr(anc, "chain", None) if anc else None
        if chain is None or not hasattr(chain, "tip"):
            return None
        tip = chain.tip()
        if tip is None:
            return None
        return tip.to_dict() if hasattr(tip, "to_dict") else dict(tip)

    def anchor_asset(
        self,
        asset_id: str,
        *,
        manifest_hash: Optional[str] = None,
        manifest: Optional[Union[Dict[str, Any], Any]] = None,
        request_broadcast: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Commit the artifact identity to the current Bitcoin epoch. Does not store the payload."""
        asset_id = str(asset_id).strip().lower()
        if not self.enabled:
            return None
        anc = self._get_anchor()
        if not anc:
            return None
        data = None
        if manifest is not None:
            data = manifest.to_dict() if hasattr(manifest, "to_dict") else dict(manifest)
            if not manifest_hash:
                from mods.btc_anchor.commitment import compute_manifest_hash

                manifest_hash = compute_manifest_hash(data)
        if not manifest_hash:
            stored = self.comms.get_state(f"asset:manifest:{asset_id}")
            if isinstance(stored, dict):
                data = stored
                from mods.btc_anchor.commitment import compute_manifest_hash

                manifest_hash = stored.get("manifest_hash") or compute_manifest_hash(stored)
        if not manifest_hash:
            raise ValueError("manifest_hash is required to anchor an artifact")
        rec = anc.record(
            asset_id,
            manifest_or_dict=data,
            note="artifact clock commitment",
            request_broadcast=request_broadcast,
            manifest_hash=manifest_hash,
        )
        if request_broadcast:
            try:
                anc.process_queue(max_items=8)
            except Exception as e:
                logger.debug(f"process_queue: {e}")
            try:
                anc.apply_chain_progress()
            except Exception as e:
                logger.debug(f"apply_chain_progress: {e}")
        return rec.to_dict() if rec else None

    def get_asset_clock(
        self,
        asset_id: str,
        *,
        manifest_hash: Optional[str] = None,
    ) -> ArtifactClock:
        asset_id = str(asset_id).strip().lower()
        if not manifest_hash:
            stored = self.comms.get_state(f"asset:manifest:{asset_id}")
            if isinstance(stored, dict):
                manifest_hash = stored.get("manifest_hash") or stored.get("content_hash") or asset_id
            else:
                manifest_hash = asset_id
        if not self.enabled:
            return ArtifactClock.unanchored(asset_id, manifest_hash)
        anc = self._get_anchor()
        if not anc:
            return ArtifactClock.unanchored(asset_id, manifest_hash)
        try:
            anc.apply_chain_progress()
        except Exception:
            pass
        rec = anc.get(asset_id)
        if not rec:
            return ArtifactClock.unanchored(asset_id, manifest_hash)
        return ArtifactClock.from_anchor_record(
            rec,
            manifest_hash=manifest_hash,
            confirmation_depth=getattr(anc, "confirmation_depth", 6),
        )

    def verify_asset_clock(
        self,
        asset_id: str,
        claimed: Optional[Union[ArtifactClock, Dict[str, Any]]] = None,
        *,
        manifest_hash: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verify a clock. Peer-supplied height/hash is evidence, not truth.
        """
        from mods.btc_anchor.verify import reject_peer_clock_claim, verify_anchor_record

        asset_id = str(asset_id).strip().lower()
        local = self.get_asset_clock(asset_id, manifest_hash=manifest_hash)
        anc = self._get_anchor() if self.enabled else None
        rec = anc.get(asset_id) if anc else None
        chain = getattr(anc, "chain", None) if anc else self._chain

        if claimed is None:
            if rec is None:
                return {
                    "ok": local.confidence == CONFIDENCE_NONE,
                    "accepted": False,
                    "reasons": [] if local.confidence == CONFIDENCE_NONE else ["unanchored"],
                    "clock": local.to_dict(),
                }
            checked = verify_anchor_record(
                rec,
                expected_asset_id=asset_id,
                expected_manifest_hash=manifest_hash or local.manifest_hash,
                chain=chain,
            )
            checked["clock"] = local.to_dict()
            return checked

        claim_d = claimed.to_dict() if hasattr(claimed, "to_dict") else dict(claimed)
        result = reject_peer_clock_claim(
            claim_d,
            local_record=rec,
            local_manifest_hash=manifest_hash or local.manifest_hash,
            chain=chain,
        )
        result["clock"] = local.to_dict()
        result["claimed"] = claim_d
        return result

    def handle_reorg(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": True, "updated": []}
        anc = self._get_anchor()
        if not anc:
            return {"ok": True, "updated": []}
        updated = anc.handle_reorg()
        return {"ok": True, "updated": [r.to_dict() for r in updated]}
