"""
Dual-node / LAN mesh: converge every node onto ONE Redis.
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
    from comms.discovery import public_redis_url

    entries: List[Tuple[str, str]] = []
    self_pub = public_redis_url(self_redis_url)
    entries.append((self_node_id, self_pub))
    for p in peers:
        if p.get("auth_ok") is False:
            continue
        nid = (p.get("node_id") or "").strip()
        ru = (p.get("redis_url") or "").strip()
        if not nid or not ru:
            continue
        entries.append((nid, ru))
    entries.sort(key=lambda x: x[0])
    return entries[0]


def try_join_mesh(comms: Any, *, force: bool = False) -> Dict[str, Any]:
    global _joined_url

    if os.getenv("AURORA_AUTO_MESH", "1").strip() in ("0", "false", "no") and not force:
        return {"ok": False, "skipped": True, "reason": "AURORA_AUTO_MESH disabled"}

    forced = (os.getenv("AURORA_MESH_REDIS") or "").strip()
    leader = ""
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

    if target == current or target == _joined_url:
        try:
            from comms.discovery import get_discovery

            d = get_discovery()
            if d:
                d.set_join_url(target or current)
        except Exception:
            pass
        return {
            "ok": True,
            "joined": False,
            "already": True,
            "redis_url": current,
            "leader": leader,
        }

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
            try:
                from comms.discovery import get_discovery

                d = get_discovery()
                if d:
                    d.set_join_url(target)
            except Exception:
                pass
            try:
                comms.register_node(
                    node_type="dashboard",
                    capabilities=["dashboard", "mesh", "chat", "mining_engine"],
                    metadata={"mesh_joined": target},
                )
                comms.heartbeat(metadata={"status": "online"})
            except Exception:
                pass
            logger.info("mesh join → %s leader=%s", target, leader)
            return {
                "ok": True,
                "joined": True,
                "redis_url": target,
                "leader": leader,
                "peers": len(comms.get_active_nodes() or []),
            }
        except Exception as e:
            logger.warning("mesh join failed: %s", e)
            return {"ok": False, "error": str(e), "target": target}


def start_auto_mesh_join(get_comms: Callable[[], Any], interval: float = 8.0):
    def _loop():
        time.sleep(6)
        while True:
            try:
                try_join_mesh(get_comms())
            except Exception as e:
                logger.debug("auto mesh: %s", e)
            time.sleep(interval)

    threading.Thread(target=_loop, name="auto-mesh-join", daemon=True).start()
    logger.info("auto mesh join started")
