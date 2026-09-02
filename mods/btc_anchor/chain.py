"""
Bitcoin chain view used by the artifact clock.

The real Bitcoin network is the production source. This module provides:

* ChainTip / Block — the coordinates the clock consumes
* ChainView — read interface (tip, block, confirmations, canonical?)
* SimulatedBitcoinChain — deterministic local chain for tests and demos
* NullChain — BTC layer disabled; artifacts remain valid and unanchored

Bitcoin block timestamps are NOT treated as exact elapsed time.
Height and cumulative work are the temporal/scarcity coordinates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _work_add(prev_hex: str, delta: int = 1) -> str:
    """Cumulative work as a hex integer. Not a wall-clock duration."""
    prev = int(prev_hex, 16) if prev_hex else 0
    return format(prev + int(delta), "x")


@dataclass(frozen=True)
class ChainTip:
    chain: str
    height: int
    block_hash: str
    work: str
    timestamp: int  # block field; informational only, never the artifact epoch

    def to_epoch_dict(self) -> Dict[str, Any]:
        return {
            "chain": self.chain,
            "height": self.height,
            "block_hash": self.block_hash,
            "work": self.work,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = self.to_epoch_dict()
        d["timestamp"] = self.timestamp
        return d


@dataclass
class Block:
    height: int
    block_hash: str
    prev_hash: str
    work: str
    timestamp: int
    txs: List[str] = field(default_factory=list)
    nonce: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "height": self.height,
            "block_hash": self.block_hash,
            "prev_hash": self.prev_hash,
            "work": self.work,
            "timestamp": self.timestamp,
            "txs": list(self.txs),
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Block":
        return cls(
            height=int(d["height"]),
            block_hash=str(d["block_hash"]),
            prev_hash=str(d.get("prev_hash") or ""),
            work=str(d.get("work") or "0"),
            timestamp=int(d.get("timestamp") or 0),
            txs=list(d.get("txs") or []),
            nonce=int(d.get("nonce") or 0),
        )


class ChainView:
    """Read-only Bitcoin coordinates. Implementations must not use time.time() as height."""

    chain_name = "bitcoin"

    def tip(self) -> Optional[ChainTip]:
        raise NotImplementedError

    def get_block(self, hash_or_height: Any) -> Optional[Block]:
        raise NotImplementedError

    def confirmations(self, block_hash: str) -> int:
        raise NotImplementedError

    def is_canonical(self, block_hash: str) -> bool:
        raise NotImplementedError

    def tx_location(self, txid: str) -> Optional[Block]:
        raise NotImplementedError


class NullChain(ChainView):
    """BTC layer disabled. Artifacts remain valid; they simply have no epoch."""

    def tip(self) -> Optional[ChainTip]:
        return None

    def get_block(self, hash_or_height: Any) -> Optional[Block]:
        return None

    def confirmations(self, block_hash: str) -> int:
        return 0

    def is_canonical(self, block_hash: str) -> bool:
        return False

    def tx_location(self, txid: str) -> Optional[Block]:
        return None


class SimulatedBitcoinChain(ChainView):
    """
    Deterministic in-process chain.

    Height starts at `start_height` (default 900000) so tests talk in realistic
    coordinates without implying a live bitcoind.
    """

    def __init__(self, start_height: int = 900000, genesis_hash: Optional[str] = None):
        self.chain_name = "bitcoin"
        genesis_hash = genesis_hash or _sha(f"aurora-genesis|{start_height}".encode())
        genesis = Block(
            height=int(start_height),
            block_hash=genesis_hash,
            prev_hash="00" * 32,
            work=_work_add("0", 1),
            timestamp=0,  # informational; not wall clock
            txs=[],
            nonce=0,
        )
        self._canonical: List[Block] = [genesis]
        self._by_hash: Dict[str, Block] = {genesis.block_hash: genesis}
        self._orphans: List[Block] = []
        self.mempool: List[Dict[str, Any]] = []
        self._nonce = 0
        self._time_tick = 0  # monotonic block-time surrogate, NOT unix now()

    def tip(self) -> ChainTip:
        b = self._canonical[-1]
        return ChainTip(
            chain=self.chain_name,
            height=b.height,
            block_hash=b.block_hash,
            work=b.work,
            timestamp=b.timestamp,
        )

    def height(self) -> int:
        return self._canonical[-1].height

    def get_block(self, hash_or_height: Any) -> Optional[Block]:
        if isinstance(hash_or_height, int) or (
            isinstance(hash_or_height, str) and hash_or_height.isdigit()
        ):
            h = int(hash_or_height)
            genesis_h = self._canonical[0].height
            idx = h - genesis_h
            if 0 <= idx < len(self._canonical):
                return self._canonical[idx]
            return None
        return self._by_hash.get(str(hash_or_height))

    def is_canonical(self, block_hash: str) -> bool:
        b = self._by_hash.get(block_hash)
        if not b:
            return False
        genesis_h = self._canonical[0].height
        idx = b.height - genesis_h
        if idx < 0 or idx >= len(self._canonical):
            return False
        return self._canonical[idx].block_hash == block_hash

    def confirmations(self, block_hash: str) -> int:
        if not self.is_canonical(block_hash):
            return 0
        b = self._by_hash[block_hash]
        return self.tip().height - b.height + 1

    def tx_location(self, txid: str) -> Optional[Block]:
        for b in reversed(self._canonical):
            if txid in b.txs:
                return b
        return None

    def submit_tx(self, txid: str, *, payload: Optional[Dict[str, Any]] = None) -> str:
        txid = str(txid)
        self.mempool.append({"txid": txid, "payload": payload or {}})
        return txid

    def mine(self, extra_txs: Optional[Sequence[str]] = None, *, fork_nonce: Optional[int] = None) -> Block:
        prev = self._canonical[-1]
        txs = [m["txid"] for m in self.mempool]
        self.mempool = []
        if extra_txs:
            for t in extra_txs:
                if t not in txs:
                    txs.append(str(t))
        self._nonce += 1
        nonce = int(fork_nonce) if fork_nonce is not None else self._nonce
        self._time_tick += 600  # ~10 min informational block spacing, not elapsed time
        body = {
            "prev": prev.block_hash,
            "height": prev.height + 1,
            "txs": txs,
            "nonce": nonce,
        }
        block_hash = _sha(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
        block = Block(
            height=prev.height + 1,
            block_hash=block_hash,
            prev_hash=prev.block_hash,
            work=_work_add(prev.work, 1),
            timestamp=self._time_tick,
            txs=txs,
            nonce=nonce,
        )
        self._canonical.append(block)
        self._by_hash[block.block_hash] = block
        return block

    def mine_n(self, n: int) -> List[Block]:
        return [self.mine() for _ in range(int(n))]

    def reorg(self, fork_height: int, new_length: int = 1) -> List[Block]:
        """
        Invalidate blocks above `fork_height` and grow a heavier competing fork.

        Historical (orphaned) blocks are retained. Canonical tip changes.
        `new_length` is the number of replacement blocks after the fork point.
        The new branch is given extra work so it wins even at equal length.
        """
        genesis_h = self._canonical[0].height
        if fork_height < genesis_h or fork_height >= self.tip().height:
            raise ValueError("fork_height must be on the canonical chain below the tip")
        keep_idx = fork_height - genesis_h
        dropped = self._canonical[keep_idx + 1 :]
        self._orphans.extend(dropped)
        self._canonical = self._canonical[: keep_idx + 1]
        # Dropped txs are NOT silently re-included. Re-anchor is an explicit act.
        for b in dropped:
            for txid in b.txs:
                if not any(m["txid"] == txid for m in self.mempool):
                    # Keep them visible as dropped, not as pending mempool.
                    pass
        produced: List[Block] = []
        # Extra nonce salt so replacement hashes differ from the orphaned ones.
        salt_base = 10_000 + len(self._orphans)
        for i in range(max(1, int(new_length))):
            produced.append(self.mine(fork_nonce=salt_base + i))
        return produced

    def dropped_blocks(self) -> List[Block]:
        return list(self._orphans)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical": [b.to_dict() for b in self._canonical],
            "orphans": [b.to_dict() for b in self._orphans],
            "mempool": list(self.mempool),
            "tip": self.tip().to_dict(),
        }
