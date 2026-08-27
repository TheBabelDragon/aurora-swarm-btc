"""File + optional Redis adapter for MetaField stats.

No torch. No MetaField import. Fail closed if files or Redis are missing.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

METAFIELD_KEYS = {
    "stats": "aurora:metafield:stats",
    "heartbeat": "aurora:metafield:heartbeat",
    "context": "aurora:sensing:context",
}


def stats_path() -> Path:
    explicit = os.environ.get("METAFIELD_STATS_PATH")
    if explicit:
        return Path(explicit)
    runtime = os.environ.get("METAFIELD_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "stats.json"
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "metafield" / "stats.json"
    return Path("/tmp/metafield/stats.json")


def load_stats(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    p = path or stats_path()
    try:
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def snapshot_from_stats(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not data:
        return {
            "schema_version": 0,
            "health": "no_export",
            "live": False,
            "source": str(stats_path()),
            "timestamp": time.time(),
        }

    health = str(data.get("health") or "unknown")
    live = bool(data.get("live", health not in ("stopped", "no_export")))
    hmc = data.get("hmc") if isinstance(data.get("hmc"), dict) else {}
    geom = data.get("geometry") if isinstance(data.get("geometry"), dict) else {}
    att = data.get("attractors") if isinstance(data.get("attractors"), dict) else {}
    mem = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    aurora = data.get("aurora") if isinstance(data.get("aurora"), dict) else {}

    return {
        "schema_version": int(data.get("schema_version") or 1),
        "version": data.get("version"),
        "traj": data.get("traj"),
        "health": health,
        "live": live,
        "hmc": {
            "acceptance_rate": hmc.get("acceptance_rate"),
            "recent_abs_dh": hmc.get("recent_abs_dh"),
        },
        "geometry": {
            "train_loss": geom.get("train_loss"),
            "scalar_curvature": geom.get("scalar_curvature"),
            "metric_logdet": geom.get("metric_logdet"),
        },
        "attractors": {
            "num_attractors": att.get("num_attractors"),
            "total_energy": att.get("total_energy"),
        },
        "memory": {
            "size": mem.get("size"),
            "soft_capacity": mem.get("soft_capacity"),
        },
        "aurora_drive": aurora.get("mode"),
        "source": str(stats_path()),
        "timestamp": time.time(),
        "stopped_at": data.get("stopped_at"),
    }


def _redis_client():
    url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    try:
        import redis  # type: ignore

        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=1.0)
        client.ping()
        return client
    except Exception:
        return None


def publish_snapshot(snapshot: Dict[str, Any], ttl_seconds: int = 90) -> Dict[str, Any]:
    """Best-effort Redis publish. Never raises."""
    if os.environ.get("METAFIELD_BRIDGE_PUBLISH", "1") in ("0", "false", "False"):
        return {"published": False, "reason": "disabled"}

    client = _redis_client()
    if client is None:
        return {"published": False, "reason": "redis_unavailable"}

    try:
        payload = json.dumps(snapshot)
        pipe = client.pipeline()
        pipe.set(METAFIELD_KEYS["stats"], payload, ex=ttl_seconds)
        pipe.set(
            METAFIELD_KEYS["heartbeat"],
            json.dumps(
                {
                    "timestamp": snapshot.get("timestamp"),
                    "health": snapshot.get("health"),
                    "live": snapshot.get("live"),
                }
            ),
            ex=ttl_seconds,
        )

        raw_ctx = client.get(METAFIELD_KEYS["context"])
        ctx: Dict[str, Any]
        if raw_ctx:
            try:
                parsed = json.loads(raw_ctx)
                ctx = parsed if isinstance(parsed, dict) else {}
            except Exception:
                ctx = {}
        else:
            ctx = {}
        ctx["metafield"] = snapshot
        pipe.set(METAFIELD_KEYS["context"], json.dumps(ctx), ex=max(ttl_seconds, 120))
        pipe.execute()
        return {"published": True, "reason": "ok"}
    except Exception as exc:
        return {"published": False, "reason": f"redis_error:{exc.__class__.__name__}"}


def tick() -> Dict[str, Any]:
    snap = snapshot_from_stats(load_stats())
    pub = publish_snapshot(snap)
    snap["publish"] = pub
    return snap
