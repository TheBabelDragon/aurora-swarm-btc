"""
Mesh chat over shared Redis.

- Broadcast room: aurora:chat:room:swarm
- DM thread: aurora:chat:dm:{sorted(a,b)}
- Index of known handles: aurora:chat:users
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer, SwarmMessage

logger = logging.getLogger("aurora.comms.chat")

ROOM = "swarm"
MAX_HISTORY = 500


def _dm_key(a: str, b: str) -> str:
    x, y = sorted([a.strip(), b.strip()])
    return f"chat:dm:{x}:{y}"


def _room_key(room: str = ROOM) -> str:
    return f"chat:room:{room}"


class MeshChat:
    def __init__(self, comms: CommsLayer):
        self.comms = comms
        self.me = comms.node_id

    def _append(self, key: str, msg: Dict[str, Any]):
        full = f"aurora:{key}"
        try:
            pipe = self.comms.r.pipeline()
            pipe.rpush(full, json.dumps(msg))
            pipe.ltrim(full, -MAX_HISTORY, -1)
            pipe.execute()
        except Exception as e:
            logger.warning(f"chat append: {e}")

    def _history(self, key: str, limit: int = 50) -> List[Dict[str, Any]]:
        full = f"aurora:{key}"
        try:
            raw = self.comms.r.lrange(full, -max(1, limit), -1) or []
            out = []
            for item in raw:
                try:
                    out.append(json.loads(item))
                except Exception:
                    out.append({"text": str(item)})
            return out
        except Exception as e:
            logger.debug(f"chat history: {e}")
            return []

    def remember_user(self, node_id: str, display: Optional[str] = None, source: str = "mesh"):
        node_id = (node_id or "").strip()
        if not node_id:
            return
        try:
            self.comms.r.hset(
                "aurora:chat:users",
                node_id,
                json.dumps(
                    {
                        "node_id": node_id,
                        "display": display or node_id,
                        "source": source,
                        "seen": time.time(),
                    }
                ),
            )
        except Exception:
            pass

    def list_users(self) -> List[Dict[str, Any]]:
        """Online mesh + LAN discovery + remembered external handles."""
        users: Dict[str, Dict[str, Any]] = {}

        # Self
        users[self.me] = {
            "node_id": self.me,
            "display": self.me,
            "source": "self",
            "online": True,
        }

        # Redis mesh registry
        try:
            for n in self.comms.get_active_nodes() or []:
                nid = (n.get("node_id") or "").strip()
                if not nid:
                    continue
                users[nid] = {
                    "node_id": nid,
                    "display": nid,
                    "source": "mesh",
                    "online": True,
                    "node_type": n.get("node_type"),
                    "capabilities": n.get("capabilities") or [],
                }
                self.remember_user(nid, source="mesh")
        except Exception:
            pass

        # LAN discovery beacons
        try:
            from comms.discovery import get_discovery

            d = get_discovery()
            if d:
                for p in d.snapshot_peers():
                    nid = (p.get("node_id") or "").strip()
                    if not nid:
                        continue
                    users[nid] = {
                        "node_id": nid,
                        "display": nid,
                        "source": "lan",
                        "online": True,
                        "from_ip": p.get("from_ip"),
                        "redis_url": p.get("redis_url"),
                    }
                    self.remember_user(nid, source="lan")
        except Exception:
            pass

        # Remembered / external
        try:
            raw = self.comms.r.hgetall("aurora:chat:users") or {}
            for nid, val in raw.items():
                if isinstance(nid, bytes):
                    nid = nid.decode()
                if nid in users:
                    continue
                try:
                    info = json.loads(val)
                except Exception:
                    info = {"node_id": nid, "display": nid, "source": "external"}
                info["online"] = False
                users[nid] = info
        except Exception:
            pass

        return sorted(users.values(), key=lambda u: (not u.get("online"), u.get("node_id") or ""))

    def search_users(self, q: str) -> List[Dict[str, Any]]:
        q = (q or "").strip().lower()
        all_u = self.list_users()
        if not q:
            return all_u
        return [
            u
            for u in all_u
            if q in (u.get("node_id") or "").lower() or q in (u.get("display") or "").lower()
        ]

    def send(
        self,
        text: str,
        *,
        to: Optional[str] = None,
        room: str = ROOM,
    ) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty message"}
        if len(text) > 4000:
            text = text[:4000]

        to = (to or "").strip() or None
        msg = {
            "id": f"{self.me}-{int(time.time()*1000)}",
            "from": self.me,
            "to": to or "*",
            "room": room if not to else None,
            "text": text,
            "ts": time.time(),
        }

        if to:
            self.remember_user(to, source="external")
            key = _dm_key(self.me, to)
            self._append(key, msg)
            channel = f"chat.dm.{to}"
            # also notify sender's mirror channel for multi-tab
            try:
                sm = SwarmMessage(type="chat.dm", payload=msg, source=self.me, target=to)
                self.comms.publish_message(channel, sm)
                self.comms.publish_message(f"chat.dm.{self.me}", sm)
            except Exception as e:
                logger.debug(f"dm publish: {e}")
        else:
            key = _room_key(room)
            self._append(key, msg)
            try:
                sm = SwarmMessage(type="chat.room", payload=msg, source=self.me)
                self.comms.publish_message(f"chat.room.{room}", sm)
            except Exception as e:
                logger.debug(f"room publish: {e}")

        return {"ok": True, "message": msg}

    def history(
        self,
        *,
        with_user: Optional[str] = None,
        room: str = ROOM,
        limit: int = 80,
    ) -> List[Dict[str, Any]]:
        with_user = (with_user or "").strip() or None
        if with_user:
            return self._history(_dm_key(self.me, with_user), limit=limit)
        return self._history(_room_key(room), limit=limit)
