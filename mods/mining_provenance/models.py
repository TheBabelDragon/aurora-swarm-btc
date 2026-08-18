"""
Mining Provenance models.

Bitcoin proves transaction/UTXO existence and coin movement.
It does NOT prove which physical machine produced a particular sat.

Aurora records progressive operational evidence — never pretends
on-chain data contains facility location or hardware identity.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from typing import Any, Dict, List, Optional


class EvidenceLevel(IntEnum):
    """Stronger levels require stronger external corroboration."""

    OBSERVED_SHARE = 1       # worker submitted valid share (local observation)
    POOL_ACCEPTED = 2        # pool accepted the share
    POOL_CREDITED = 3        # pool credited worker/account
    COINBASE_ASSOCIATED = 4  # identifiable reward tx linked by operational policy


EVIDENCE_LABELS = {
    EvidenceLevel.OBSERVED_SHARE: "observed_share",
    EvidenceLevel.POOL_ACCEPTED: "pool_accepted",
    EvidenceLevel.POOL_CREDITED: "pool_credited",
    EvidenceLevel.COINBASE_ASSOCIATED: "coinbase_associated",
}


@dataclass
class WorkerIdentity:
    worker_id: str
    node_id: str
    pubkey_fingerprint: str = ""
    hardware_id: str = ""
    pool_id: str = ""
    pool_worker_name: str = ""
    facility_domain: str = "unknown"  # topology site/domain
    power_domain: str = "unknown"
    network_domain: str = "unknown"
    rack: str = "unknown"
    extra: Dict[str, str] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkerIdentity":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        kwargs = {k: v for k, v in d.items() if k in known}
        return cls(**kwargs)


@dataclass
class MiningEvent:
    event_id: str
    epoch: int
    worker_id: str
    node_id: str
    pool_id: str
    job_id: str = ""
    share_id: str = ""
    difficulty: float = 0.0
    accepted: bool = False
    evidence: int = int(EvidenceLevel.OBSERVED_SHARE)
    facility_domain: str = "unknown"
    energy_epoch: str = ""
    timestamp: float = field(default_factory=time.time)
    # Optional progressive links
    pool_account: str = ""
    reward_txid: str = ""
    reward_vout: Optional[int] = None
    notes: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    def evidence_label(self) -> str:
        try:
            return EVIDENCE_LABELS[EvidenceLevel(self.evidence)]
        except Exception:
            return f"level_{self.evidence}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["evidence_label"] = self.evidence_label()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MiningEvent":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore
        kwargs = {k: v for k, v in d.items() if k in known}
        if "event_id" not in kwargs:
            kwargs["event_id"] = uuid.uuid4().hex[:16]
        return cls(**kwargs)

    def fingerprint(self) -> str:
        body = f"{self.epoch}:{self.worker_id}:{self.share_id}:{self.job_id}:{self.timestamp}"
        return hashlib.sha256(body.encode()).hexdigest()[:32]


@dataclass
class OnChainUTXO:
    """What Bitcoin actually proves — nothing about which miner machine."""

    txid: str
    vout: int
    amount_sats: int
    address: str = ""
    script_hex: str = ""
    block_height: Optional[int] = None
    confirmations: int = 0

    def key(self) -> str:
        return f"{self.txid}:{self.vout}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "OnChainUTXO":
        return cls(
            txid=str(d["txid"]),
            vout=int(d["vout"]),
            amount_sats=int(d.get("amount_sats") or d.get("amount") or 0),
            address=str(d.get("address") or ""),
            script_hex=str(d.get("script_hex") or ""),
            block_height=d.get("block_height"),
            confirmations=int(d.get("confirmations") or 0),
        )


@dataclass
class AuroraCustodyRecord:
    """
    Operational custody observation — NOT an on-chain fact.

    Explicitly labeled so it cannot be confused with Bitcoin truth.
    """

    utxo_key: str
    amount_sats: int
    on_chain: Dict[str, Any]
    custody_path: List[str] = field(default_factory=list)  # e.g. treasury / vault-A / policy-7
    last_epoch: int = 0
    observed_by: str = ""
    note: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = "aurora_custody_observation"
        d["disclaimer"] = (
            "Aurora operational observation only. "
            "Not proven by the Bitcoin consensus layer."
        )
        return d
