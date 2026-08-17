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

import logging
from typing import Any, Dict, Optional

from comms.layer import CommsLayer, SwarmMessage

logger = logging.getLogger("aurora.torrent.hooks")

# We keep a weak reference to a live CommsLayer if one was injected.
# In real deployments the host process usually has one already.
_comms: Optional[CommsLayer] = None


def set_comms(comms: CommsLayer):
    """Optional helper so the host can inject the live CommsLayer."""
    global _comms
    _comms = comms


def on_asset_needed(asset_info: Dict[str, Any], *args, **kwargs) -> None:
    """
    Hook entrypoint.

    Publishes an "asset.needed" event onto the mesh.
    Any running TorrentManager will pick it up and call start_download
    if it does not already have the complete file.
    """
    infohash = asset_info.get("infohash") or asset_info.get("hash")
    name = asset_info.get("name") or asset_info.get("asset")

    if not infohash and not name:
        logger.warning("on_asset_needed called without infohash or name — ignoring")
        return

    payload = {"infohash": infohash, "name": name, **asset_info}

    if _comms is not None:
        msg = SwarmMessage(
            type="asset.needed",
            payload=payload,
            source=_comms.node_id,
        )
        _comms.publish_message("asset.needed", msg)
        logger.info(f"Published asset.needed for {infohash or name}")
    else:
        # Fallback: just log. The host is expected to wire a live CommsLayer.
        logger.info(f"on_asset_needed (no live comms): {payload}")
