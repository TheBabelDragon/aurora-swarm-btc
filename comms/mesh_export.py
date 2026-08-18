"""Auto-export everything a peer needs to join this mesh."""

from __future__ import annotations

import os
import socket
import time
from typing import Any, Dict, List, Optional

from .discovery import _local_ipv4s, public_redis_url


def export_join_pack(
    *,
    node_id: str,
    redis_url: str,
    peers: Optional[List[Dict[str, Any]]] = None,
    discovered: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    join = public_redis_url(redis_url)
    ips = _local_ipv4s()
    host = socket.gethostname()
    env_lines = [
        f"export REDIS_URL={join}",
        f"export AURORA_NODE_ID=node-{host}",
        "export AURORA_AUTO_MINE=1",
        "export AURORA_MINER_BACKEND=cpu",
        "export AURORA_DISCOVERY=1",
        "# then: docker compose -f docker-compose.solo.yml up -d --build",
    ]
    shell = "\n".join(env_lines) + "\n"
    dotenv = "\n".join(
        [
            f"REDIS_URL={join}",
            f"AURORA_NODE_ID=node-{host}-peer",
            "AURORA_AUTO_MINE=1",
            "AURORA_MINER_BACKEND=cpu",
            "AURORA_DISCOVERY=1",
        ]
    ) + "\n"

    return {
        "format": "aurora_mesh_join_v1",
        "ts": time.time(),
        "hub_node_id": node_id,
        "hub_hostname": host,
        "hub_ips": ips,
        "REDIS_URL": join,
        "discovery_port": int(os.getenv("AURORA_DISCOVERY_PORT", "7379") or 7379),
        "env_export": shell,
        "dotenv": dotenv,
        "docker_peer_cmd": (
            f"REDIS_URL={join} AURORA_NODE_ID=node-$(hostname) "
            f"docker compose -f docker-compose.solo.yml up -d --build"
        ),
        "mesh_peers_redis": peers or [],
        "mesh_peers_lan": discovered or [],
        "instructions": [
            "On the other machine, paste env_export into a shell (or write dotenv to .env).",
            "Or run docker_peer_cmd from the repo root.",
            "Ensure UDP 7379 and TCP 6379 are open on the LAN.",
            "Both dashboards should then list each other under Comms Layer.",
        ],
    }
