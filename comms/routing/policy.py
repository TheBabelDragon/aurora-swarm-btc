"""Destination and egress policy — SSRF / DNS-rebinding defenses.

Validation at connection time, not only at resolution time.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable, List, Optional, Set, Tuple


_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("2001:db8::/32"),
]


def is_blocked_address(addr: str, *, allow_private: bool = False) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True
    if allow_private:
        for net in _BLOCKED_NETWORKS:
            if ip in net and not _is_rfc1918(ip):
                return True
        return False
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return True
    return False


def _is_rfc1918(ip: ipaddress._BaseAddress) -> bool:
    if ip.version != 4:
        return False
    return any(
        ip in n
        for n in (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )
    )


def parse_cidrs(cidrs: Iterable[str]) -> List[ipaddress._BaseNetwork]:
    out: List[ipaddress._BaseNetwork] = []
    for c in cidrs:
        try:
            out.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue
    return out


def address_allowed(
    addr: str,
    *,
    allowed_cidrs: Optional[List[ipaddress._BaseNetwork]] = None,
    deny_private: bool = True,
) -> Tuple[bool, str]:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False, "unparseable_address"
    if deny_private and is_blocked_address(addr, allow_private=False):
        return False, "blocked_private_or_reserved"
    if allowed_cidrs:
        if not any(ip in net for net in allowed_cidrs):
            return False, "not_in_allowed_cidrs"
    return True, "ok"


def port_allowed(port: Optional[int], allowed_ports: Set[int]) -> Tuple[bool, str]:
    if port is None:
        return True, "no_port"
    if not allowed_ports:
        return True, "no_port_policy"
    if port in allowed_ports:
        return True, "ok"
    return False, "port_denied"


def validate_resolved_for_egress(
    addresses: List[str],
    port: Optional[int],
    *,
    allowed_cidrs: Optional[List[ipaddress._BaseNetwork]] = None,
    allowed_ports: Optional[Set[int]] = None,
    deny_private: bool = True,
) -> Tuple[bool, str]:
    """Connection-time validation (DNS rebinding defense)."""
    if not addresses:
        return False, "no_addresses"
    for addr in addresses:
        ok, reason = address_allowed(
            addr, allowed_cidrs=allowed_cidrs, deny_private=deny_private
        )
        if not ok:
            return False, reason
    if allowed_ports is not None:
        ok, reason = port_allowed(port, allowed_ports)
        if not ok:
            return False, reason
    return True, "ok"
