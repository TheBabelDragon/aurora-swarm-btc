"""
AssetFabric — the public systems interface for swarm assets.

This is the language the rest of Aurora should speak.

Primary verb:
    fabric.ensure(asset_id | manifest, policy=...)

Under the hood the current implementation uses torrent_protocol's
TorrentManager for piece distribution. That is an implementation detail.
Callers should not depend on pieces, infohashes, or rarest-first directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from comms.layer import CommsLayer
from .manifest_model import AssetManifest

logger = logging.getLogger("aurora.assets")


class AssetFabric:
    """
    High-level swarm asset interface.

    Usage:
        fabric = AssetFabric(comms)
        asset_id = fabric.publish("/path/to/model.pt", asset_type="model")
        fabric.ensure(asset_id)
        print(fabric.possession(asset_id))

        # Optional attestation at publish time:
        asset_id = fabric.publish("/path/to/model.pt", asset_type="model", anchor=True)
    """

    def __init__(self, comms: CommsLayer, storage_dir: Optional[str] = None):
        self.comms = comms
        self.node_id = comms.node_id
        self._tm = None
        self._storage_dir = storage_dir
        self._anchor = None
        self._anchor_tried = False

    def _transport(self):
        if self._tm is None:
            from mods.torrent_protocol.torrent_manager import TorrentManager, register_torrent_capability
            register_torrent_capability(self.comms, extra_caps=["asset_fabric"])
            self._tm = TorrentManager(
                self.comms,
                storage_dir=self._storage_dir,
                auto_maintain=True,
            )
        return self._tm

    def _get_anchor(self):
        """Soft dependency on btc_anchor — never required for basic operation."""
        if self._anchor_tried:
            return self._anchor
        self._anchor_tried = True
        try:
            from mods.btc_anchor.anchor import AssetAnchor
            self._anchor = AssetAnchor(self.comms)
        except Exception as e:
            logger.debug(f"btc_anchor not available: {e}")
            self._anchor = None
        return self._anchor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish(
        self,
        path: str | Path,
        *,
        name: Optional[str] = None,
        asset_type: str = "blob",
        provenance: Optional[Dict[str, Any]] = None,
        announce: bool = True,
        anchor: bool = False,
    ) -> Optional[str]:
        """
        Turn a local file into a swarm asset and (by default) announce it.

        If anchor=True and btc_anchor is available, also records a content
        commitment on the mesh (optional path toward on-chain attestation).

        Returns asset_id or None on failure.
        """
        try:
            tm = self._transport()
            meta = tm.create_torrent(path, name=name)
            if announce:
                tm.announce(meta.infohash)

            manifest = AssetManifest.from_torrent_meta(
                meta, asset_type=asset_type, provenance=provenance
            )
            self._store_manifest(manifest)

            if anchor:
                anc = self._get_anchor()
                if anc:
                    try:
                        anc.anchor_manifest(manifest)
                    except Exception as e:
                        logger.warning(f"Optional anchor failed (asset still published): {e}")
                else:
                    logger.debug("anchor=True requested but btc_anchor not loaded")

            logger.info(
                f"Published asset {manifest.fingerprint()}… type={asset_type} "
                f"name={manifest.name} anchored={bool(anchor)}"
            )
            return manifest.asset_id
        except Exception as e:
            logger.exception(f"publish failed: {e}")
            return None

    def ensure(
        self,
        target: Union[str, AssetManifest],
        *,
        policy: Optional[Dict[str, Any]] = None,
    ) -> bool:
        policy = policy or {}
        asset_id = target.asset_id if isinstance(target, AssetManifest) else str(target).strip().lower()

        if policy:
            logger.debug(f"ensure({asset_id[:12]}…) policy={policy}")

        try:
            tm = self._transport()
            if tm.is_complete(asset_id):
                return True
            return bool(tm.ensure_asset(infohash=asset_id))
        except Exception as e:
            logger.warning(f"ensure({asset_id[:12]}…) failed: {e}")
            return False

    def possession(self, asset_id: str) -> Dict[str, Any]:
        asset_id = str(asset_id).strip().lower()
        tm = self._transport()
        prog = tm.get_progress(asset_id)
        path = tm.get_path(asset_id)

        result = {
            "asset_id": asset_id,
            "complete": bool(prog.get("complete")),
            "percent": prog.get("percent", 0.0),
            "have": prog.get("have", 0),
            "total": prog.get("total", 0),
            "wanted": bool(prog.get("wanted")),
            "path": str(path) if path else None,
            "name": prog.get("name"),
            "anchor": None,
        }

        # Soft-enrich with attestation status when available
        anc = self._get_anchor()
        if anc:
            try:
                rec = anc.get(asset_id)
                if rec:
                    result["anchor"] = {
                        "status": rec.status,
                        "commitment": rec.commitment,
                        "txid": rec.txid,
                        "method": rec.method,
                        "created_at": rec.created_at,
                    }
            except Exception:
                pass

        return result

    def list_assets(self) -> List[Dict[str, Any]]:
        tm = self._transport()
        out = []
        for t in tm.list_torrents():
            aid = t.get("infohash")
            if not aid:
                continue
            out.append(self.possession(aid))
        return out

    def get_manifest(self, asset_id: str) -> Optional[AssetManifest]:
        try:
            raw = self.comms.get_state(f"asset:manifest:{asset_id}")
            if raw and isinstance(raw, dict):
                return AssetManifest.from_dict(raw)
        except Exception:
            pass
        tm = self._transport()
        meta = tm.torrents.get(asset_id)
        if meta:
            return AssetManifest.from_torrent_meta(meta)
        return None

    def is_complete(self, asset_id: str) -> bool:
        return self._transport().is_complete(str(asset_id).strip().lower())

    def path(self, asset_id: str) -> Optional[Path]:
        return self._transport().get_path(str(asset_id).strip().lower())

    def _store_manifest(self, manifest: AssetManifest):
        try:
            self.comms.set_state(
                f"asset:manifest:{manifest.asset_id}",
                manifest.to_dict(),
                expire=86400 * 7,
            )
        except Exception as e:
            logger.debug(f"Could not store manifest: {e}")
