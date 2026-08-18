"""
Multi-pool connector with failover (inspired by classic PoolConnector patterns).
"""

from __future__ import annotations

import json
import logging
import select
import socket
import ssl
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .coins import CoinProfile, PoolEndpoint, get_coin

logger = logging.getLogger("aurora.mining.pools")


def parse_pool_url(url: str) -> PoolEndpoint:
    u = urlparse(url if "://" in url else "stratum+tcp://" + url)
    host = u.hostname or "stratum.braiins.com"
    port = int(u.port or 3333)
    ssl_flag = u.scheme in ("stratum+ssl", "ssl")
    return PoolEndpoint(host=host, port=port, ssl=ssl_flag)


class PoolConnector:
    def __init__(self, pools: List[PoolEndpoint], username: str, password: str = "x"):
        self.pools = pools or [parse_pool_url("stratum+tcp://stratum.braiins.com:3333")]
        self.username = username
        self.password = password
        self.active_index = 0
        self.sock: Optional[socket.socket] = None
        self._msg_id = 0

    @classmethod
    def from_coin(cls, symbol: str, wallet: str, worker: str, password: str = "x") -> "PoolConnector":
        coin = get_coin(symbol) or get_coin("BTC")
        assert coin
        pools = list(coin.default_pools)
        user = f"{wallet}.{worker}"
        return cls(pools, username=user, password=password)

    @property
    def active(self) -> PoolEndpoint:
        return self.pools[self.active_index % len(self.pools)]

    def connect(self, timeout: float = 15.0) -> bool:
        self.close()
        for i in range(len(self.pools)):
            self.active_index = i
            pool = self.active
            try:
                raw = socket.create_connection((pool.host, pool.port), timeout=timeout)
                if pool.ssl:
                    ctx = ssl.create_default_context()
                    self.sock = ctx.wrap_socket(raw, server_hostname=pool.host)
                else:
                    self.sock = raw
                self.sock.settimeout(30)
                logger.info(f"pool connected {pool.host}:{pool.port}")
                return True
            except Exception as e:
                logger.warning(f"pool fail {pool.host}: {e}")
                self.sock = None
        return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def _send(self, method: str, params: list) -> int:
        self._msg_id += 1
        mid = self._msg_id
        payload = json.dumps({"id": mid, "method": method, "params": params}) + "\n"
        if not self.sock:
            raise RuntimeError("not connected")
        self.sock.sendall(payload.encode())
        return mid

    def receive(self, timeout: float = 2.0) -> List[dict]:
        if not self.sock:
            return []
        out: List[dict] = []
        try:
            ready, _, _ = select.select([self.sock], [], [], timeout)
            if not ready:
                return []
            data = self.sock.recv(8192)
            if not data:
                return []
            for line in data.decode(errors="ignore").split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"receive: {e}")
        return out

    def subscribe_authorize(self) -> bool:
        try:
            self._send("mining.subscribe", ["aurora-swarm/1.0"])
            self._send("mining.authorize", [self.username, self.password])
            # drain a few responses
            ok_auth = False
            for _ in range(5):
                for msg in self.receive(timeout=2.0):
                    if msg.get("result") is True:
                        ok_auth = True
                    if isinstance(msg.get("result"), list):
                        ok_auth = True  # subscribe result shape
                if ok_auth:
                    break
            return True
        except Exception as e:
            logger.error(f"subscribe/auth: {e}")
            return False

    def failover(self) -> bool:
        self.active_index = (self.active_index + 1) % max(1, len(self.pools))
        return self.connect() and self.subscribe_authorize()
