"""Replace misleading torrent status. No open BVL mint."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("aurora-dashboard.truth")


def install_truth_routes(
    app: Any,
    *,
    get_comms: Callable[[], Any],
    get_torrent_manager: Callable[[], Any],
    get_fabric: Callable[[], Any],
    get_anchor: Callable[[], Any],
):
    try:
        app.router.routes = [
            r
            for r in app.router.routes
            if not (
                getattr(r, "path", None) == "/torrent/status"
                and "GET" in (getattr(r, "methods", set()) or set())
            )
        ]
    except Exception as e:
        logger.warning(f"could not prune old torrent status: {e}")

    @app.get("/torrent/status")
    def torrent_status_truth():
        comms = get_comms()
        tm = get_torrent_manager()
        fabric = get_fabric()
        if tm:
            try:
                from mods.torrent_protocol.torrent_manager import register_torrent_capability

                register_torrent_capability(comms, extra_caps=["dashboard", "torrent"])
            except Exception as e:
                logger.debug(f"re-register torrent: {e}")

        torrent_nodes = []
        if hasattr(comms, "get_nodes_by_capability"):
            try:
                torrent_nodes = comms.get_nodes_by_capability("torrent") or []
            except Exception:
                torrent_nodes = []

        if fabric:
            try:
                fabric.publish_possession_snapshot()
            except Exception:
                pass

        local = []
        if tm:
            try:
                local = tm.list_torrents()
            except Exception as e:
                logger.warning(f"list_torrents: {e}")

        announced = []
        try:
            keys = comms.r.keys("aurora:torrent:*") if hasattr(comms, "r") else []
            for k in keys[:60]:
                key = k.replace("aurora:", "", 1) if str(k).startswith("aurora:") else k
                raw = comms.get_state(key)
                if isinstance(raw, dict) and "infohash" in raw:
                    announced.append(
                        {
                            "infohash": raw.get("infohash"),
                            "name": raw.get("name"),
                            "size": raw.get("size"),
                            "num_pieces": raw.get("num_pieces")
                            or len(raw.get("piece_hashes", [])),
                            "created_by": raw.get("created_by"),
                        }
                    )
        except Exception as e:
            logger.debug(f"scan announced: {e}")

        downloading = [t for t in local if not t.get("complete")]
        seeding = [t for t in local if t.get("complete")]
        capable_count = len(torrent_nodes)
        if tm is not None and capable_count == 0:
            capable_count = 1

        artifacts = []
        if fabric:
            try:
                for row in fabric.list_assets():
                    clock = row.get("clock") or {}
                    artifacts.append(
                        {
                            "asset": row.get("name") or (row.get("asset_id") or "")[:12],
                            "asset_id": row.get("asset_id"),
                            "pieces": f"{row.get('have', 0)}/{row.get('total', 0)}",
                            "possession": row.get("possession_state"),
                            "epoch": clock.get("epoch"),
                            "btc_height": clock.get("btc_height"),
                            "anchor_status": clock.get("confidence"),
                            "confirmations": (row.get("anchor") or {}).get("confirmations"),
                            "canonical": clock.get("confidence") == "confirmed",
                            "reorged": clock.get("confidence") == "reorged",
                        }
                    )
            except Exception as e:
                logger.debug(f"artifact clock rows: {e}")

        note = ""
        if not tm:
            note = "torrent manager offline"
        elif not local:
            note = "no local torrents yet — upload to seed"

        chain = None
        if fabric and hasattr(fabric, "current_clock"):
            try:
                chain = fabric.current_clock()
            except Exception:
                chain = None

        return {
            "torrent_capable_nodes": capable_count,
            "torrent_nodes": [
                {"node_id": n.get("node_id"), "capabilities": n.get("capabilities")}
                for n in torrent_nodes
            ],
            "local_torrents": local,
            "downloading": downloading,
            "seeding": seeding,
            "announced_torrents": announced,
            "artifacts": artifacts,
            "chain": chain,
            "dashboard_has_manager": tm is not None,
            "dashboard_has_anchor": get_anchor() is not None,
            "dashboard_has_fabric": fabric is not None,
            "note": note,
        }

    logger.info("truth routes installed (no open mint)")
