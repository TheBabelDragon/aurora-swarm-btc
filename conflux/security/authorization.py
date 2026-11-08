"""AEGIS-42 authorization for Conflux mutations.

Fail closed when AEGIS is required but unavailable.
Do not trust actor_id from request headers alone without registry presence.
Do not auto-grant capabilities. Operators must be provisioned explicitly.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional, Set

logger = logging.getLogger("conflux.security")

CONFLUX_CAPABILITIES: Set[str] = {
    "conflux:project:create",
    "conflux:source:add",
    "conflux:changeset:create",
    "conflux:changeset:reconcile",
    "conflux:changeset:approve",
    "conflux:build:create",
    "conflux:release:create",
    "conflux:release:promote",
    "conflux:deployment:plan",
    "conflux:deployment:execute",
    "conflux:deployment:rollback",
    "conflux:*",  # explicit wildcard only when granted
}


@dataclass
class AuthorizationResult:
    allowed: bool
    reason: str = ""
    actor_id: str = ""
    capability: str = ""
    trusted: bool = False


def _aegis_required() -> bool:
    return os.getenv("CONFLUX_REQUIRE_AEGIS", "1").strip().lower() not in ("0", "false", "no", "off")


def _get_aegis():
    try:
        from mods.aegis_42 import get_aegis

        return get_aegis()
    except Exception as e:
        logger.debug("get_aegis failed: %s", e)
        return None


def authorize_mutation(
    *,
    actor_id: str,
    capability: str,
    api_key_ok: bool,
) -> AuthorizationResult:
    """Authorize a Conflux mutation.

    Order:
    1. API key must pass when configured.
    2. actor_id required and non-empty.
    3. AEGIS must be available when required.
    4. Identity must exist and not be revoked.
    5. Identity must be trusted OR hold the explicit capability / conflux:*.
    """
    if not api_key_ok:
        return AuthorizationResult(False, reason="api_key_invalid", capability=capability)

    actor = (actor_id or "").strip()
    if not actor:
        return AuthorizationResult(False, reason="actor_id_required", capability=capability)

    if capability not in CONFLUX_CAPABILITIES and not capability.startswith("conflux:"):
        return AuthorizationResult(False, reason="unknown_capability", actor_id=actor, capability=capability)

    aegis = _get_aegis()
    if aegis is None:
        if _aegis_required():
            return AuthorizationResult(
                False,
                reason="aegis_unavailable",
                actor_id=actor,
                capability=capability,
            )
        # AEGIS explicitly not required — still demand API key (already checked)
        return AuthorizationResult(True, reason="aegis_disabled", actor_id=actor, capability=capability)

    if not getattr(aegis, "enabled", True):
        if _aegis_required():
            return AuthorizationResult(
                False,
                reason="aegis_disabled_but_required",
                actor_id=actor,
                capability=capability,
            )
        return AuthorizationResult(True, reason="aegis_disabled", actor_id=actor, capability=capability)

    identity = aegis.identity.get(actor)
    if identity is None:
        return AuthorizationResult(
            False,
            reason="actor_unknown",
            actor_id=actor,
            capability=capability,
        )

    if getattr(identity.trust, "revoked", False):
        return AuthorizationResult(
            False,
            reason="actor_revoked",
            actor_id=actor,
            capability=capability,
        )

    trusted = aegis.identity.is_trusted(actor)
    caps = aegis.identity.capabilities_of(actor)

    has_cap = capability in caps or "conflux:*" in caps
    # Trusted operators still need an explicit conflux capability or conflux:*
    if not has_cap:
        return AuthorizationResult(
            False,
            reason="capability_missing",
            actor_id=actor,
            capability=capability,
            trusted=trusted,
        )

    # Record decision if AEGIS exposes audit
    try:
        if hasattr(aegis, "audit") and hasattr(aegis.audit, "record"):
            aegis.audit.record(
                event_type="conflux.authorize",
                actor_id=actor,
                detail={"capability": capability, "allowed": True},
            )
    except Exception:
        pass

    return AuthorizationResult(
        True,
        reason="authorized",
        actor_id=actor,
        capability=capability,
        trusted=trusted,
    )


def require_capability(
    *,
    actor_id: str,
    capability: str,
    api_key_ok: bool,
) -> AuthorizationResult:
    """Alias for authorize_mutation — explicit name for call sites."""
    return authorize_mutation(actor_id=actor_id, capability=capability, api_key_ok=api_key_ok)


def provision_operator(
    identity_id: str,
    *,
    capabilities: Optional[list] = None,
    granted_by: str = "system",
    trust_level: str = "operator",
) -> dict:
    """Provision an operator identity with Conflux capabilities.

    Must be called by system/bootstrap — never from untrusted request paths.
    """
    aegis = _get_aegis()
    if aegis is None:
        return {"ok": False, "error": "aegis_unavailable"}

    caps = capabilities or sorted(c for c in CONFLUX_CAPABILITIES if c != "conflux:*")
    existing = aegis.identity.get(identity_id)
    if existing is None:
        try:
            aegis.identity.register(
                identity_id,
                kind="operator",
                capabilities=caps,
                trust_level=trust_level,
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    else:
        for c in caps:
            aegis.identity.grant_capability(identity_id, c, granted_by=granted_by)
        # Elevate trust if requested
        if trust_level in ("trusted", "operator") and hasattr(existing, "trust"):
            existing.trust.trust_level = trust_level

    return {
        "ok": True,
        "identity_id": identity_id,
        "capabilities": sorted(aegis.identity.capabilities_of(identity_id)),
        "trusted": aegis.identity.is_trusted(identity_id),
    }
