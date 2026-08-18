"""
AssetFabric — the public systems interface for swarm assets.

Primary verb:
    fabric.ensure(asset_id | manifest, policy=...)

Also:
    fabric.publish(..., important=True)  → RS encode + placement jobs
    fabric.swarm_possession(asset_id)
    fabric.publish_possession_snapshot()
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from comms.layer import CommsLayer
from .manifest_model import AssetManifest

logger = logging.getLogger("aurora.assets")

POSSESSION_KEY = "asset:possession:"
POSSESSION_TTL = 120


class AssetFabric:
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

    def publish(
        self,
        path: str | Path,
        *,
        name: Optional[str] = None,
        asset_type: str = "blob",
        provenance: Optional[Dict[str, Any]] = None,
        announce: bool = True,
        anchor: bool = False,
        important: bool = False,
    ) -> Optional[str]:
        try:
            tm = self._transport()
            meta = tm.create_torrent(path, name=name)
            if announce:
                tm.announce(meta.infohash)

            prov = dict(provenance or {})
            if important:
                try:
                    from mods.asset_fabric.important import encode_and_plan, write_shards
                    from mods.asset_fabric.repair import RepairPlanner, RedundancyPolicy
                    from mods.asset_fabric.topology import TopologyRegistry, load_topology_from_mesh
                    from mods.asset_fabric.possession_verify import PossessionTracker
                    from comms.layer import SwarmMessage

                    data = Path(path).read_bytes()
                    topo = TopologyRegistry()
                    load_topology_from_mesh(self.comms, topo)
                    planner = RepairPlanner(PossessionTracker(), topo, RedundancyPolicy())
                    candidates = []
                    try:
                        for n in (self.comms.get_active_nodes() or []):
                            if isinstance(n, dict):
                                candidates.append(n.get("node_id") or n.get("id"))
                            elif isinstance(n, str):
                                candidates.append(n)
                    except Exception:
                        pass
                    pack = encode_and_plan(
                        data,
                        asset_id=meta.infohash,
                        planner=planner,
                        candidates=[c for c in candidates if c],
                    )
                    shard_dir = Path(tm.storage_dir) / "shards"
                    paths = write_shards(shard_dir, meta.infohash, pack["shards"])
                    prov["important"] = True
                    prov["erasure"] = pack["encoding"]
                    prov["shard_paths"] = paths
                    prov["placement"] = pack.get("placement")
                    placement = pack.get("placement") or {}
                    for i, target in enumerate(placement.get("targets") or []):
                        msg = SwarmMessage(
                            type="asset.shard_place",
                            payload={
                                "asset_id": meta.infohash,
                                "target": target,
                                "shard_index": i,
                                "action": "hold_shard",
                                "source": self.node_id,
                            },
                            source=self.node_id,
                            target=target,
                        )
                        self.comms.publish_message("asset.shard_place", msg)
                    logger.info(
                        f"Important asset RS-encoded shards={pack['encoding']['shard_count']} "
                        f"code={pack['encoding']['code']}"
                    )
                except Exception as e:
                    logger.warning(f"important RS path failed (asset still published): {e}")

            manifest = AssetManifest.from_torrent_meta(
                meta, asset_type=asset_type, provenance=prov
            )
            self._store_manifest(manifest)

            if anchor:
                anc = self._get_anchor()
                if anc:
                    try:
                        anc.anchor_manifest(manifest)
                    except Exception as e:
                        logger.warning(f"Optional anchor failed (asset still published): {e}")

            self.publish_possession_snapshot()
            logger.info(
                f"Published asset {manifest.fingerprint()}… type={asset_type} "
                f"name={manifest.name} anchored={bool(anchor)} important={important}"
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
                self.publish_possession_snapshot()
                return True
            return bool(tm.ensure_asset(infohash=asset_id))
        except Exception as e:
            logger.warning(f"ensure({asset_id[:12]}…) failed: {e}")
            return False

    def possession(self, asset_id: str, *, include_swarm: bool = False) -> Dict[str, Any]:
        asset_id = str(asset_id).strip().lower()
        tm = self._transport()
        prog = tm.get_progress(asset_id)
        path = tm.get_path(asset_id)
        result: Dict[str, Any] = {
            "asset_id": asset_id,
            "complete": bool(prog.get("complete")),
            "percent": prog.get("percent", 0.0),
            "have": prog.get("have", 0),
            "total": prog.get("total", 0),
            "wanted": bool(prog.get("wanted")),
            "path": str(path) if path else None,
            "name": prog.get("name"),
            "anchor": None,
            "holders": None,
            "holder_count": None,
        }
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
        if include_swarm:
            swarm = self.swarm_possession(asset_id)
            result["holders"] = swarm.get("holders", [])
            result["holder_count"] = swarm.get("holder_count", 0)
        return result

    def list_assets(self) -> List[Dict[str, Any]]:
        tm = self._transport()
        out = []
        for t in tm.list_torrents():
            aid = t.get("infohash")
            if aid:
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

    def publish_possession_snapshot(self) -> Dict[str, Any]:
        tm = self._transport()
        complete_ids = []
        names = {}
        for t in tm.list_torrents():
            if t.get("complete") and t.get("infohash"):
                aid = t["infohash"]
                complete_ids.append(aid)
                if t.get("name"):
                    names[aid] = t["name"]
        payload = {
            "node_id": self.node_id,
            "assets": complete_ids,
            "names": names,
            "count": len(complete_ids),
            "updated_at": time.time(),
        }
        try:
            self.comms.set_state(f"{POSSESSION_KEY}{self.node_id}", payload, expire=POSSESSION_TTL)
        except Exception as e:
            logger.debug(f"publish_possession_snapshot failed: {e}")
        return payload

    def swarm_possession(self, asset_id: str) -> Dict[str, Any]:
        asset_id = str(asset_id).strip().lower()
        holders: List[str] = []
        try:
            keys = self.comms.r.keys(f"aurora:{POSSESSION_KEY}*") if hasattr(self.comms, "r") else []
            for k in keys[:200]:
                key = k.replace("aurora:", "", 1) if k.startswith("aurora:") else k
                raw = self.comms.get_state(key)
                if not isinstance(raw, dict):
                    continue
                node = raw.get("node_id") or key.split(":")[-1]
                if asset_id in (raw.get("assets") or []):
                    holders.append(str(node))
        except Exception as e:
            logger.debug(f"swarm_possession scan failed: {e}")
        if self.is_complete(asset_id) and self.node_id not in holders:
            holders.append(self.node_id)
        return {
            "asset_id": asset_id,
            "holders": sorted(set(holders)),
            "holder_count": len(set(holders)),
        }

    def list_swarm_assets(self, limit: int = 100) -> List[Dict[str, Any]]:
        inventory: Dict[str, Dict[str, Any]] = {}
        try:
            keys = self.comms.r.keys(f"aurora:{POSSESSION_KEY}*") if hasattr(self.comms, "r") else []
            for k in keys[:200]:
                key = k.replace("aurora:", "", 1) if k.startswith("aurora:") else k
                raw = self.comms.get_state(key)
                if not isinstance(raw, dict):
                    continue
                node = str(raw.get("node_id") or key.split(":")[-1])
                names = raw.get("names") or {}
                for aid in raw.get("assets") or []:
                    if aid not in inventory:
                        inventory[aid] = {"asset_id": aid, "name": names.get(aid), "holders": []}
                    if node not in inventory[aid]["holders"]:
                        inventory[aid]["holders"].append(node)
                    if not inventory[aid].get("name") and names.get(aid):
                        inventory[aid]["name"] = names[aid]
        except Exception as e:
            logger.debug(f"list_swarm_assets failed: {e}")
        out = []
        for aid, row in list(inventory.items())[:limit]:
            row["holder_count"] = len(row["holders"])
            out.append(row)
        out.sort(key=lambda r: (-r["holder_count"], r.get("name") or r["asset_id"]))
        return out

    def _store_manifest(self, manifest: AssetManifest):
        try:
            self.comms.set_state(
                f"asset:manifest:{manifest.asset_id}",
                manifest.to_dict(),
                expire=86400 * 7,
            )
        except Exception as e:
            logger.debug(f"Could not store manifest: {e}")
