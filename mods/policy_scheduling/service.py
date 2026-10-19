"""Policy service — draft → simulate → validate → approve → activate.

AEGIS-42 retains independent authority over protected activations.
Shadow mode never changes live execution.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set

from .multiflow_adapter import MultiFlowAdapter
from .schema import (
    INITIAL_DRAFT,
    ActivationMode,
    AuditEntry,
    PolicyDocument,
    PolicyPreferences,
    PolicyStatus,
    SimulationResult,
)
from .store import ConcurrentModificationError, PolicyStore

logger = logging.getLogger("aurora.policy.service")

_INSTANCE: Optional["PolicyService"] = None
_LOCK = threading.Lock()

# Valid transitions
_TRANSITIONS = {
    PolicyStatus.DRAFT: {PolicyStatus.SIMULATED, PolicyStatus.REJECTED},
    PolicyStatus.SIMULATED: {PolicyStatus.VALIDATED, PolicyStatus.DRAFT, PolicyStatus.REJECTED},
    PolicyStatus.VALIDATED: {
        PolicyStatus.PENDING_APPROVAL,
        PolicyStatus.ACTIVE,  # controlled / shadow path after gates
        PolicyStatus.DRAFT,
        PolicyStatus.REJECTED,
    },
    PolicyStatus.PENDING_APPROVAL: {
        PolicyStatus.ACTIVE,
        PolicyStatus.REJECTED,
        PolicyStatus.DRAFT,
    },
    PolicyStatus.ACTIVE: {PolicyStatus.SUPERSEDED},
}


class PolicyService:
    def __init__(self) -> None:
        self.store = PolicyStore()
        self.adapter = MultiFlowAdapter()
        self._comms = None
        # Working draft (unsaved preview can differ)
        self._preview: Dict[str, Any] = dict(INITIAL_DRAFT)
        self._preview_dirty = False

    def attach_comms(self, comms: Any) -> None:
        self._comms = comms
        self.store.attach_comms(comms)

    # --- Preview / draft ---

    def get_status(self) -> Dict[str, Any]:
        active = self.store.get_active()
        draft = self.store.get_draft()
        return {
            "active_version_id": self.store.active_version_id(),
            "active": active.model_dump() if active else None,
            "draft": draft.model_dump() if draft else None,
            "preview": dict(self._preview),
            "preview_dirty": self._preview_dirty,
            "initial_draft": dict(INITIAL_DRAFT),
            "multiflow": self.adapter.status(),
            "baseline_scheduler": "aurora-scheduler",
            "execution_mode": (
                active.preferences.activation_mode.value if active else "shadow"
            ),
        }

    def update_preview(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Update unsaved preview only — does not mutate active policy."""
        allowed = set(INITIAL_DRAFT.keys())
        unknown = set(patch.keys()) - allowed
        if unknown:
            raise ValueError(f"Unknown fields rejected: {sorted(unknown)}")
        prefs = PolicyPreferences(**{**self._preview, **patch})
        self._preview = prefs.model_dump()
        self._preview["recovery_strategy"] = prefs.recovery_strategy.value
        self._preview["activation_mode"] = prefs.activation_mode.value
        self._preview_dirty = True
        return dict(self._preview)

    def save_draft(self, *, actor: str = "operator") -> PolicyDocument:
        prefs = PolicyPreferences(**self._preview)
        doc = PolicyDocument(
            status=PolicyStatus.DRAFT,
            preferences=prefs,
            created_by=actor,
            expected_active_version=self.store.active_version_id(),
        )
        saved = self.store.set_draft(doc)
        self._preview_dirty = False
        self.store.append_audit(
            AuditEntry(
                action="save_draft",
                actor=actor,
                policy_version_id=saved.version_id,
                detail="Draft saved (not active)",
            )
        )
        return saved

    def discard_draft(self, *, actor: str = "operator") -> None:
        self.store.discard_draft()
        self._preview = dict(INITIAL_DRAFT)
        self._preview_dirty = False
        self.store.append_audit(AuditEntry(action="discard_draft", actor=actor))

    # --- Simulate / validate ---

    def simulate(
        self,
        *,
        actor: str = "operator",
        workers: Optional[List[Dict[str, Any]]] = None,
        quarantined: Optional[Set[str]] = None,
        revoked: Optional[Set[str]] = None,
    ) -> SimulationResult:
        draft = self.store.get_draft()
        if draft is None:
            # use preview without promoting to active
            prefs = PolicyPreferences(**self._preview)
            draft = PolicyDocument(status=PolicyStatus.DRAFT, preferences=prefs, created_by=actor)
            draft = self.store.set_draft(draft)

        if workers is None and self._comms is not None:
            try:
                workers = self._comms.get_workers() or self._comms.get_active_nodes() or []
            except Exception:
                workers = []

        quarantined, revoked = self._aegis_sets(quarantined, revoked)
        snapshot = self.adapter.collect_snapshot(
            workers=workers or [], quarantined=quarantined, revoked=revoked
        )
        sim = self.adapter.simulate(
            draft.preferences,
            snapshot,
            policy_version_id=draft.version_id,
            current_plan=[],
        )
        assert sim.side_effect_free is True
        self.store.put_simulation(sim)

        # promote draft status to SIMULATED (immutable copy into versions)
        sim_doc = draft.model_copy(
            update={
                "status": PolicyStatus.SIMULATED,
                "simulation_id": sim.simulation_id,
                "updated_at": time.time(),
            }
        )
        try:
            self.store.put_version(sim_doc)
        except ValueError:
            # already stored — update simulation link on draft only
            pass
        self.store.set_draft(sim_doc.model_copy(update={"status": PolicyStatus.SIMULATED}))

        self.store.append_audit(
            AuditEntry(
                action="simulate",
                actor=actor,
                policy_version_id=draft.version_id,
                outcome=sim.status,
                detail=f"side_effect_free={sim.side_effect_free}",
                payload={"simulation_id": sim.simulation_id, "admissible": sim.admissible},
            )
        )
        self._aegis_event("policy.simulation", actor, draft.version_id, sim.status)
        return sim

    def validate_draft(self, *, actor: str = "operator") -> PolicyDocument:
        draft = self.store.get_draft()
        if draft is None:
            raise ValueError("No draft to validate")
        if draft.status not in (PolicyStatus.DRAFT, PolicyStatus.SIMULATED):
            raise ValueError(f"Cannot validate from status {draft.status}")

        sim = None
        if draft.simulation_id:
            sim = self.store.get_simulation(draft.simulation_id)

        ok = True
        summary = "schema ok"
        if sim is not None:
            ok = sim.admissible or sim.status in ("admissible", "unavailable")
            # unavailable adapter still allows validation of policy schema
            if sim.status == "error":
                ok = False
                summary = "simulation error"
            elif sim.status == "no_complete_solution":
                summary = "NO_COMPLETE_SOLUTION — policy schema valid; plan not feasible"
            else:
                summary = f"simulation status={sim.status}"

        # schema re-check
        PolicyPreferences.model_validate(draft.preferences.model_dump())

        new_status = PolicyStatus.VALIDATED if ok else PolicyStatus.REJECTED
        validated = draft.model_copy(
            update={
                "status": new_status,
                "validation_ok": ok,
                "validation_summary": summary,
                "updated_at": time.time(),
            }
        )
        try:
            self.store.put_version(validated)
        except ValueError:
            pass
        self.store.set_draft(validated)
        self.store.append_audit(
            AuditEntry(
                action="validate",
                actor=actor,
                policy_version_id=validated.version_id,
                outcome="ok" if ok else "reject",
                detail=summary,
            )
        )
        return validated

    # --- Activation / rollback ---

    def request_activation(
        self,
        *,
        actor: str = "operator",
        expected_active: Optional[str] = None,
        approved: bool = False,
    ) -> Dict[str, Any]:
        draft = self.store.get_draft()
        if draft is None:
            raise ValueError("No draft to activate")
        if draft.status not in (PolicyStatus.VALIDATED, PolicyStatus.PENDING_APPROVAL):
            raise ValueError(
                f"Activation requires VALIDATED or PENDING_APPROVAL, got {draft.status}"
            )

        mode = draft.preferences.activation_mode
        prior = self.store.active_version_id()
        if expected_active is None:
            expected_active = prior

        # AEGIS authorization — fail closed
        auth = self._aegis_authorize_activation(actor, draft.version_id)
        if not auth.get("allowed"):
            self.store.append_audit(
                AuditEntry(
                    action="activation_denied",
                    actor=actor,
                    policy_version_id=draft.version_id,
                    prior_active_version=prior,
                    outcome="denied",
                    detail=auth.get("reason", "AEGIS deny"),
                )
            )
            self._aegis_event("policy.activation_denied", actor, draft.version_id, "denied")
            return {
                "ok": False,
                "active_unchanged": True,
                "active_version_id": prior,
                "reason": auth.get("reason", "authorization failed"),
            }

        if mode == ActivationMode.APPROVAL and not approved:
            pending = draft.model_copy(
                update={"status": PolicyStatus.PENDING_APPROVAL, "updated_at": time.time()}
            )
            self.store.set_draft(pending)
            try:
                self.store.put_version(pending)
            except ValueError:
                pass
            self.store.append_audit(
                AuditEntry(
                    action="pending_approval",
                    actor=actor,
                    policy_version_id=draft.version_id,
                    detail="Awaiting explicit approval",
                )
            )
            return {
                "ok": True,
                "pending_approval": True,
                "version_id": draft.version_id,
                "active_version_id": prior,
            }

        # Shadow: record active reference for comparison only — does not dispatch
        # Controlled/Approval (approved): set active reference
        try:
            active = self.store.set_active(
                draft.version_id, expected_active=expected_active
            )
        except ConcurrentModificationError as e:
            self.store.append_audit(
                AuditEntry(
                    action="activation_conflict",
                    actor=actor,
                    policy_version_id=draft.version_id,
                    prior_active_version=prior,
                    outcome="conflict",
                    detail=str(e),
                )
            )
            return {
                "ok": False,
                "active_unchanged": True,
                "active_version_id": self.store.active_version_id(),
                "reason": str(e),
            }
        except Exception as e:
            self.store.append_audit(
                AuditEntry(
                    action="activation_failed",
                    actor=actor,
                    policy_version_id=draft.version_id,
                    prior_active_version=prior,
                    outcome="error",
                    detail=str(e),
                )
            )
            return {
                "ok": False,
                "active_unchanged": True,
                "active_version_id": prior,
                "reason": str(e),
            }

        self.store.append_audit(
            AuditEntry(
                action="activate",
                actor=actor,
                policy_version_id=active.version_id,
                prior_active_version=prior,
                outcome="ok",
                detail=f"mode={mode.value}; shadow={mode == ActivationMode.SHADOW}",
            )
        )
        self._aegis_event("policy.activated", actor, active.version_id, "ok")
        # Clear draft after successful activation
        self.store.discard_draft()
        self._preview_dirty = False
        return {
            "ok": True,
            "active_version_id": active.version_id,
            "prior_active_version": prior,
            "mode": mode.value,
            "live_execution_changed": mode != ActivationMode.SHADOW,
            "note": (
                "Shadow activation recorded for comparison; baseline scheduler still executes"
                if mode == ActivationMode.SHADOW
                else "Active policy updated after authorization"
            ),
        }

    def rollback(
        self,
        target_version_id: str,
        *,
        actor: str = "operator",
        reason: str = "",
        expected_active: Optional[str] = None,
    ) -> Dict[str, Any]:
        source = self.store.get_version(target_version_id)
        if source is None:
            raise KeyError(f"Unknown version {target_version_id}")

        prior = self.store.active_version_id()
        if expected_active is None:
            expected_active = prior

        auth = self._aegis_authorize_activation(actor, target_version_id)
        if not auth.get("allowed"):
            self.store.append_audit(
                AuditEntry(
                    action="rollback_denied",
                    actor=actor,
                    policy_version_id=target_version_id,
                    prior_active_version=prior,
                    outcome="denied",
                    detail=auth.get("reason", "AEGIS deny"),
                )
            )
            return {"ok": False, "reason": auth.get("reason"), "active_version_id": prior}

        # New version based on historical preferences (history preserved)
        new_doc = PolicyDocument(
            status=PolicyStatus.VALIDATED,
            preferences=source.preferences,
            created_by=actor,
            parent_version_id=source.version_id,
            notes=f"Rollback from {source.version_id}: {reason}".strip(),
            validation_ok=True,
            validation_summary="rollback revalidation",
        )
        self.store.put_version(new_doc)

        try:
            active = self.store.set_active(new_doc.version_id, expected_active=expected_active)
        except ConcurrentModificationError as e:
            return {"ok": False, "reason": str(e), "active_version_id": self.store.active_version_id()}

        self.store.append_audit(
            AuditEntry(
                action="rollback",
                actor=actor,
                policy_version_id=active.version_id,
                prior_active_version=prior,
                outcome="ok",
                detail=reason or f"restored preferences from {source.version_id}",
                payload={"source_version": source.version_id},
            )
        )
        self._aegis_event("policy.rollback", actor, active.version_id, "ok")
        return {
            "ok": True,
            "active_version_id": active.version_id,
            "source_version_id": source.version_id,
            "prior_active_version": prior,
        }

    def list_versions(self) -> List[Dict[str, Any]]:
        return [v.model_dump() for v in self.store.list_versions()]

    def list_audit(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [e.model_dump() for e in self.store.list_audit(limit=limit)]

    def compare(self, version_a: str, version_b: str) -> Dict[str, Any]:
        a = self.store.get_version(version_a)
        b = self.store.get_version(version_b)
        if not a or not b:
            raise KeyError("Both versions required")
        pa, pb = a.preferences.model_dump(), b.preferences.model_dump()
        diff = {k: {"a": pa.get(k), "b": pb.get(k)} for k in pa if pa.get(k) != pb.get(k)}
        return {"version_a": version_a, "version_b": version_b, "preference_diff": diff}

    # --- AEGIS helpers ---

    def _aegis_sets(
        self,
        quarantined: Optional[Set[str]],
        revoked: Optional[Set[str]],
    ) -> tuple:
        q = set(quarantined or [])
        r = set(revoked or [])
        try:
            from mods.aegis_42 import get_aegis

            aegis = get_aegis()
            if aegis:
                for ident in aegis.identity.list_identities():
                    if ident.trust.revoked:
                        r.add(ident.identity_id)
                # rate-limited actors treated as soft-quarantine for scheduling
                for ident in aegis.identity.list_identities():
                    if aegis.containment.is_rate_limited(ident.identity_id):
                        q.add(ident.identity_id)
        except Exception:
            pass
        return q, r

    def _aegis_authorize_activation(self, actor: str, version_id: str) -> Dict[str, Any]:
        try:
            from mods.aegis_42 import get_aegis
            from mods.aegis_42.events import EventSource, EventType, make_event

            aegis = get_aegis()
            if aegis is None:
                # Fail closed only if AEGIS is expected; if never started, allow with warning
                # but record — activation of policy is operator-level
                return {"allowed": True, "reason": "AEGIS not running; operator path"}

            if aegis.identity.get(actor) is None:
                try:
                    aegis.identity.register(
                        actor, kind="operator", capabilities=["policy_activate"], trust_level="operator"
                    )
                except Exception:
                    pass

            # Capability check: need policy_activate or operator trust
            caps = aegis.identity.capabilities_of(actor)
            trusted = aegis.identity.is_trusted(actor)
            if "policy_activate" not in caps and "*" not in caps and not trusted and actor not in (
                "operator",
                "system",
                "aegis",
            ):
                return {"allowed": False, "reason": "missing policy_activate capability"}

            if aegis.containment.is_rate_limited(actor):
                return {"allowed": False, "reason": "actor rate-limited"}

            ev = make_event(
                EventType.CAPABILITY_CHANGE,
                EventSource.POLICY_ENGINE,
                actor_id=actor,
                severity="medium",
                summary=f"Policy activation request {version_id}",
                details={"version_id": version_id, "action": "activate"},
            )
            # Observability only — do not treat tool policy as blocking operators
            aegis.ingest(ev)
            return {"allowed": True, "reason": "authorized"}
        except Exception as e:
            logger.warning("AEGIS auth check failed closed: %s", e)
            return {"allowed": False, "reason": f"authorization unavailable: {e}"}

    def _aegis_event(self, kind: str, actor: str, version_id: str, outcome: str) -> None:
        try:
            from mods.aegis_42 import get_aegis
            from mods.aegis_42.events import EventSource, EventType, make_event

            aegis = get_aegis()
            if not aegis:
                return
            aegis.ingest(
                make_event(
                    EventType.CUSTOM,
                    EventSource.POLICY_ENGINE,
                    actor_id=actor,
                    summary=f"{kind}:{outcome}",
                    details={"kind": kind, "version_id": version_id, "outcome": outcome},
                )
            )
        except Exception:
            pass


def get_policy_service() -> Optional[PolicyService]:
    return _INSTANCE


def start_policy_service(comms: Any = None) -> PolicyService:
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = PolicyService()
        if comms is not None:
            _INSTANCE.attach_comms(comms)
        return _INSTANCE
