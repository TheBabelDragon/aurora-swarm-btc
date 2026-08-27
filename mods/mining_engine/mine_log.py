"""Append-only official mining log. One line per event, UTC."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import List

_lock = threading.Lock()
_MAX_BYTES = 2_000_000


def log_path() -> Path:
    raw = (os.getenv("AURORA_MINING_LOG") or "").strip()
    if raw:
        return Path(raw)
    for cand in ("/data/aurora_mining.log", "/tmp/aurora_mining.log"):
        p = Path(cand)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch(exist_ok=True)
            return p
        except Exception:
            continue
    return Path("/tmp/aurora_mining.log")


def mine_log(kind: str, msg: str) -> None:
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + f" {kind.upper():<5} {msg.rstrip()}\n"
    path = log_path()
    try:
        with _lock:
            if path.exists() and path.stat().st_size > _MAX_BYTES:
                prev = path.read_text(encoding="utf-8", errors="replace")[-400_000:]
                path.write_text(prev, encoding="utf-8")
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass


def tail(n: int = 80) -> List[str]:
    path = log_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-max(1, min(n, 400)):]
