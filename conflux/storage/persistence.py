"""Durable record store.

Redis may be used for coordination/caching.
It must not be the sole permanent record of source history, builds,
releases, or deployment evidence.
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, TypeVar

T = TypeVar("T")


class ConfluxStore(ABC):
    """Storage adapter interface."""

    @abstractmethod
    def put(self, collection: str, key: str, value: dict) -> None:
        ...

    @abstractmethod
    def get(self, collection: str, key: str) -> Optional[dict]:
        ...

    @abstractmethod
    def delete(self, collection: str, key: str) -> bool:
        ...

    @abstractmethod
    def list_keys(self, collection: str, *, prefix: str = "", limit: int = 100) -> List[str]:
        ...

    @abstractmethod
    def list_values(self, collection: str, *, prefix: str = "", limit: int = 100) -> List[dict]:
        ...


class MemoryStore(ConfluxStore):
    """Process-local store with recovery-friendly snapshot support."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, dict]] = {}
        self._lock = threading.RLock()

    def put(self, collection: str, key: str, value: dict) -> None:
        with self._lock:
            self._data.setdefault(collection, {})[key] = dict(value)

    def get(self, collection: str, key: str) -> Optional[dict]:
        with self._lock:
            col = self._data.get(collection) or {}
            v = col.get(key)
            return dict(v) if v is not None else None

    def delete(self, collection: str, key: str) -> bool:
        with self._lock:
            col = self._data.get(collection)
            if not col or key not in col:
                return False
            del col[key]
            return True

    def list_keys(self, collection: str, *, prefix: str = "", limit: int = 100) -> List[str]:
        with self._lock:
            col = self._data.get(collection) or {}
            keys = sorted(k for k in col if k.startswith(prefix))
            return keys[:limit]

    def list_values(self, collection: str, *, prefix: str = "", limit: int = 100) -> List[dict]:
        with self._lock:
            col = self._data.get(collection) or {}
            keys = sorted(k for k in col if k.startswith(prefix))
            return [dict(col[k]) for k in keys[:limit]]

    def snapshot(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def restore(self, data: dict) -> None:
        with self._lock:
            self._data = {c: {k: dict(v) for k, v in items.items()} for c, items in data.items()}
