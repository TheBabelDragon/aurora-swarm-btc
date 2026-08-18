"""
Local peer evidence for the data plane.

Cryptographic failures are strong signals.
Timeouts / network errors are weak signals.

Reputation affects routing preference only — never whether bytes are accepted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class PeerStats:
    node_id: str
    success: int = 0
    invalid_pieces: int = 0
    failed_challenges: int = 0
    timeouts: int = 0
    stale: int = 0
    last_success: float = 0.0
    last_invalid: float = 0.0
    notes: List[str] = field(default_factory=list)

    def score(self) -> float:
        """
        Higher is better for routing preference.
        Invalid pieces are heavily penalized.
        """
        base = float(self.success) - 5.0 * self.invalid_pieces - 3.0 * self.failed_challenges
        base -= 0.5 * self.timeouts - 0.5 * self.stale
        return base

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "success": self.success,
            "invalid_pieces": self.invalid_pieces,
            "failed_challenges": self.failed_challenges,
            "timeouts": self.timeouts,
            "stale": self.stale,
            "score": self.score(),
            "last_success": self.last_success,
            "last_invalid": self.last_invalid,
        }


class PeerEvidence:
    def __init__(self):
        self._peers: Dict[str, PeerStats] = {}

    def _p(self, node_id: str) -> PeerStats:
        if node_id not in self._peers:
            self._peers[node_id] = PeerStats(node_id=node_id)
        return self._peers[node_id]

    def record_success(self, node_id: str):
        p = self._p(node_id)
        p.success += 1
        p.last_success = time.time()

    def record_invalid_piece(self, node_id: str, note: str = ""):
        p = self._p(node_id)
        p.invalid_pieces += 1
        p.last_invalid = time.time()
        if note:
            p.notes = (p.notes + [note])[-20:]

    def record_failed_challenge(self, node_id: str):
        self._p(node_id).failed_challenges += 1

    def record_timeout(self, node_id: str):
        self._p(node_id).timeouts += 1

    def record_stale(self, node_id: str):
        self._p(node_id).stale += 1

    def ranking(self, candidates: List[str] | None = None) -> List[str]:
        """Order peer ids by preference (best first)."""
        ids = candidates if candidates is not None else list(self._peers.keys())
        return sorted(ids, key=lambda n: self._p(n).score(), reverse=True)

    def snapshot(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in sorted(self._peers.values(), key=lambda x: -x.score())]
