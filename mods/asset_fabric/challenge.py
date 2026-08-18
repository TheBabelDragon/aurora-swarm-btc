"""
Mesh piece challenges — claimed possession → verified possession.

Node A: "I have pieces …"
Node B: challenge(piece_index) → bytes + optional proof
Node B: verify against manifest Merkle root → update evidence
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional

from comms.layer import CommsLayer, SwarmMessage

from .merkle_pieces import verify_piece
from .peer_evidence import PeerEvidence
from .possession_verify import PossessionTracker

logger = logging.getLogger("aurora.assets.challenge")

CHALLENGE_TIMEOUT = 12.0


class PieceChallenger:
    def __init__(
        self,
        comms: CommsLayer,
        *,
        get_piece: Callable[[str, int], Optional[bytes]],
        get_meta: Callable[[str], Optional[Dict[str, Any]]],
        peer_evidence: Optional[PeerEvidence] = None,
        possession: Optional[PossessionTracker] = None,
    ):
        self.comms = comms
        self.node_id = comms.node_id
        self.get_piece = get_piece
        self.get_meta = get_meta
        self.peer_evidence = peer_evidence or PeerEvidence()
        self.possession = possession or PossessionTracker()
        self._pending: Dict[str, Dict[str, Any]] = {}

        self.comms.subscribe("asset.challenge", self._on_challenge)
        self.comms.subscribe("asset.challenge_response", self._on_response)

    def challenge(
        self,
        asset_id: str,
        piece_index: int,
        target_node: str,
        *,
        timeout: float = CHALLENGE_TIMEOUT,
    ) -> bool:
        """
        Ask target_node to prove piece_index. Blocks up to timeout.
        Returns True if verified.
        """
        cid = uuid.uuid4().hex[:16]
        event = {"done": False, "ok": False}
        self._pending[cid] = event

        msg = SwarmMessage(
            type="asset.challenge",
            payload={
                "challenge_id": cid,
                "asset_id": asset_id,
                "piece_index": piece_index,
            },
            source=self.node_id,
            target=target_node,
        )
        try:
            self.comms.publish_message("asset.challenge", msg)
        except Exception as e:
            logger.warning(f"challenge publish failed: {e}")
            self._pending.pop(cid, None)
            return False

        deadline = time.time() + timeout
        while time.time() < deadline:
            if event["done"]:
                self._pending.pop(cid, None)
                return bool(event["ok"])
            time.sleep(0.05)

        self._pending.pop(cid, None)
        self.peer_evidence.record_timeout(target_node)
        logger.info(f"Challenge timeout asset={asset_id[:12]}… piece={piece_index} node={target_node}")
        return False

    def _on_challenge(self, msg: SwarmMessage):
        try:
            if msg.target and msg.target != self.node_id:
                return
            if msg.source == self.node_id:
                return
            payload = msg.payload or {}
            cid = payload.get("challenge_id")
            asset_id = payload.get("asset_id")
            idx = payload.get("piece_index")
            if cid is None or asset_id is None or idx is None:
                return
            idx = int(idx)
            data = self.get_piece(str(asset_id), idx)
            if not data:
                # explicit fail so challenger can score
                reply = SwarmMessage(
                    type="asset.challenge_response",
                    payload={
                        "challenge_id": cid,
                        "asset_id": asset_id,
                        "piece_index": idx,
                        "ok": False,
                        "error": "not_held",
                    },
                    source=self.node_id,
                    target=msg.source,
                )
                self.comms.publish_message("asset.challenge_response", reply)
                return

            reply = SwarmMessage(
                type="asset.challenge_response",
                payload={
                    "challenge_id": cid,
                    "asset_id": asset_id,
                    "piece_index": idx,
                    "ok": True,
                    "data": data.hex(),
                    "hash": __import__("hashlib").sha256(data).hexdigest(),
                },
                source=self.node_id,
                target=msg.source,
            )
            self.comms.publish_message("asset.challenge_response", reply)
        except Exception as e:
            logger.debug(f"_on_challenge: {e}")

    def _on_response(self, msg: SwarmMessage):
        try:
            if msg.target and msg.target != self.node_id:
                return
            payload = msg.payload or {}
            cid = payload.get("challenge_id")
            if not cid or cid not in self._pending:
                return

            event = self._pending[cid]
            src = msg.source or "unknown"
            asset_id = str(payload.get("asset_id") or "")
            idx = int(payload.get("piece_index") or 0)

            if not payload.get("ok"):
                self.peer_evidence.record_failed_challenge(src)
                event["ok"] = False
                event["done"] = True
                return

            data_hex = payload.get("data")
            if not data_hex:
                self.peer_evidence.record_failed_challenge(src)
                event["ok"] = False
                event["done"] = True
                return

            data = bytes.fromhex(data_hex)
            meta = self.get_meta(asset_id) or {}
            hashes = meta.get("piece_hashes") or []
            root = meta.get("merkle_root") or ""

            ok = False
            if hashes and root:
                try:
                    ok = verify_piece(data, idx, hashes, root)
                except Exception:
                    ok = False
            elif hashes and idx < len(hashes):
                import hashlib

                ok = hashlib.sha256(data).hexdigest() == hashes[idx]

            if ok:
                self.peer_evidence.record_success(src)
                self.possession.mark_verified_piece(asset_id, src, idx)
            else:
                self.peer_evidence.record_invalid_piece(src, "challenge_verify_failed")
                self.peer_evidence.record_failed_challenge(src)

            event["ok"] = ok
            event["done"] = True
        except Exception as e:
            logger.debug(f"_on_response: {e}")
