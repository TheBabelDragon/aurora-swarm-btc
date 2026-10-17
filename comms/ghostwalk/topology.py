"""Bounded, time-aware topology model from real observations.

Maps the configured Aurora mesh only — never claims public-internet discovery.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ObservationKind(str, Enum):
    PEER_SEEN = "peer_seen"
    PEER_AUTH = "peer_auth"
    PEER_LOST = "peer_lost"
    LINK_OK = "link_ok"
    LINK_FAIL = "link_fail"
    GATEWAY_ADV = "gateway_adv"
    SERVICE_ADV = "service_adv"
    ROUTE_CHANGE = "route_change"
    CAPABILITY_CHANGE = "capability_change"


class ObservationSource(str, Enum):
    DIRECT = "direct"
    PEER_ADVERTISED = "peer_advertised"
    LOCAL = "local"


@dataclass
class Observation:
    kind: ObservationKind
    subject_id: str
    observer_id: str
    source: ObservationSource
    ts: float
    expires_at: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)
    evidence_ref: str = ""
    sequence: int = 0

    def is_stale(self, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        if self.expires_at <= 0:
            return False
        return now >= self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "observer_id": self.observer_id,
            "source": self.source.value,
            "ts": self.ts,
            "expires_at": self.expires_at,
            "stale": self.is_stale(),
            "payload": dict(self.payload),
            "evidence_ref": self.evidence_ref,
            "sequence": self.sequence,
        }


@dataclass
class TopologySnapshot:
    nodes: Dict[str, Dict[str, Any]]
    links: List[Dict[str, Any]]
    gateways: List[Dict[str, Any]]
    services: Dict[str, List[str]]
    generated_at: float
    observer_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": dict(self.nodes),
            "links": list(self.links),
            "gateways": list(self.gateways),
            "services": {k: list(v) for k, v in self.services.items()},
            "generated_at": self.generated_at,
            "observer_id": self.observer_id,
            "node_count": len(self.nodes),
            "link_count": len(self.links),
        }


class TopologyEngine:
    """Ingest observations; maintain bounded topology view."""

    def __init__(
        self,
        *,
        local_node_id: str = "local",
        default_ttl_s: float = 180.0,
        max_observations: int = 2048,
        max_timeline: int = 256,
        clock=None,
    ):
        self.local_node_id = local_node_id
        self.default_ttl_s = default_ttl_s
        self.max_observations = max_observations
        self.max_timeline = max_timeline
        self._clock = clock or time.time
        self._seq = 0
        self._by_subject: Dict[str, List[Observation]] = {}
        self._timeline: List[Observation] = []
        self._links: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._gateways: Dict[str, Dict[str, Any]] = {}
        self._services: Dict[str, Dict[str, Any]] = {}
        self._node_caps: Dict[str, List[str]] = {}

    def _now(self) -> float:
        return float(self._clock())

    def ingest(
        self,
        kind: ObservationKind,
        subject_id: str,
        *,
        observer_id: str = "",
        source: ObservationSource = ObservationSource.DIRECT,
        payload: Optional[Dict[str, Any]] = None,
        ttl_s: Optional[float] = None,
        evidence_ref: str = "",
        ts: Optional[float] = None,
    ) -> Observation:
        now = ts if ts is not None else self._now()
        ttl = self.default_ttl_s if ttl_s is None else ttl_s
        self._seq += 1
        obs = Observation(
            kind=kind,
            subject_id=(subject_id or "").strip(),
            observer_id=(observer_id or self.local_node_id).strip(),
            source=source,
            ts=now,
            expires_at=now + max(1.0, ttl),
            payload=dict(payload or {}),
            evidence_ref=evidence_ref,
            sequence=self._seq,
        )
        if not obs.subject_id:
            raise ValueError("subject_id required")

        bucket = self._by_subject.setdefault(obs.subject_id, [])
        bucket.append(obs)
        if len(bucket) > 32:
            self._by_subject[obs.subject_id] = bucket[-32:]

        self._timeline.append(obs)
        if len(self._timeline) > self.max_timeline:
            self._timeline = self._timeline[-self.max_timeline :]

        self._apply(obs)
        self._purge()
        return obs

    def _apply(self, obs: Observation) -> None:
        if obs.kind in (ObservationKind.PEER_SEEN, ObservationKind.PEER_AUTH):
            caps = obs.payload.get("capabilities")
            if isinstance(caps, list):
                self._node_caps[obs.subject_id] = [str(c) for c in caps][:32]
            ep = obs.payload.get("endpoint") or obs.payload.get("advertised_endpoint")
            if ep:
                key = (self.local_node_id, obs.subject_id)
                self._links[key] = {
                    "from": self.local_node_id,
                    "to": obs.subject_id,
                    "status": "up",
                    "last_ts": obs.ts,
                    "source": obs.source.value,
                }
        elif obs.kind == ObservationKind.PEER_LOST:
            key = (self.local_node_id, obs.subject_id)
            if key in self._links:
                self._links[key]["status"] = "down"
                self._links[key]["last_ts"] = obs.ts
        elif obs.kind == ObservationKind.LINK_OK:
            frm = str(obs.payload.get("from") or self.local_node_id)
            to = str(obs.payload.get("to") or obs.subject_id)
            self._links[(frm, to)] = {
                "from": frm,
                "to": to,
                "status": "up",
                "last_ts": obs.ts,
                "source": obs.source.value,
            }
        elif obs.kind == ObservationKind.LINK_FAIL:
            frm = str(obs.payload.get("from") or self.local_node_id)
            to = str(obs.payload.get("to") or obs.subject_id)
            self._links[(frm, to)] = {
                "from": frm,
                "to": to,
                "status": "down",
                "last_ts": obs.ts,
                "source": obs.source.value,
                "reason": str(obs.payload.get("reason") or ""),
            }
        elif obs.kind == ObservationKind.GATEWAY_ADV:
            self._gateways[obs.subject_id] = {
                "gateway_id": obs.subject_id,
                "ts": obs.ts,
                "transports": list(obs.payload.get("transports") or []),
                "source": obs.source.value,
                "expires_at": obs.expires_at,
            }
        elif obs.kind == ObservationKind.SERVICE_ADV:
            svc = str(obs.payload.get("service") or obs.subject_id)
            holders = self._services.setdefault(svc, {"holders": [], "ts": obs.ts})
            if obs.subject_id not in holders["holders"]:
                holders["holders"].append(obs.subject_id)
            holders["ts"] = obs.ts
        elif obs.kind == ObservationKind.CAPABILITY_CHANGE:
            caps = obs.payload.get("capabilities")
            if isinstance(caps, list):
                self._node_caps[obs.subject_id] = [str(c) for c in caps][:32]

    def _purge(self) -> None:
        now = self._now()
        total = sum(len(v) for v in self._by_subject.values())
        if total <= self.max_observations:
            return
        # drop oldest stale first
        for sid in list(self._by_subject.keys()):
            kept = [o for o in self._by_subject[sid] if not o.is_stale(now)]
            if not kept and self._by_subject[sid]:
                kept = self._by_subject[sid][-4:]
            self._by_subject[sid] = kept[-16:]
            if not self._by_subject[sid]:
                del self._by_subject[sid]

    def snapshot(self, peer_records: Optional[Dict[str, Dict[str, Any]]] = None) -> TopologySnapshot:
        now = self._now()
        nodes: Dict[str, Dict[str, Any]] = {}
        nodes[self.local_node_id] = {
            "node_id": self.local_node_id,
            "role": "local",
            "capabilities": list(self._node_caps.get(self.local_node_id, [])),
            "fresh": True,
        }
        for sid, obs_list in self._by_subject.items():
            latest = obs_list[-1] if obs_list else None
            if latest is None:
                continue
            pr = (peer_records or {}).get(sid) or {}
            nodes[sid] = {
                "node_id": sid,
                "capabilities": list(self._node_caps.get(sid, pr.get("capabilities") or [])),
                "identity_state": pr.get("identity_state", "unknown"),
                "trust_decision": pr.get("trust_decision", "defer"),
                "last_observation_at": latest.ts,
                "fresh": not latest.is_stale(now),
                "source": latest.source.value,
            }
        services = {k: list(v.get("holders") or []) for k, v in self._services.items()}
        return TopologySnapshot(
            nodes=nodes,
            links=list(self._links.values()),
            gateways=list(self._gateways.values()),
            services=services,
            generated_at=now,
            observer_id=self.local_node_id,
        )

    def timeline(self, limit: int = 50) -> List[Dict[str, Any]]:
        items = self._timeline[-max(1, limit) :]
        return [o.to_dict() for o in items]

    def latest_for(self, subject_id: str) -> Optional[Observation]:
        bucket = self._by_subject.get(subject_id) or []
        return bucket[-1] if bucket else None
