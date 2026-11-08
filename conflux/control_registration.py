"""Register Conflux with the Aurora ecosystem control plane."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger("conflux.control")

ENTITY_ID = "aurora.conflux"
ADAPTER_ID = "aurora.null"


def register_with_control_plane(
    *,
    get_plane=None,
    health: str = "healthy",
) -> dict:
    """Register Conflux as a software_service. Does not grant execution privileges."""
    try:
        if get_plane is None:
            from dashboard.control_ops import get_control_plane

            plane = get_control_plane()
        else:
            plane = get_plane()
    except Exception as e:
        return {"ok": False, "error": f"control_plane_unavailable: {e}"}

    try:
        from control.registry import (
            Capability,
            CapabilityStatus,
            EntityRegistration,
            EntityType,
            OperationalState,
        )

        caps = [
            Capability(name="project_management", status=CapabilityStatus.DECLARED, operations=["create", "list", "get"]),
            Capability(name="git_source_inspection", status=CapabilityStatus.DECLARED, operations=["branches", "revisions", "snapshot"]),
            Capability(name="changeset_coordination", status=CapabilityStatus.DECLARED, operations=["create", "reconcile", "approve"]),
            Capability(name="build_orchestration", status=CapabilityStatus.DECLARED, operations=["plan", "record"]),
            Capability(name="artifact_verification", status=CapabilityStatus.DECLARED, operations=["inspect", "hash"]),
            Capability(name="release_management", status=CapabilityStatus.DECLARED, operations=["create", "promote"]),
            Capability(name="deployment_planning", status=CapabilityStatus.DECLARED, operations=["plan", "dry_run", "rollback_plan"]),
        ]

        reg = EntityRegistration(
            entity_id=ENTITY_ID,
            entity_type=EntityType.SOFTWARE_SERVICE,
            adapter_id=ADAPTER_ID,
            protocol_version="0.1.1",
            capabilities=caps,
            health=health,
            operational_state=OperationalState.HEALTHY,
            registration_source="conflux.boot",
            metadata={
                "subsystem": "conflux",
                "api_prefix": "/conflux",
                "runner_default": "disabled",
                "deploy_default": "dry_run",
            },
        )
        stored = plane.register_entity(reg)
        return {"ok": True, "entity": stored.to_dict()}
    except Exception as e:
        logger.warning("Conflux control-plane registration failed: %s", e)
        return {"ok": False, "error": str(e)}


def heartbeat(get_plane=None, *, health: str = "healthy") -> dict:
    try:
        if get_plane is None:
            from dashboard.control_ops import get_control_plane

            plane = get_control_plane()
        else:
            plane = get_plane()
        ent = plane.heartbeat(ENTITY_ID, health=health)
        if ent is None:
            return register_with_control_plane(get_plane=lambda: plane, health=health)
        return {"ok": True, "entity": ent.to_dict()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
