"""
Mining Provenance service — record, query, epoch snapshot.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from comms.layer import CommsLayer

from .models import (
    AuroraCustodyRecord,
    EvidenceLevel,
    MiningEvent,
    OnChainUTXO,
    WorkerIdentity,
)

logger = logging.getLogger("aurora.mining_provenance")

WORKER_PREFIX = "mining:worker:"
EVENT_PREFIX = "mining:event:"
EVENT_INDEX = "mining:events:index"
UTXO_PREFIX = "mining:utxo:"
CUSTODY_PREFIX = "mining:custody:"
PROVENANCE_PREFIX = "mining:provenance:"


class MiningProvenance:
    def __init__(self, comms: CommsLayer):
        self.comms = comms
        self.node_id = comms.node_id

    # ------------------------------------------------------------------
    # Workers
    # ------------------------------------------------------------------

    def register_worker(self, identity: WorkerIdentity) -> WorkerIdentity:
        identity.updated_at = time.time()
        self.comms.set_state(f"{WORKER_PREFIX}{identity.worker_id}", identity.to_dict(), expire=0)
        logger.info(
            f"Worker registered {identity.worker_id} facility={identity.facility_domain} "
            f"pool={identity.pool_id}"
        )
        return identity

    def get_worker(self, worker_id: str) -> Optional[WorkerIdentity]:
        raw = self.comms.get_state(f"{WORKER_PREFIX}{worker_id}")
        if isinstance(raw, dict):
            return WorkerIdentity.from_dict(raw)
        return None

    def list_workers(self, limit: int = 100) -> List[WorkerIdentity]:
        out: List[WorkerIdentity] = []
        try:
            keys = list(self.comms.r.keys(f"aurora:{WORKER_PREFIX}*") or []) if hasattr(self.comms, "r") else []
            for k in keys[:limit]:
                key = k.replace("aurora:", "", 1) if str(k).startswith("aurora:") else k
                raw = self.comms.get_state(key)
                if isinstance(raw, dict):
                    out.append(WorkerIdentity.from_dict(raw))
        except Exception as e:
            logger.debug(f"list_workers: {e}")
        return out

    # ------------------------------------------------------------------
    # Events (progressive evidence)
    # ------------------------------------------------------------------

    def record_event(self, event: MiningEvent) -> MiningEvent:
        if not event.event_id:
            event.event_id = uuid.uuid4().hex[:16]
        self.comms.set_state(f"{EVENT_PREFIX}{event.event_id}", event.to_dict(), expire=86400 * 30)
        # Index by epoch and worker
        try:
            idx = self.comms.get_state(EVENT_INDEX) or {"by_epoch": {}, "by_worker": {}, "by_txid": {}}
            if not isinstance(idx, dict):
                idx = {"by_epoch": {}, "by_worker": {}, "by_txid": {}}
            ep = str(event.epoch)
            idx.setdefault("by_epoch", {}).setdefault(ep, [])
            if event.event_id not in idx["by_epoch"][ep]:
                idx["by_epoch"][ep] = (idx["by_epoch"][ep] + [event.event_id])[-500:]
            idx.setdefault("by_worker", {}).setdefault(event.worker_id, [])
            if event.event_id not in idx["by_worker"][event.worker_id]:
                idx["by_worker"][event.worker_id] = (
                    idx["by_worker"][event.worker_id] + [event.event_id]
                )[-200:]
            if event.reward_txid:
                idx.setdefault("by_txid", {}).setdefault(event.reward_txid, [])
                if event.event_id not in idx["by_txid"][event.reward_txid]:
                    idx["by_txid"][event.reward_txid].append(event.event_id)
            self.comms.set_state(EVENT_INDEX, idx, expire=0)
        except Exception as e:
            logger.debug(f"event index: {e}")
        return event

    def observe_share(
        self,
        *,
        worker_id: str,
        epoch: int,
        pool_id: str = "",
        job_id: str = "",
        share_id: str = "",
        difficulty: float = 0.0,
        facility_domain: str = "unknown",
        energy_epoch: str = "",
        **meta,
    ) -> MiningEvent:
        w = self.get_worker(worker_id)
        ev = MiningEvent(
            event_id=uuid.uuid4().hex[:16],
            epoch=epoch,
            worker_id=worker_id,
            node_id=(w.node_id if w else self.node_id),
            pool_id=pool_id or (w.pool_id if w else ""),
            job_id=job_id,
            share_id=share_id or uuid.uuid4().hex[:12],
            difficulty=difficulty,
            accepted=False,
            evidence=int(EvidenceLevel.OBSERVED_SHARE),
            facility_domain=facility_domain or (w.facility_domain if w else "unknown"),
            energy_epoch=energy_epoch,
            meta=meta,
        )
        return self.record_event(ev)

    def upgrade_evidence(
        self,
        event_id: str,
        level: EvidenceLevel,
        *,
        reward_txid: str = "",
        reward_vout: Optional[int] = None,
        pool_account: str = "",
        notes: str = "",
    ) -> Optional[MiningEvent]:
        raw = self.comms.get_state(f"{EVENT_PREFIX}{event_id}")
        if not isinstance(raw, dict):
            return None
        ev = MiningEvent.from_dict(raw)
        if int(level) < ev.evidence:
            return ev  # never downgrade
        ev.evidence = int(level)
        if int(level) >= int(EvidenceLevel.POOL_ACCEPTED):
            ev.accepted = True
        if reward_txid:
            ev.reward_txid = reward_txid
        if reward_vout is not None:
            ev.reward_vout = reward_vout
        if pool_account:
            ev.pool_account = pool_account
        if notes:
            ev.notes = notes
        return self.record_event(ev)

    def events_for_epoch(self, epoch: int, limit: int = 100) -> List[MiningEvent]:
        return self._events_from_index("by_epoch", str(epoch), limit)

    def events_for_worker(self, worker_id: str, limit: int = 100) -> List[MiningEvent]:
        return self._events_from_index("by_worker", worker_id, limit)

    def events_for_txid(self, txid: str, limit: int = 50) -> List[MiningEvent]:
        return self._events_from_index("by_txid", txid, limit)

    def _events_from_index(self, bucket: str, key: str, limit: int) -> List[MiningEvent]:
        out: List[MiningEvent] = []
        try:
            idx = self.comms.get_state(EVENT_INDEX) or {}
            ids = (idx.get(bucket) or {}).get(key) or []
            for eid in list(ids)[-limit:]:
                raw = self.comms.get_state(f"{EVENT_PREFIX}{eid}")
                if isinstance(raw, dict):
                    out.append(MiningEvent.from_dict(raw))
        except Exception as e:
            logger.debug(f"_events_from_index: {e}")
        return out

    # ------------------------------------------------------------------
    # On-chain UTXO (Bitcoin facts) vs custody (Aurora observation)
    # ------------------------------------------------------------------

    def record_utxo(self, utxo: OnChainUTXO) -> OnChainUTXO:
        self.comms.set_state(f"{UTXO_PREFIX}{utxo.key()}", utxo.to_dict(), expire=0)
        return utxo

    def get_utxo(self, txid: str, vout: int) -> Optional[OnChainUTXO]:
        raw = self.comms.get_state(f"{UTXO_PREFIX}{txid}:{vout}")
        if isinstance(raw, dict):
            return OnChainUTXO.from_dict(raw)
        return None

    def record_custody(self, rec: AuroraCustodyRecord) -> AuroraCustodyRecord:
        self.comms.set_state(f"{CUSTODY_PREFIX}{rec.utxo_key}", rec.to_dict(), expire=0)
        return rec

    def get_custody(self, utxo_key: str) -> Optional[Dict[str, Any]]:
        raw = self.comms.get_state(f"{CUSTODY_PREFIX}{utxo_key}")
        return raw if isinstance(raw, dict) else None

    # ------------------------------------------------------------------
    # Provenance graph queries
    # ------------------------------------------------------------------

    def provenance_for_txid(self, txid: str) -> Dict[str, Any]:
        events = self.events_for_txid(txid)
        workers = {}
        for ev in events:
            if ev.worker_id not in workers:
                w = self.get_worker(ev.worker_id)
                workers[ev.worker_id] = w.to_dict() if w else {"worker_id": ev.worker_id}
        utxos = []
        custody = []
        for ev in events:
            if ev.reward_txid and ev.reward_vout is not None:
                u = self.get_utxo(ev.reward_txid, ev.reward_vout)
                if u:
                    utxos.append(u.to_dict())
                    c = self.get_custody(u.key())
                    if c:
                        custody.append(c)
        return {
            "txid": txid,
            "bitcoin_proves": "Transaction/UTXO existence and value movement between scripts/addresses only.",
            "aurora_observes": "Worker identity, facility domain, share evidence tiers, optional custody path.",
            "events": [e.to_dict() for e in events],
            "workers": workers,
            "utxos": utxos,
            "custody_observations": custody,
            "strongest_evidence": max((e.evidence for e in events), default=0),
        }

    def who_epoch(self, epoch: int) -> Dict[str, Any]:
        events = self.events_for_epoch(epoch)
        by_worker: Dict[str, Dict[str, Any]] = {}
        for ev in events:
            row = by_worker.setdefault(
                ev.worker_id,
                {
                    "worker_id": ev.worker_id,
                    "events": 0,
                    "max_evidence": 0,
                    "facility_domain": ev.facility_domain,
                    "pool_id": ev.pool_id,
                },
            )
            row["events"] += 1
            row["max_evidence"] = max(row["max_evidence"], ev.evidence)
        return {
            "epoch": epoch,
            "workers": list(by_worker.values()),
            "event_count": len(events),
            "disclaimer": "Operational observations. Not Bitcoin consensus facts about hardware.",
        }

    def epoch_snapshot(self, epoch: int) -> Dict[str, Any]:
        """Compact contribution for epoch state root."""
        who = self.who_epoch(epoch)
        return {
            "epoch": epoch,
            "worker_count": len(who["workers"]),
            "event_count": who["event_count"],
            "workers": sorted(
                [
                    {
                        "worker_id": w["worker_id"],
                        "events": w["events"],
                        "max_evidence": w["max_evidence"],
                        "facility": w["facility_domain"],
                    }
                    for w in who["workers"]
                ],
                key=lambda x: x["worker_id"],
            ),
        }
