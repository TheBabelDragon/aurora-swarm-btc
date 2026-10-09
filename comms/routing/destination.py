"""Destination resolution — classify, normalize, validate, cache.

Classification precedence (highest first):
  1. URL / host:port / bracketed IPv6 parsing
  2. IP literals (IPv4 / IPv6)
  3. Content identifiers
  4. localhost and dotted hostnames
  5. Registered services / nodes (lookup)
  6. Service-id pattern only when not a hostname
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("aurora.comms.routing.destination")

_SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_NODE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CONTENT_ID_RE = re.compile(
    r"^(?:sha256:)?[0-9a-fA-F]{32,128}$|^(?:Qm|b)[1-9A-HJ-NP-Za-km-z]{20,}$"
)
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)
_LOCALHOST_NAMES = frozenset({"localhost", "localhost."})

_DNS_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="aurora-dns"
)


class DestinationKind(str, Enum):
    SERVICE = "service"
    NODE = "node"
    HOSTNAME = "hostname"
    IPV4 = "ipv4"
    IPV6 = "ipv6"
    CONTENT = "content"
    UNKNOWN = "unknown"


@dataclass
class Destination:
    kind: DestinationKind
    canonical_id: str
    hostname: Optional[str] = None
    port: Optional[int] = None
    transport: Optional[str] = None
    resolution_source: str = "input"
    resolved_addresses: List[str] = field(default_factory=list)
    expires_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "canonical_id": self.canonical_id,
            "hostname": self.hostname,
            "port": self.port,
            "transport": self.transport,
            "resolution_source": self.resolution_source,
            "resolved_addresses": list(self.resolved_addresses),
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
        }


class DestinationError(ValueError):
    pass


class DestinationResolver:
    def __init__(self, *, dns_timeout=3.0, dns_cache_ttl_cap=300.0,
                 dns_resolver=None, known_services=None, node_lookup=None, content_lookup=None):
        self.dns_timeout = dns_timeout
        self.dns_cache_ttl_cap = dns_cache_ttl_cap
        self._dns = dns_resolver or self._default_dns
        self.known_services = known_services or {}
        self._node_lookup = node_lookup
        self._content_lookup = content_lookup
        self._cache = {}
        self._stats = {"resolve_ok": 0, "resolve_fail": 0, "cache_hit": 0}

    @staticmethod
    def _getaddrinfo(host):
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addrs = []
        for info in infos:
            ip = info[4][0]
            if ip not in addrs:
                addrs.append(ip)
        return addrs

    @classmethod
    def _default_dns(cls, host, timeout):
        fut = _DNS_EXECUTOR.submit(cls._getaddrinfo, host)
        try:
            addrs = fut.result(timeout=timeout)
            return addrs, 60.0
        except concurrent.futures.TimeoutError as e:
            fut.cancel()
            raise DestinationError(f"dns_timeout:{host}") from e
        except Exception as e:
            raise DestinationError(f"dns_failed:{e}") from e

    def classify(self, raw):
        s = (raw or "").strip()
        if not s:
            raise DestinationError("empty_destination")
        if "://" in s:
            try:
                p = urlparse(s)
                if p.hostname:
                    return self.classify(p.hostname)
            except Exception:
                raise DestinationError("malformed_url")
            raise DestinationError("malformed_url")
        if s.startswith("[") and "]" in s:
            inner = s[1 : s.index("]")]
            try:
                import ipaddress
                ipaddress.IPv6Address(inner)
                return DestinationKind.IPV6
            except ValueError:
                raise DestinationError("malformed_ipv6")
        if s.count(":") == 1 and not s.startswith("["):
            host, _, port_s = s.rpartition(":")
            if host and port_s.isdigit():
                return self.classify(host)
        try:
            import ipaddress
            ip = ipaddress.ip_address(s)
            return DestinationKind.IPV6 if ip.version == 6 else DestinationKind.IPV4
        except ValueError:
            pass
        if _CONTENT_ID_RE.match(s):
            return DestinationKind.CONTENT
        if s.lower().rstrip(".") in _LOCALHOST_NAMES:
            return DestinationKind.HOSTNAME
        if "." in s:
            if not _HOSTNAME_RE.match(s.rstrip(".")):
                raise DestinationError("malformed_hostname")
            return DestinationKind.HOSTNAME
        if s in self.known_services:
            return DestinationKind.SERVICE
        if self._node_lookup and _NODE_ID_RE.match(s) and self._node_lookup(s):
            return DestinationKind.NODE
        if _SERVICE_ID_RE.match(s):
            return DestinationKind.SERVICE
        if _NODE_ID_RE.match(s):
            return DestinationKind.NODE
        raise DestinationError(f"ambiguous_or_unknown:{s[:64]}")

    def _parse_port(self, raw):
        s = raw.strip()
        if "://" in s:
            p = urlparse(s)
            return (p.hostname or s), p.port
        if s.startswith("[") and "]" in s:
            inner = s[1 : s.index("]")]
            rest = s[s.index("]") + 1 :]
            if rest.startswith(":") and rest[1:].isdigit():
                return inner, int(rest[1:])
            return inner, None
        if s.count(":") == 1:
            host, _, port_s = s.rpartition(":")
            if host and port_s.isdigit():
                return host, int(port_s)
        return s, None

    def resolve(self, raw, *, allow_dns=True, transport_hint=None):
        cache_key = f"{raw}|{allow_dns}|{transport_hint or ''}"
        cached = self._cache.get(cache_key)
        if cached and not cached.is_expired:
            self._stats["cache_hit"] += 1
            return cached
        host, port = self._parse_port(raw)
        kind = self.classify(host if "://" not in raw else host)
        dest = Destination(kind=kind, canonical_id=host, port=port, transport=transport_hint)
        if kind == DestinationKind.IPV4:
            dest.resolved_addresses = [host]
            dest.resolution_source = "literal"
        elif kind == DestinationKind.IPV6:
            dest.resolved_addresses = [host]
            dest.resolution_source = "literal"
        elif kind == DestinationKind.HOSTNAME:
            dest.hostname = host
            dest.canonical_id = host.lower().rstrip(".")
            if allow_dns:
                addrs, ttl = self._dns(host, self.dns_timeout)
                dest.resolved_addresses = addrs
                dest.resolution_source = "dns"
                dest.expires_at = time.time() + min(ttl, self.dns_cache_ttl_cap)
            else:
                dest.resolution_source = "hostname_unresolved"
        elif kind == DestinationKind.SERVICE:
            meta = self.known_services.get(host) or {}
            dest.metadata = dict(meta)
            dest.resolution_source = "service_registry"
            dest.transport = dest.transport or meta.get("transport") or "mesh"
            dest.expires_at = time.time() + 60.0
        elif kind == DestinationKind.NODE:
            info = self._node_lookup(host) if self._node_lookup else None
            if info:
                dest.metadata = dict(info)
                dest.resolution_source = "node_registry"
                dest.transport = dest.transport or "mesh"
                dest.expires_at = time.time() + float(info.get("ttl") or 120)
            else:
                dest.resolution_source = "node_unresolved"
                dest.transport = dest.transport or "mesh"
        elif kind == DestinationKind.CONTENT:
            info = self._content_lookup(host) if self._content_lookup else None
            if info:
                dest.metadata = dict(info)
                dest.resolution_source = "content_discovery"
                dest.transport = dest.transport or "torrent"
            else:
                dest.resolution_source = "content_unresolved"
        else:
            raise DestinationError(f"unsupported_kind:{kind}")
        self._cache[cache_key] = dest
        self._stats["resolve_ok"] += 1
        return dest

    def try_resolve(self, raw, **kwargs):
        try:
            return self.resolve(raw, **kwargs), None
        except DestinationError as e:
            self._stats["resolve_fail"] += 1
            return None, str(e)
        except Exception as e:
            self._stats["resolve_fail"] += 1
            return None, f"internal:{e}"

    def invalidate_cache(self, raw=None):
        if raw is None:
            self._cache.clear()
        else:
            for k in [k for k in self._cache if k.startswith(raw)]:
                del self._cache[k]

    def stats(self):
        return dict(self._stats)
