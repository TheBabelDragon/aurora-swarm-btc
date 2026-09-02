"""
AssetFabric — the public systems interface for swarm assets.

User-facing conceptual API:

    ensure(asset)
    publish(asset)
    possession(asset)
    history(asset)
    clock(asset)
    verify(asset)

Torrent details stay behind this API.
Bitcoin is a temporal/scarcity layer, not a transport scheduler.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from comms.layer import CommsLayer
from .artifact_clock import ArtifactClock
from .history import (
    ANCHORED,
    ANNOUNCED,
    COMPLETE,
    PIECE_VERIFIED,
    POSSESSION_VERIFIED,
    PUBLISHED,
    REANCHORED,
    REQUESTED,
    ArtifactHistory,
)
from .manifest_model import AssetManifest

logger = logging.getLogger("aurora.assets")

POSSESSION_KEY = "asset:possession:"
POSSESSION_TTL = 120


class AssetFabric:
    def __init__(
        self,
        comms: CommsLayer,
        storage_dir: Optional[str] = None,
        *,
        chain: Any = None,
        btc_enabled: Optional[bool] = None,
        confirmation_depth: Optional[int] = None,
        transport: Any = None,
    ):
        self.comms = comms
        self.node_id = comms.node_id
        self._tm = transport
        self._storage_dir = storage_dir
        self._anchor = None
        self._anchor_tried = False
        self._chain = chain
        self._btc_enabled = btc_enabled
        self._confirmation_depth = confirmation_depth
        self._btc_clock = None
        self._history = ArtifactHistory(comms)
        # Local verified possession (independent of peer claims)
        try:
            from .possession_verify import PossessionTracker

            self.possession_tracker = PossessionTracker()
        except Exception:
            self.possession_tracker = None

    def _transport(self):
        if self._tm is None:
            from mods.torrent_protocol.torrent_manager import TorrentManager, register_torrent_capability
            register_torrent_capability(self.comms, extra_caps=["asset_fabric"])
            self._tm = TorrentManager(
                self.comms,
                storage_dir=self._storage_dir,
                auto_maintain=True,
            )
            self._install_complete_hook(self._tm)
        return self._tm

    def _install_complete_hook(self, tm) -> None:
        orig = getattr(tm, "on_complete", None)

        def _hook(infohash, path):
            try:
                self._on_local_complete(infohash, path)
            except Exception as e:
                logger.debug(f"complete hook: {e}")
            if orig:
                try:
                    orig(infohash, path)
                except Exception:
                    pass

        tm.on_complete = _hook

    def _get_anchor(self):
        if self._anchor_tried:
            return self._anchor
        self._anchor_tried = True
        try:
            from mods.btc_anchor.anchor import AssetAnchor
            from mods.btc_anchor.chain import NullChain

            chain = self._chain if self._chain is not None else NullChain()
            self._anchor = AssetAnchor(
                self.comms,
                chain=chain,
                confirmation_depth=self._confirmation_depth,
            )
        except Exception as e:
            logger.debug(f"btc_anchor not available: {e}")
            self._anchor = None
        return self._anchor

    def _clock_adapter(self):
        if self._btc_clock is None:
            from .btc_clock import BTCClock

            self._btc_clock = BTCClock(
                self.comms,
                chain=self._chain,
                confirmation_depth=self._confirmation_depth,
                enabled=self._btc_enabled,
                anchor=self._get_anchor() if self._btc_enabled is not False else None,
            )
        return self._btc_clock

    def register_manifest(self, manifest: AssetManifest) -> AssetManifest:
        """Store a content-addressed manifest without requiring torrent transfer."""
        self._store_manifest(manifest)
        clock = self.get_clock(manifest.asset_id)
        self._history.append(
            manifest.asset_id,
            PUBLISHED,
            manifest_hash=manifest.identity_hash(),
            epoch=clock.epoch,
            peer_id=self.node_id,
            payload={"name": manifest.name, "size": manifest.size},
        )
        return manifest

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
            manifest = AssetManifest.from_torrent_meta(
                meta, asset_type=asset_type, provenance=dict(provenance or {})
            )
            if announce:
                tm.announce(meta.infohash, temporal=self._announce_temporal(manifest))
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
            clock = self.get_clock(manifest.asset_id)
            self._history.append(
                manifest.asset_id,
                PUBLISHED,
                manifest_hash=manifest.identity_hash(),
                epoch=clock.epoch,
                peer_id=self.node_id,
                payload={"name": manifest.name, "size": manifest.size},
            )
            if announce:
                self._history.append(
                    manifest.asset_id,
                    ANNOUNCED,
                    manifest_hash=manifest.identity_hash(),
                    epoch=clock.epoch,
                    peer_id=self.node_id,
                    payload={"transport": "torrent"},
                )

            if self.possession_tracker:
                for idx in range(len(manifest.piece_hashes)):
                    self.possession_tracker.mark_verified_piece(
                        manifest.asset_id,
                        self.node_id,
                        idx,
                        total_pieces=len(manifest.piece_hashes),
                        manifest_hash=manifest.identity_hash(),
                        epoch=clock.epoch,
                        anchor_id=clock.anchor_id,
                    )
                self._history.append(
                    manifest.asset_id,
                    POSSESSION_VERIFIED,
                    manifest_hash=manifest.identity_hash(),
                    epoch=clock.epoch,
                    peer_id=self.node_id,
                    payload={"verified_pieces": len(manifest.piece_hashes), "local": True},
                )

            if anchor:
                try:
                    self.anchor_asset(manifest.asset_id)
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
        if isinstance(target, AssetManifest):
            self._store_manifest(target)
            asset_id = target.asset_id
            manifest_hash = target.identity_hash()
        else:
            asset_id = str(target).strip().lower()
            man = self.get_manifest(asset_id)
            manifest_hash = man.identity_hash() if man else asset_id
        clock = self.get_clock(asset_id)
        self._history.append(
            asset_id,
            REQUESTED,
            manifest_hash=manifest_hash,
            epoch=clock.epoch,
            peer_id=self.node_id,
            payload={"policy": policy},
        )
        if policy:
            logger.debug(f"ensure({asset_id[:12]}…) policy={policy}")
        try:
            tm = self._transport()
            if tm.is_complete(asset_id):
                self._record_local_verified_possession(asset_id)
                self.publish_possession_snapshot()
                return True
            return bool(tm.ensure_asset(infohash=asset_id))
        except Exception as e:
            logger.warning(f"ensure({asset_id[:12]}…) failed: {e}")
            return False

    def possession(self, asset_id: str, *, include_swarm: bool = False) -> Dict[str, Any]:
        """Temporally addressable possession. Claims ≠ verified history."""
        asset_id = str(asset_id).strip().lower()
        man = self.get_manifest(asset_id)
        manifest_hash = man.identity_hash() if man else asset_id
        clock = self.get_clock(asset_id)
        tm = None
        try:
            tm = self._transport()
        except Exception:
            tm = None
        prog = tm.get_progress(asset_id) if tm else {}
        path = tm.get_path(asset_id) if tm else None
        total = int(prog.get("total") or (len(man.piece_hashes) if man else 0))
        have = int(prog.get("have") or 0)
        local_complete = bool(prog.get("complete")) if tm else False
        verified = None
        if self.possession_tracker:
            verified = self.possession_tracker.evidence(asset_id, self.node_id)
        if verified:
            possession_state = verified.get("possession_state") or "partial"
            verified_pieces = verified.get("verified_pieces") or []
        elif local_complete:
            possession_state = "complete"
            verified_pieces = list(range(total))
        elif have:
            possession_state = "partial"
            verified_pieces = []
        else:
            possession_state = "none"
            verified_pieces = []
        result: Dict[str, Any] = {
            "asset_id": asset_id,
            "manifest_hash": manifest_hash,
            "peer_id": self.node_id,
            "possession_state": possession_state,
            "verified_pieces": verified_pieces,
            "total_pieces": total,
            "epoch": clock.epoch,
            "anchor_id": clock.anchor_id,
            "complete": possession_state == "complete",
            "percent": prog.get("percent", 0.0),
            "have": have,
            "total": total,
            "wanted": bool(prog.get("wanted")),
            "path": str(path) if path else None,
            "name": prog.get("name") or (man.name if man else None),
            "anchor": clock.to_dict(),
            "clock": clock.to_dict(),
            "holders": None,
            "holder_count": None,
            "verified": bool(verified) or local_complete,
        }
        if include_swarm:
            swarm = self.swarm_possession(asset_id)
            result["holders"] = swarm.get("holders", [])
            result["holder_count"] = swarm.get("holder_count", 0)
            result["claimed_holders"] = swarm.get("holders", [])
            result["verified_holders"] = (
                self.possession_tracker.verified_holders(asset_id) if self.possession_tracker else []
            )
        return result

    def get_possession(self, asset_id: str, **kwargs) -> Dict[str, Any]:
        return self.possession(asset_id, **kwargs)

    def get_clock(self, asset_id: str) -> ArtifactClock:
        man = self.get_manifest(asset_id)
        manifest_hash = man.identity_hash() if man else str(asset_id)
        return self._clock_adapter().get_asset_clock(asset_id, manifest_hash=manifest_hash)

    def clock(self, asset_id: str) -> ArtifactClock:
        return self.get_clock(asset_id)

    def get_history(self, asset_id: str) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self._history.get(asset_id)]

    def history(self, asset_id: str) -> List[Dict[str, Any]]:
        return self.get_history(asset_id)

    def verify_anchor(self, asset_id: str, claimed: Any = None) -> Dict[str, Any]:
        man = self.get_manifest(asset_id)
        manifest_hash = man.identity_hash() if man else None
        return self._clock_adapter().verify_asset_clock(
            asset_id, claimed=claimed, manifest_hash=manifest_hash
        )

    def verify(self, asset_id: str, claimed: Any = None) -> Dict[str, Any]:
        return self.verify_anchor(asset_id, claimed=claimed)

    def current_clock(self) -> Optional[Dict[str, Any]]:
        return self._clock_adapter().current_clock()

    def anchor_asset(self, asset_id: str, *, request_broadcast: bool = True) -> Optional[Dict[str, Any]]:
        man = self.get_manifest(asset_id)
        if not man:
            raise ValueError("unknown asset; publish or register a manifest first")
        rec = self._clock_adapter().anchor_asset(
            asset_id,
            manifest_hash=man.identity_hash(),
            manifest=man,
            request_broadcast=request_broadcast,
        )
        clock = self.get_clock(asset_id)
        temporal = {
            "clock_version": clock.clock_version,
            "anchor_id": clock.anchor_id,
            "btc_height": clock.btc_height,
            "btc_block_hash": clock.btc_block_hash,
            "btc_work": clock.btc_work,
            "anchored_at": clock.epoch,
        }
        self._store_manifest(man.with_temporal(temporal))
        prior = [e for e in self._history.get(asset_id) if e.event_type in (ANCHORED, REANCHORED)]
        self._history.append(
            asset_id,
            REANCHORED if prior else ANCHORED,
            manifest_hash=man.identity_hash(),
            epoch=clock.epoch,
            peer_id=self.node_id,
            payload={"anchor": rec, "clock": clock.to_dict()},
        )
        return rec

    def handle_reorg(self) -> Dict[str, Any]:
        result = self._clock_adapter().handle_reorg()
        for rec in result.get("updated") or []:
            aid = rec.get("asset_id")
            if not aid:
                continue
            man = self.get_manifest(aid)
            clock = self.get_clock(aid)
            self._history.append(
                aid,
                REANCHORED,
                manifest_hash=man.identity_hash() if man else clock.manifest_hash,
                epoch=clock.epoch,
                peer_id=self.node_id,
                payload={"reorg": True, "status": rec.get("status"), "observed": True},
            )
        return result

    def ingest_complete_event(self, payload: Dict[str, Any], *, verified: bool = False) -> Dict[str, Any]:
        """
        asset.complete means this peer reconstructed and verified the immutable artifact.
        It does NOT mean the artifact was created at this time.
        A peer emitting the event is not enough to become authoritative.
        """
        asset_id = str(payload.get("asset_id") or payload.get("infohash") or "").strip().lower()
        if not asset_id:
            return {"ok": False, "reason": "missing_asset_id"}
        if not verified:
            return {
                "ok": False,
                "accepted": False,
                "reason": "peer_claim_not_verified",
                "asset_id": asset_id,
            }
        man = self.get_manifest(asset_id)
        manifest_hash = (
            payload.get("manifest_hash")
            or (man.identity_hash() if man else asset_id)
        )
        clock = self.get_clock(asset_id)
        self._history.append(
            asset_id,
            COMPLETE,
            manifest_hash=manifest_hash,
            epoch=clock.epoch,
            peer_id=str(payload.get("peer_id") or payload.get("node_id") or ""),
            payload={
                "possession_proof": payload.get("possession_proof"),
                "btc_anchor": payload.get("btc_anchor") or clock.anchor_id,
                "local_verified": True,
            },
        )
        return {"ok": True, "accepted": True, "asset_id": asset_id, "epoch": clock.epoch}

    def record_piece_verified(
        self,
        asset_id: str,
        piece_index: int,
        *,
        peer_id: Optional[str] = None,
        total_pieces: int = 0,
    ) -> None:
        man = self.get_manifest(asset_id)
        manifest_hash = man.identity_hash() if man else asset_id
        clock = self.get_clock(asset_id)
        if self.possession_tracker:
            self.possession_tracker.mark_verified_piece(
                asset_id,
                peer_id or self.node_id,
                piece_index,
                total_pieces=total_pieces or (len(man.piece_hashes) if man else 0),
                manifest_hash=manifest_hash,
                epoch=clock.epoch,
                anchor_id=clock.anchor_id,
            )
        self._history.append(
            asset_id,
            PIECE_VERIFIED,
            manifest_hash=manifest_hash,
            epoch=clock.epoch,
            peer_id=peer_id or self.node_id,
            payload={"piece_index": piece_index},
        )

    def list_assets(self) -> List[Dict[str, Any]]:
        out = []
        seen = set()
        try:
            tm = self._transport()
            for t in tm.list_torrents():
                aid = t.get("infohash")
                if aid:
                    seen.add(aid)
                    out.append(self.possession(aid))
        except Exception:
            pass
        try:
            keys = self.comms.r.keys("aurora:asset:manifest:*") if hasattr(self.comms, "r") else []
            for k in keys[:200]:
                key = k.replace("aurora:", "", 1) if str(k).startswith("aurora:") else k
                aid = key.split(":")[-1]
                if aid and aid not in seen:
                    out.append(self.possession(aid))
        except Exception:
            pass
        return out

    def get_manifest(self, asset_id: str) -> Optional[AssetManifest]:
        try:
            raw = self.comms.get_state(f"asset:manifest:{asset_id}")
            if raw and isinstance(raw, dict):
                return AssetManifest.from_dict(raw)
        except Exception:
            pass
        tm = self._tm
        if tm is None:
            return None
        meta = tm.torrents.get(asset_id) if hasattr(tm, "torrents") else None
        if meta:
            return AssetManifest.from_torrent_meta(meta)
        return None

    def is_complete(self, asset_id: str) -> bool:
        try:
            return self._transport().is_complete(str(asset_id).strip().lower())
        except Exception:
            return False

    def path(self, asset_id: str) -> Optional[Path]:
        try:
            return self._transport().get_path(str(asset_id).strip().lower())
        except Exception:
            return None

    def publish_possession_snapshot(self) -> Dict[str, Any]:
        complete_ids = []
        names = {}
        try:
            tm = self._transport()
            for t in tm.list_torrents():
                if t.get("complete") and t.get("infohash"):
                    aid = t["infohash"]
                    complete_ids.append(aid)
                    if t.get("name"):
                        names[aid] = t["name"]
        except Exception:
            pass
        payload = {
            "node_id": self.node_id,
            "assets": complete_ids,
            "names": names,
            "count": len(complete_ids),
            "updated_at": 0,  # observational field left unset as wall-clock-not-epoch
        }
        try:
            import time as _t

            payload["updated_at"] = _t.time()
        except Exception:
            pass
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

    def _announce_temporal(self, manifest: AssetManifest) -> Dict[str, Any]:
        clock = self.get_clock(manifest.asset_id)
        return {
            "asset_id": manifest.asset_id,
            "manifest_hash": manifest.identity_hash(),
            "epoch": clock.epoch,
            "anchor_id": clock.anchor_id,
        }

    def _record_local_verified_possession(self, asset_id: str) -> None:
        man = self.get_manifest(asset_id)
        if not man or not self.possession_tracker:
            return
        clock = self.get_clock(asset_id)
        for idx in range(len(man.piece_hashes)):
            self.possession_tracker.mark_verified_piece(
                asset_id,
                self.node_id,
                idx,
                total_pieces=len(man.piece_hashes),
                manifest_hash=man.identity_hash(),
                epoch=clock.epoch,
                anchor_id=clock.anchor_id,
            )

    def _on_local_complete(self, infohash: str, path: Any) -> None:
        self._record_local_verified_possession(infohash)
        man = self.get_manifest(infohash)
        clock = self.get_clock(infohash)
        payload = {
            "asset_id": infohash,
            "manifest_hash": man.identity_hash() if man else infohash,
            "peer_id": self.node_id,
            "possession_proof": {
                "complete": True,
                "path": str(path) if path else "",
            },
            "epoch": clock.epoch,
            "btc_anchor": clock.anchor_id,
        }
        self.ingest_complete_event(payload, verified=True)
        self.publish_possession_snapshot()

    def _store_manifest(self, manifest: AssetManifest):
        try:
            self.comms.set_state(
                f"asset:manifest:{manifest.asset_id}",
                manifest.to_dict(),
                expire=86400 * 7,
            )
        except Exception as e:
            logger.debug(f"Could not store manifest: {e}")
