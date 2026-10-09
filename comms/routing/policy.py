"""Destination and egress policy — SSRF / DNS-rebinding defenses.

Validation at connection time, not only at resolution time.
Handles IPv4-mapped IPv6 and special-purpose addresses.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable, List, Optional, Set, Tuple


# Private, loopback, link-local, multicast, reserved, documentation, CGNAT, etc.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),       # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),        # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),       # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),     # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),      # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::/128"),              # unspecified
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::ffff:0:0/96"),       # IPv4-mapped (checked after expand)
    ipaddress.ip_network("64:ff9b::/96"),        # NAT64
    ipaddress.ip_network("100::/64"),
    ipaddress.ip_network("2001::/32"),           # Teredo
    ipaddress.ip_network("2001:db8::/32"),       # documentation
    ipaddress.ip_network("fc00::/7"),            # ULA
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def _normalize_ip(addr: str) -> ipaddress._BaseAddress:
    """Parse address; expand IPv4-mapped IPv6 to the underlying IPv4 for policy."""
    ip = ipaddress.ip_address(addr)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_blocked_address(addr: str, *, allow_private: bool = False) -> bool:
    try:
        ip = _normalize_ip(addr)
    except ValueError:
        return True
    if allow_private:
        still_block = [
            ipaddress.ip_network("0.0.0.0/8"),
            ipaddress.ip_network("127.0.0.0/8"),
            ipaddress.ip_network("169.254.0.0/16"),
            ipaddress.ip_network("224.0.0.0/4"),
            ipaddress.ip_network("240.0.0.0/4"),
            ipaddress.ip_network("::1/128"),
            ipaddress.ip_network("fe80::/10"),
            ipaddress.ip_network("ff00::/8"),
            ipaddress.ip_network("2001:db8::/32"),
        ]
        for net in still_block:
            if ip in net:
                return True
        return False
    for net in _BLOCKED_NETWORKS:
        try:
            if ip in net:
                return True
        except TypeError:
            continue
    return False


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
        ip = _normalize_ip(addr)
    except ValueError:
        return False, "unparseable_address"
    if deny_private and is_blocked_address(str(ip), allow_private=False):
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
    """Connection-time validation (DNS rebinding defense).

    Every candidate address is checked. deny_private is applied regardless of
    whether CIDR/port allow-lists are configured.
    """
    if not addresses:
        return False, "no_addresses"
    for addr in addresses:
        ok, reason = address_allowed(
            addr, allowed_cidrs=allowed_cidrs, deny_private=deny_private
        )
        if not ok:
            return False, reason
    if allowed_ports is not None and allowed_ports:
        ok, reason = port_allowed(port, allowed_ports)
        if not ok:
            return False, reason
    return True, "ok"


def validate_selected_address(
    addr: str,
    port: Optional[int],
    *,
    allowed_cidrs: Optional[List[ipaddress._BaseNetwork]] = None,
    allowed_ports: Optional[Set[int]] = None,
    deny_private: bool = True,
) -> Tuple[bool, str]:
    """Validate the single address about to be connected to."""
    return validate_resolved_for_egress(
        [addr], port,
        allowed_cidrs=allowed_cidrs,
        allowed_ports=allowed_ports,
        deny_private=deny_private,
    )
