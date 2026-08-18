"""In-process selftest for mining provenance (no Redis required for model logic)."""

from __future__ import annotations

from .models import (
    AuroraCustodyRecord,
    EvidenceLevel,
    MiningEvent,
    OnChainUTXO,
    WorkerIdentity,
)


def selftest() -> bool:
    w = WorkerIdentity(
        worker_id="node-17",
        node_id="node-17",
        facility_domain="AZ-01",
        pool_id="pool-X",
    )
    assert w.to_dict()["facility_domain"] == "AZ-01"

    ev = MiningEvent(
        event_id="abc123",
        epoch=1842,
        worker_id="node-17",
        node_id="node-17",
        pool_id="pool-X",
        share_id="s1",
        evidence=int(EvidenceLevel.OBSERVED_SHARE),
    )
    assert ev.evidence_label() == "observed_share"
    ev.evidence = int(EvidenceLevel.POOL_ACCEPTED)
    assert ev.evidence_label() == "pool_accepted"

    u = OnChainUTXO(txid="deadbeef", vout=0, amount_sats=1000, address="bcrt1qtest")
    assert u.key() == "deadbeef:0"

    c = AuroraCustodyRecord(
        utxo_key=u.key(),
        amount_sats=1000,
        on_chain=u.to_dict(),
        custody_path=["treasury", "vault-A", "policy-7"],
        last_epoch=1842,
        observed_by="dashboard",
    )
    d = c.to_dict()
    assert d["kind"] == "aurora_custody_observation"
    assert "Not proven by the Bitcoin" in d["disclaimer"]

    # Never claim stronger without upgrade path
    assert EvidenceLevel.OBSERVED_SHARE < EvidenceLevel.COINBASE_ASSOCIATED
    return True


if __name__ == "__main__":
    assert selftest()
    print("mining_provenance selftest OK")
