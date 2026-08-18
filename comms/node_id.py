"""Unique default node IDs so two machines don't both call themselves dashboard."""

from __future__ import annotations

import os
import re
import socket


def default_node_id(prefix: str = "node") -> str:
    env = (os.getenv("AURORA_NODE_ID") or "").strip()
    if env and env.lower() not in ("dashboard", "unknown-node", "unknown"):
        return env
    # Prefer explicit worker name
    wn = (os.getenv("WORKER_NAME") or "").strip()
    if wn:
        return wn
    host = socket.gethostname() or "host"
    host = re.sub(r"[^a-zA-Z0-9_-]+", "-", host).strip("-")[:24] or "host"
    # If user forced AURORA_NODE_ID=dashboard, still uniquify with hostname
    if env:
        return f"{env}-{host}"
    return f"{prefix}-{host}"
