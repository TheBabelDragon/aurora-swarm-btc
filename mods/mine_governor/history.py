"""In-process command history for the governor."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

_lock = threading.Lock()
_items: List[Dict[str, Any]] = []
_MAX = 40


def record(action: str, result: Dict[str, Any]) -> Dict[str, Any]:
    item = {
        "ts": time.time(),
        "action": action,
        "ok": bool(result.get("ok") and result.get("applied", True)),
        "apply": result.get("apply"),
        "threads": result.get("threads"),
        "error": result.get("error"),
    }
    with _lock:
        _items.append(item)
        del _items[:-_MAX]
    return item


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    with _lock:
        return list(_items[-max(1, min(limit, _MAX)):])


def last() -> Dict[str, Any] | None:
    with _lock:
        return dict(_items[-1]) if _items else None
