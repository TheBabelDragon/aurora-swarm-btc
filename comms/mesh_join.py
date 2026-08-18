"""
Dual-node / LAN mesh: converge every node onto ONE Redis.

Problem: each machine defaults to redis://127.0.0.1 — isolated islands.
Fix: after LAN discovery, pick a deterministic leader (lowest node_id) and
reconnect every node to that leader's advertised Redis URL.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("aurora.comms.mesh_join")

_lock = threading.Lock()
_joined_url: Optional[str] = None


def _normalize(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _is_loopback_url(url: str) -> bool:
    u = (url or "").lower()
    return "127.0.0.1" in u or "localhost" in u or "://redis:" in u


def choose_leader_redis(
    self_node_id: str,
    self_redis_url: str,
    peers: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """Return (leader_node_id, redis_url). Lowest node_id wins."""
    from comms.discovery import public_redis_url

    entries: List[Tuple[str, str]] = []
    self_pub = public_redis_url(self_redis_url)
    entries.append((self_node_id, self_pub))
    for p in peers:
        nid = (p.get("node_id") or "").strip()
        ru = (p.get("redis_url") or "").strip()
        if not nid or not ru:
            continue
        entries.append((nid, ru))
    # stable: lowest node_id
    entries.sort(key=lambda x: x[0])
    return entries[0]


def try_join_mesh(comms: Any, *, force: bool = False) -> Dict[str, Any]:
    """Reconnect CommsLayer to leader Redis if needed. Safe to call often."""
    global _joined_url

    if os.getenv("AURORA_AUTO_MESH", "1").strip() in ("0", "false", "no") and not force:
        return {"ok": False, "skipped": True, "reason": "AURORA_AUTO_MESH disabled"}

    # Explicit override always wins
    forced = (os.getenv("AURORA_MESH_REDIS") or "").strip()
    if forced:
        target = forced
        leader = "env:AURORA_MESH_REDIS"
    else:
        peers: List[Dict[str, Any]] = []
        try:
            from comms.discovery import get_discovery

            d = get_discovery()
            if d:
                peers = d.snapshot_peers()
        except Exception as e:
            return {"ok": False, "error": f"discovery: {e}"}

        if not peers and not force:
            return {"ok": True, "joined": False, "reason": "no LAN peers yet"}

        leader, target = choose_leader_redis(comms.node_id, getattr(comms, "redis_url", ""), peers)

    target = _normalize(target)
    current = _normalize(getattr(comms, "redis_url", ""))

    # Already on target
    if target == current or target == _joined_url:
        return {
            "ok": True,
            "joined": False,
            "already": True,
            "redis_url": current,
            "leader": leader if not forced else leader,
        }

    # Don't leave a working multi-peer redis for a worse target unless force
    if not force and not _is_loopback_url(current):
        try:
            peers_now = len(comms.get_active_nodes() or [])
            if peers_now > 1:
                return {
                    "ok": True,
                    "joined": False,
                    "reason": "already on shared redis",
                    "peer_count": peers_now,
                    "redis_url": current,
                }
        except Exception:
            pass

    with _lock:
        try:
            if hasattr(comms, "reconnect"):
                ok = comms.reconnect(target)
            else:
                import redis as redis_lib

                comms.r = redis_lib.from_url(target, decode_responses=True, socket_connect_timeout=3)
                comms.redis_url = target
                ok = bool(comms.r.ping())
            if not ok:
                return {"ok": False, "error": f"ping failed for {target}"}
            _joined_url = target
            # Re-announce on the shared fabric
            try:
                comms.register_node(
                    node_type="dashboard",
                    capabilities=["dashboard", "mesh", "chat", "mining_engine"],
                    metadata={"mesh_joined": target},
                )
                comms.heartbeat(metadata={"status": "online"})
            except Exception:
                pass
            logger.info(f"mesh join → {target} leader={leader}")
            return {
                "ok": True,
                "joined": True,
                "redis_url": target,
                "leader": leader,
                "peers": len(comms.get_active_nodes() or []),
            }
        except Exception as e:
            logger.warning(f"mesh join failed: {e}")
            return {"ok": False, "error": str(e), "target": target}


def start_auto_mesh_join(get_comms: Callable[[], Any], interval: float = 8.0):
    def _loop():
        # wait for discovery beacons
        time.sleep(6)
        while True:
            try:
                try_join_mesh(get_comms())
            except Exception as e:
                logger.debug(f"auto mesh: {e}")
            time.sleep(interval)

    threading.Thread(target=_loop, name="auto-mesh-join", daemon=True).start()
    logger.info("auto mesh join started")
