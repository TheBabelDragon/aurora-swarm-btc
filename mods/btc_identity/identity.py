"""
Bitcoin-style node identity for the Aurora mesh.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

from comms.layer import CommsLayer

from .keys import NodeKey, load_or_create, sign_message

logger = logging.getLogger("aurora.btc_identity")


class NodeIdentity:
    def __init__(self, comms: CommsLayer, key_path: Optional[str] = None):
        self.comms = comms
        self.node_id = comms.node_id
        self.key: NodeKey = load_or_create(key_path)
        logger.info(
            f"NodeIdentity backend={self.key.backend} fingerprint={self.key.fingerprint} "
            f"label={self.key.address_style[:20]}…"
        )

    def claim_payload(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = {
            "node_id": self.node_id,
            "fingerprint": self.key.fingerprint,
            "public_hex": self.key.public_hex,
            "address_style": self.key.address_style,
            "backend": self.key.backend,
            "ts": int(time.time()),
        }
        if extra:
            body["extra"] = extra
        msg = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        body["sig"] = sign_message(self.key, msg)
        return body

    def register_with_identity(self, capabilities: Optional[list] = None, metadata: Optional[Dict] = None):
        """Re-register on the mesh with identity metadata attached. Never wipe prior caps."""
        meta = dict(metadata or {})
        claim = self.claim_payload()
        meta["btc_identity"] = {
            "fingerprint": claim["fingerprint"],
            "address_style": claim["address_style"],
            "public_hex": claim["public_hex"],
            "backend": claim["backend"],
            "sig": claim["sig"],
            "ts": claim["ts"],
        }
        try:
            existing = []
            try:
                prev = self.comms.get_state(f"node:{self.node_id}") or {}
                if isinstance(prev, dict):
                    existing = list(prev.get("capabilities") or [])
                    for k, v in (prev.get("metadata") or {}).items():
                        meta.setdefault(k, v)
            except Exception:
                pass
            caps = list(dict.fromkeys(existing + list(capabilities or []) + ["btc_identity"]))
            if "dashboard" not in caps:
                caps.append("dashboard")
            self.comms.register_node(
                node_type="dashboard",
                capabilities=caps,
                metadata=meta,
            )
            # Persistent on shared Redis
            self.comms.set_state(
                f"node:identity:{self.node_id}",
                meta["btc_identity"],
                expire=0,
            )
            logger.info(f"Registered identity for {self.node_id} caps={caps}")
            return meta["btc_identity"]
        except Exception as e:
            logger.warning(f"register_with_identity failed: {e}")
            raise

    def identity_view(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "fingerprint": self.key.fingerprint,
            "address_style": self.key.address_style,
            "backend": self.key.backend,
            "public_hex": self.key.public_hex[:24] + "…",
        }


# Back-compat alias — old dashboard imported IdentityService
IdentityService = NodeIdentity
