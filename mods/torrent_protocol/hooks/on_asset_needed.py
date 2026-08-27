"""
on_asset_needed hook

Called by the scheduler (or any other component) when a large asset
is required. Publishes a mesh event so every TorrentManager that is
listening can decide whether to start (or continue) the download.

Expected payload examples:
    {"infohash": "abc123..."}
    {"name": "big_model.pt", "infohash": "abc123..."}
    {"asset": "gpu_kernel_v3", "infohash": "..."}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("aurora.torrent.hooks")

# Weak handle to a live CommsLayer if the host injected one.
_comms = None


def set_comms(comms: Any) -> None:
    """Optional helper so the host can inject the live CommsLayer."""
    global _comms
    _comms = comms


def on_asset_needed(asset_info: Dict[str, Any], *args, **kwargs) -> None:
    """Publish an asset.needed event onto the mesh when comms is available."""
    infohash = asset_info.get("infohash") or asset_info.get("hash")
    name = asset_info.get("name") or asset_info.get("asset")

    if not infohash and not name:
        logger.warning("on_asset_needed called without infohash or name — ignoring")
        return

    payload = {"infohash": infohash, "name": name, **asset_info}

    if _comms is None:
        logger.info("on_asset_needed (no live comms): %s", payload)
        return

    try:
        from comms.layer import SwarmMessage

        msg = SwarmMessage(
            type="asset.needed",
            payload=payload,
            source=getattr(_comms, "node_id", "torrent"),
        )
        _comms.publish_message("asset.needed", msg)
        logger.info("Published asset.needed for %s", infohash or name)
    except Exception as exc:
        logger.info("on_asset_needed (comms unavailable: %s): %s", exc, payload)
