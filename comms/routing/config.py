"""Configuration for destination routing subsystem.

All settings degrade gracefully when disabled. Existing deployments continue
without any new environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Set


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _csv(name: str) -> List[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass
class RoutingConfig:
    """Validated routing settings. Defaults keep everything off / safe."""

    enabled: bool = False
    gateway_advertise_enabled: bool = False
    egress_gateway_enabled: bool = False
    egress_bind_host: str = "127.0.0.1"
    egress_port: int = 0
    route_health_interval: float = 30.0
    route_ttl: float = 120.0
    route_connect_timeout: float = 5.0
    route_max_retries: int = 2
    dns_timeout: float = 3.0
    dns_cache_ttl_cap: float = 300.0
    egress_allowed_cidrs: List[str] = field(default_factory=list)
    egress_allowed_ports: Set[int] = field(default_factory=set)
    egress_max_connections: int = 32
    deny_private_for_egress: bool = True

    def validate(self) -> List[str]:
        problems: List[str] = []
        if self.route_ttl <= 0:
            problems.append("AURORA_ROUTE_TTL must be > 0")
        if self.route_connect_timeout <= 0:
            problems.append("AURORA_ROUTE_CONNECT_TIMEOUT must be > 0")
        if self.route_max_retries < 0:
            problems.append("AURORA_ROUTE_MAX_RETRIES must be >= 0")
        if self.egress_gateway_enabled:
            if self.egress_port < 0 or self.egress_port > 65535:
                problems.append("AURORA_EGRESS_PORT out of range")
            if not self.egress_bind_host:
                problems.append("AURORA_EGRESS_BIND_HOST required when egress enabled")
        return problems


def load_routing_config() -> RoutingConfig:
    ports: Set[int] = set()
    for p in _csv("AURORA_EGRESS_ALLOWED_PORTS"):
        try:
            ports.add(int(p))
        except ValueError:
            pass
    return RoutingConfig(
        enabled=_bool("AURORA_DESTINATION_ROUTING_ENABLED", False),
        gateway_advertise_enabled=_bool("AURORA_GATEWAY_ADVERTISE_ENABLED", False),
        egress_gateway_enabled=_bool("AURORA_EGRESS_GATEWAY_ENABLED", False),
        egress_bind_host=(os.getenv("AURORA_EGRESS_BIND_HOST") or "127.0.0.1").strip(),
        egress_port=_int("AURORA_EGRESS_PORT", 0),
        route_health_interval=_float("AURORA_ROUTE_HEALTH_INTERVAL", 30.0),
        route_ttl=_float("AURORA_ROUTE_TTL", 120.0),
        route_connect_timeout=_float("AURORA_ROUTE_CONNECT_TIMEOUT", 5.0),
        route_max_retries=_int("AURORA_ROUTE_MAX_RETRIES", 2),
        dns_timeout=_float("AURORA_DNS_TIMEOUT", 3.0),
        dns_cache_ttl_cap=_float("AURORA_DNS_CACHE_TTL_CAP", 300.0),
        egress_allowed_cidrs=_csv("AURORA_EGRESS_ALLOWED_CIDRS"),
        egress_allowed_ports=ports,
        egress_max_connections=_int("AURORA_EGRESS_MAX_CONNECTIONS", 32),
        deny_private_for_egress=_bool("AURORA_EGRESS_DENY_PRIVATE", True),
    )
