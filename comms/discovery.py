"""
LAN mesh discovery — UDP beacon so peers find Redis without typing IPs.

Beacon port default 7379. Payload is signed JSON (see beacon_auth).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Any, Dict, List, Optional

from comms.beacon_auth import sign_beacon, verify_beacon

logger = logging.getLogger("aurora.comms.discovery")

DISCOVERY_PORT = int(os.getenv("AURORA_DISCOVERY_PORT", "7379") or 7379)
BEACON_INTERVAL = float(os.getenv("AURORA_BEACON_INTERVAL", "5") or 5)
MAGIC = "AURORA_MESH_V1"


def _local_ipv4s() -> List[str]:
    ips: List[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            ips.append(ip)
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    try:
        for _name, addrs in socket.getaddrinfo(socket.gethostname(), None):
            pass
    except Exception:
        pass
    # last-ditch: enumerate interfaces via hostname -I style is not portable; keep list
    return ips or ["127.0.0.1"]


def public_redis_url(redis_url: str) -> str:
    """Rewrite docker-internal redis://redis:6379 → LAN IP for peers."""
    url = (redis_url or "").strip() or "redis://127.0.0.1:6379/0"
    ips = _local_ipv4s()
    lan = ips[0]
    if "redis://redis" in url or "redis://localhost" in url or "redis://127.0.0.1" in url:
        if "@" in url:
            pre, rest = url.split("@", 1)
            path = ""
            if "/" in rest:
                hostport, path = rest.split("/", 1)
                path = "/" + path
            else:
                hostport = rest
            port = "6379"
            if ":" in hostport:
                port = hostport.rsplit(":", 1)[-1]
            return f"{pre}@{lan}:{port}{path}"
        tail = url.split("://", 1)[-1]
        path = ""
        if "/" in tail:
            hostport, path = tail.split("/", 1)
            path = "/" + path
        else:
            hostport = tail
        port = "6379"
        if ":" in hostport:
            port = hostport.rsplit(":", 1)[-1]
        return f"redis://{lan}:{port}{path}"
    return url


def _node_key_hex() -> str:
    try:
        from mods.btc_identity.keys import load_or_create

        return load_or_create().private_hex
    except Exception:
        return ""


def _fingerprint() -> str:
    try:
        from mods.btc_identity.keys import load_or_create

        return load_or_create().fingerprint
    except Exception:
        return ""


class MeshDiscovery:
    def __init__(
        self,
        *,
        node_id: str,
        redis_url: str,
        capabilities: Optional[List[str]] = None,
        port: int = DISCOVERY_PORT,
    ):
        self.node_id = node_id
        self.redis_url = redis_url
        self.join_url = public_redis_url(redis_url)
        self.capabilities = capabilities or ["dashboard", "mesh"]
        self.port = port
        self._stop = threading.Event()
        self._seen: Dict[str, Dict[str, Any]] = {}
        self._pins: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._beacon_t: Optional[threading.Thread] = None
        self._listen_t: Optional[threading.Thread] = None
        self.listen_ok = False
        self.last_listen_error = ""

    def set_join_url(self, redis_url: str):
        """After mesh join, advertise the shared leader — not the local island."""
        self.redis_url = redis_url
        self.join_url = public_redis_url(redis_url)
        logger.info("discovery now advertises join=%s", self.join_url)

    def snapshot_peers(self, max_age: float = 30.0) -> List[Dict[str, Any]]:
        now = time.time()
        with self._lock:
            return [
                dict(v)
                for v in self._seen.values()
                if now - float(v.get("seen_at") or 0) <= max_age
            ]

    def _payload(self) -> bytes:
        body = {
            "magic": MAGIC,
            "node_id": self.node_id,
            "redis_url": self.join_url,
            "capabilities": self.capabilities,
            "ts": int(time.time()),
            "ips": _local_ipv4s(),
            "role": "hub" if os.getenv("AURORA_MESH_ROLE", "") == "hub" else "peer",
            "fingerprint": _fingerprint(),
        }
        signed = sign_beacon(body, node_key_hex=_node_key_hex())
        return json.dumps(signed).encode("utf-8")

    def _beacon_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        while not self._stop.is_set():
            try:
                payload = self._payload()
                targets = ["255.255.255.255"]
                for ip in _local_ipv4s():
                    parts = ip.split(".")
                    if len(parts) == 4:
                        targets.append(".".join(parts[:3] + ["255"]))
                for dest in dict.fromkeys(targets):
                    try:
                        sock.sendto(payload, (dest, self.port))
                    except Exception as e:
                        logger.debug("beacon %s: %s", dest, e)
            except Exception as e:
                logger.debug("beacon: %s", e)
            self._stop.wait(BEACON_INTERVAL)
        try:
            sock.close()
        except Exception:
            pass

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            pass
        try:
            sock.bind(("0.0.0.0", self.port))
            self.listen_ok = True
            self.last_listen_error = ""
        except Exception as e:
            self.listen_ok = False
            self.last_listen_error = str(e)
            logger.error("discovery bind UDP %s failed: %s", self.port, e)
            return
        sock.settimeout(1.0)
        while not self._stop.is_set():
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except Exception as e:
                logger.debug("listen: %s", e)
                continue
            try:
                msg = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            nid = (msg.get("node_id") or "").strip()
            if not nid or nid == self.node_id:
                continue
            with self._lock:
                pins = dict(self._pins)
            ok, reason = verify_beacon(msg, pinned=pins)
            if not ok:
                logger.info("drop beacon from %s (%s): %s", addr[0], nid, reason)
                continue
            fp = (msg.get("fingerprint") or "").strip()
            msg["seen_at"] = time.time()
            msg["from_ip"] = addr[0]
            msg["auth_ok"] = True
            msg["auth_reason"] = reason
            with self._lock:
                if fp:
                    self._pins.setdefault(nid, fp)
                self._seen[nid] = msg
        try:
            sock.close()
        except Exception:
            pass

    def start(self):
        if self._beacon_t and self._beacon_t.is_alive():
            return
        self._stop.clear()
        self._beacon_t = threading.Thread(target=self._beacon_loop, name="mesh-beacon", daemon=True)
        self._listen_t = threading.Thread(target=self._listen_loop, name="mesh-listen", daemon=True)
        self._beacon_t.start()
        self._listen_t.start()
        logger.info("mesh discovery on UDP %s join=%s node=%s", self.port, self.join_url, self.node_id)

    def stop(self):
        self._stop.set()


_discovery: Optional[MeshDiscovery] = None


def start_discovery(node_id: str, redis_url: str, capabilities: Optional[List[str]] = None) -> MeshDiscovery:
    global _discovery
    if _discovery is not None:
        if node_id and _discovery.node_id != node_id:
            _discovery.node_id = node_id
        return _discovery
    _discovery = MeshDiscovery(node_id=node_id, redis_url=redis_url, capabilities=capabilities)
    if os.getenv("AURORA_DISCOVERY", "1").lower() not in ("0", "false", "no", "off"):
        _discovery.start()
    return _discovery


def get_discovery() -> Optional[MeshDiscovery]:
    return _discovery
