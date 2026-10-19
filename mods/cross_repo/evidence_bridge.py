"""Bridge MultiFlow DecisionEvidence (and upstream refs) into Aurora evidence integrity.

Does not grant permissions. Solver evidence never authorizes execution.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aurora.cross_repo.evidence")


def ingest_decision_evidence(
    evidence: Dict[str, Any],
    *,
    node_id: str = "",
    parent_hashes: Optional[List[str]] = None,
    extra_refs: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Store MultiFlow decision evidence in Aurora EvidenceStore.

    Returns content_hash on success, None if store unavailable or invalid.
    """
    try:
        from mods.evidence_integrity.envelope import EvidenceObject, content_hash, SCHEMA_ID, SCHEMA_VERSION
        from mods.evidence_integrity.store import EvidenceStore
    except Exception as e:
        logger.warning("evidence_integrity unavailable: %s", e)
        return None

    if not isinstance(evidence, dict):
        return None

    schema_id = evidence.get("schema_id") or "multiflow.decision_evidence"
    payload = {
        "kind": "multiflow.decision_evidence",
        "schema_id": schema_id,
        "schema_version": evidence.get("schema_version") or "0.1.0",
        "decision": evidence,
    }
    refs = list(evidence.get("evidence_refs") or [])
    if extra_refs:
        refs.extend(extra_refs)

    h = content_hash(payload)
    obj = EvidenceObject(
        content_hash=h,
        payload=payload,
        schema_id=SCHEMA_ID,
        schema_version=SCHEMA_VERSION,
        evidence_refs=refs,
        parent_hashes=list(parent_hashes or []),
        node_id=node_id,
    )
    # Process-local store instance — callers may pass their own later
    store = getattr(ingest_decision_evidence, "_store", None)
    if store is None:
        store = EvidenceStore()
        ingest_decision_evidence._store = store  # type: ignore[attr-defined]
    try:
        return store.append(obj)
    except Exception as e:
        logger.warning("evidence append failed: %s", e)
        return None


def link_evidence_chain(
    *,
    observation_ref: Optional[Dict[str, Any]] = None,
    field_ref: Optional[Dict[str, Any]] = None,
    lineage_ref: Optional[Dict[str, Any]] = None,
    decision_ref: Optional[Dict[str, Any]] = None,
    policy_version_id: Optional[str] = None,
    authorization: Optional[Dict[str, Any]] = None,
    execution: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a linked evidence_refs list for the full Chimera path (where present)."""
    refs: List[Dict[str, Any]] = []
    for label, ref in (
        ("cantheon.observation", observation_ref),
        ("metafield.field_observation", field_ref),
        ("tensorgate.lineage", lineage_ref),
        ("multiflow.decision", decision_ref),
    ):
        if ref:
            item = dict(ref)
            item.setdefault("role", label)
            refs.append(item)
    if policy_version_id:
        refs.append({"role": "aurora.policy_version", "version_id": policy_version_id})
    if authorization:
        refs.append({"role": "aurora.aegis_authorization", **authorization})
    if execution:
        refs.append({"role": "aurora.execution", **execution})
    return {"evidence_refs": refs, "chain_complete": all([observation_ref, decision_ref])}
