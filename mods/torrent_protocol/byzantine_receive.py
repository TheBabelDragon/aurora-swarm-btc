"""
Byzantine verify-on-receive for TorrentManager.

Wraps _on_piece_data so invalid pieces never enter local state.
Also attaches PieceChallenger, topology, RepairPlanner, RepairExecutor,
and optional EpochTicker (AURORA_EPOCH_TICK=1).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger("aurora.torrent.byz")


def _try_imports():
    try:
        from mods.asset_fabric.merkle_pieces import (
            merkle_root_from_piece_hashes,
            verify_piece,
        )
        from mods.asset_fabric.peer_evidence import PeerEvidence
        from mods.asset_fabric.possession_verify import PossessionTracker

        return merkle_root_from_piece_hashes, verify_piece, PeerEvidence, PossessionTracker
    except Exception as e:
        logger.debug(f"byzantine helpers unavailable: {e}")
        return None, None, None, None


def attach_byzantine_receive(manager: Any) -> bool:
    merkle_root_from_piece_hashes, verify_piece, PeerEvidence, PossessionTracker = _try_imports()
    if not verify_piece:
        return False

    if PeerEvidence and not getattr(manager, "peer_evidence", None):
        manager.peer_evidence = PeerEvidence()
    if PossessionTracker and not getattr(manager, "possession", None):
        manager.possession = PossessionTracker()

    orig_create = manager.create_torrent

    def create_torrent_wrapped(*args, **kwargs):
        meta = orig_create(*args, **kwargs)
        if merkle_root_from_piece_hashes and not getattr(meta, "merkle_root", None):
            try:
                meta.merkle_root = merkle_root_from_piece_hashes(meta.piece_hashes)
            except Exception:
                pass
        return meta

    manager.create_torrent = create_torrent_wrapped  # type: ignore

    orig_on_piece = manager._on_piece_data

    def on_piece_data_wrapped(msg):
        try:
            if getattr(msg, "source", None) == manager.node_id:
                return
            if getattr(msg, "target", None) and msg.target != manager.node_id:
                return

            payload = msg.payload or {}
            infohash = payload.get("infohash")
            idx = payload.get("piece_index")
            data_hex = payload.get("data")
            expected_hash = payload.get("hash")
            if not all([infohash, idx is not None, data_hex, expected_hash]):
                return
            idx = int(idx)
            try:
                data = bytes.fromhex(data_hex)
            except ValueError:
                return

            src = msg.source or "unknown"

            if hashlib.sha256(data).hexdigest() != expected_hash:
                if getattr(manager, "peer_evidence", None):
                    manager.peer_evidence.record_invalid_piece(src, "payload_hash_mismatch")
                return

            meta = manager.torrents.get(infohash)
            if not meta or idx >= len(meta.piece_hashes):
                return
            if expected_hash != meta.piece_hashes[idx]:
                if getattr(manager, "peer_evidence", None):
                    manager.peer_evidence.record_invalid_piece(src, "manifest_slot_mismatch")
                return

            root = getattr(meta, "merkle_root", None) or ""
            if not root and merkle_root_from_piece_hashes:
                try:
                    root = merkle_root_from_piece_hashes(meta.piece_hashes)
                    meta.merkle_root = root
                except Exception:
                    root = ""

            if root:
                try:
                    ok = verify_piece(data, idx, meta.piece_hashes, root)
                except Exception:
                    ok = False
                if not ok:
                    logger.warning(f"INVALID_PIECE {str(infohash)[:12]}[{idx}] from {src}")
                    if getattr(manager, "peer_evidence", None):
                        manager.peer_evidence.record_invalid_piece(src, "merkle_verify_failed")
                    return

            before = set(manager.have.get(infohash, set()))
            orig_on_piece(msg)
            after = set(manager.have.get(infohash, set()))
            if idx in after and idx not in before:
                if getattr(manager, "peer_evidence", None):
                    manager.peer_evidence.record_success(src)
                if getattr(manager, "possession", None):
                    manager.possession.mark_verified_piece(infohash, src, idx)
        except Exception as e:
            logger.debug(f"byzantine on_piece_data: {e}")
            try:
                orig_on_piece(msg)
            except Exception:
                pass

    manager._on_piece_data = on_piece_data_wrapped  # type: ignore

    orig_assemble = manager._assemble_and_finish

    def assemble_wrapped(infohash: str):
        orig_assemble(infohash)
        try:
            from comms.layer import SwarmMessage

            meta = manager.torrents.get(infohash)
            path = manager.get_path(infohash)
            msg = SwarmMessage(
                type="asset.complete",
                payload={
                    "infohash": infohash,
                    "asset_id": infohash,
                    "name": meta.name if meta else "",
                    "size": meta.size if meta else 0,
                    "node_id": manager.node_id,
                    "path": str(path) if path else "",
                },
                source=manager.node_id,
            )
            manager.comms.publish_message("asset.complete", msg)
        except Exception as e:
            logger.debug(f"asset.complete: {e}")

    manager._assemble_and_finish = assemble_wrapped  # type: ignore

    try:
        from mods.asset_fabric.challenge import PieceChallenger

        def _get_piece(asset_id: str, idx: int) -> Optional[bytes]:
            data = manager.pieces.get(asset_id, {}).get(idx)
            if data:
                return data
            p = manager._piece_path(asset_id, idx)
            if p.exists():
                return p.read_bytes()
            meta = manager.torrents.get(asset_id)
            complete = manager._complete_path(asset_id, meta.name if meta else None)
            if complete and complete.exists() and meta:
                blob = complete.read_bytes()
                start = idx * meta.piece_size
                return blob[start : start + meta.piece_size]
            return None

        def _get_meta(asset_id: str):
            meta = manager.torrents.get(asset_id)
            return meta.to_dict() if meta else None

        manager.challenger = PieceChallenger(
            manager.comms,
            get_piece=_get_piece,
            get_meta=_get_meta,
            peer_evidence=manager.peer_evidence,
            possession=manager.possession,
        )
    except Exception as e:
        logger.debug(f"PieceChallenger not attached: {e}")

    try:
        from mods.asset_fabric.topology import TopologyRegistry, publish_topology, load_topology_from_mesh
        from mods.asset_fabric.repair import RepairPlanner, RedundancyPolicy

        topo = publish_topology(manager.comms)
        registry = TopologyRegistry()
        registry.upsert(topo)
        load_topology_from_mesh(manager.comms, registry)
        manager.topology = registry
        manager.repair_planner = RepairPlanner(
            manager.possession,
            registry,
            RedundancyPolicy(),
        )
        try:
            from mods.asset_fabric.repair_executor import RepairExecutor

            def _candidates():
                try:
                    nodes = manager.comms.get_active_nodes() or []
                    out = []
                    for n in nodes:
                        if isinstance(n, dict):
                            out.append(n.get("node_id") or n.get("id"))
                        elif isinstance(n, str):
                            out.append(n)
                    return [x for x in out if x]
                except Exception:
                    return []

            manager.repair_executor = RepairExecutor(
                manager.comms,
                manager.repair_planner,
                list_candidates=_candidates,
            )
        except Exception as e:
            logger.debug(f"RepairExecutor not attached: {e}")
        logger.info(
            f"Topology published site={topo.site} power={topo.power} "
            f"net={topo.network} rack={topo.rack}"
        )
    except Exception as e:
        logger.debug(f"topology/repair not attached: {e}")

    try:
        from mods.asset_fabric.epoch_tick import start_epoch_ticker

        manager.epoch_ticker = start_epoch_ticker(
            manager.comms,
            possession=getattr(manager, "possession", None),
            topology_registry=getattr(manager, "topology", None),
            policy=getattr(getattr(manager, "repair_planner", None), "policy", None),
        )
    except Exception as e:
        logger.debug(f"epoch ticker not attached: {e}")

    logger.info(f"Byzantine verify-on-receive attached on {manager.node_id}")
    return True
