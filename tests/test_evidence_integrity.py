"""Shared Evidence Contract Phase 6 — Aurora Mesh evidence integrity."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from mods.evidence_integrity import (
    EvidenceObject,
    IntegrityStatus,
    content_hash,
    build_evidence_object,
    verify_integrity,
    check_schema,
    EvidenceStore,
)


def test_content_hash_deterministic():
    p = {"kind": "observation", "value": 25.0, "unit": "C"}
    assert content_hash(p) == content_hash(dict(p))
    assert content_hash(p) != content_hash({"kind": "observation", "value": 25.1, "unit": "C"})


def test_build_and_verify():
    obj = build_evidence_object(
        {"decision_id": "dec-1", "outcome": "ADMITTED"},
        node_id="node-a",
        sequence=1,
        evidence_refs=[{"schema_id": "multiflow.decision_evidence", "event_id": "dec-1"}],
    )
    assert obj.content_hash
    assert verify_integrity(obj) == IntegrityStatus.VALID
    check_schema(obj)


def test_tamper_detected():
    obj = build_evidence_object({"x": 1})
    obj.payload["x"] = 2
    assert verify_integrity(obj) == IntegrityStatus.HASH_MISMATCH


def test_empty_payload_rejected():
    with pytest.raises(ValueError):
        build_evidence_object({})


def test_store_append_idempotent():
    store = EvidenceStore()
    obj = build_evidence_object({"a": 1})
    h1 = store.append(obj)
    h2 = store.append(obj)
    assert h1 == h2
    assert len(store) == 1


def test_store_rejects_corrupt():
    store = EvidenceStore()
    obj = build_evidence_object({"a": 1})
    obj.payload["a"] = 99
    with pytest.raises(ValueError):
        store.append(obj)


def test_replication_no_rewrite():
    store_a = EvidenceStore()
    o1 = build_evidence_object({"n": 1}, node_id="a")
    o2 = build_evidence_object({"n": 2}, node_id="a")
    store_a.append(o1)
    store_a.append(o2)

    store_b = EvidenceStore()
    store_b.append(o1)
    result = store_b.replicate([o1, o2])
    assert o1.content_hash in result.duplicates
    assert o2.content_hash in result.accepted
    assert len(store_b) == 2
    assert store_b.get(o1.content_hash).payload == {"n": 1}


def test_replication_rejects_bad():
    store = EvidenceStore()
    good = build_evidence_object({"ok": True})
    bad = build_evidence_object({"ok": False})
    bad.payload["ok"] = True
    result = store.replicate([good, bad])
    assert good.content_hash in result.accepted
    assert bad.content_hash in result.rejected


def test_export_import_roundtrip():
    store = EvidenceStore()
    store.append(build_evidence_object({"i": 0}))
    store.append(build_evidence_object({"i": 1}, parent_hashes=[store.chain_hashes()[0]]))
    data = store.export()
    store2 = EvidenceStore.import_store(data)
    assert store2.chain_hashes() == store.chain_hashes()
    assert len(store2) == 2


def test_schema_major_fail():
    obj = build_evidence_object({"z": 1})
    obj.schema_version = "1.0.0"
    with pytest.raises(ValueError):
        check_schema(obj)


def test_parent_and_upstream_refs():
    parent = build_evidence_object({"root": True})
    child = build_evidence_object(
        {"derived": True},
        parent_hashes=[parent.content_hash],
        evidence_refs=[
            {"schema_id": "cantheon.metafield_boundary", "event_id": "e1"},
            {"schema_id": "tensorgate.lineage", "event_id": "t1"},
            {"schema_id": "multiflow.decision_evidence", "event_id": "d1"},
        ],
    )
    assert parent.content_hash in child.parent_hashes
    assert len(child.evidence_refs) == 3
    child2 = EvidenceObject.from_dict(child.to_dict())
    assert child2.content_hash == child.content_hash
    assert verify_integrity(child2) == IntegrityStatus.VALID
