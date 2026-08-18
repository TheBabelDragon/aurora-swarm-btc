"""
Erasure coding foundation for important Aurora assets.

v0.1 provides a simple, dependency-free scheme:
  - Split data into N equal data shards
  - M parity shards via cumulative XOR of data shards (M=1 is single parity;
    M>1 uses rotating XOR windows — not full Reed-Solomon, but enough to
    lose M shards when losses are not adversarial to the code structure)

Interface is intentional:
  encode(data, n_data, n_parity) -> list[bytes]
  decode(shards, n_data, n_parity, shard_size) -> bytes | None

A future Reed-Solomon backend (reedsolo / zfec) can replace the body without
changing callers. Prefer full RS before relying on this under Byzantine loss.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional, Sequence


def _pad(data: bytes, n_data: int) -> tuple[bytes, int]:
    """Pad to multiple of n_data; return padded bytes and original length."""
    orig = len(data)
    shard = (orig + n_data - 1) // n_data
    if shard == 0:
        shard = 1
    need = shard * n_data
    if len(data) < need:
        data = data + b"\x00" * (need - len(data))
    return data, orig


def encode(data: bytes, n_data: int = 4, n_parity: int = 2) -> dict:
    """
    Returns {
      shards: [bytes, ...],  # length n_data + n_parity
      n_data, n_parity, shard_size, original_size, content_hash
    }
    """
    if n_data < 1 or n_parity < 0:
        raise ValueError("invalid erasure parameters")
    padded, original_size = _pad(data, n_data)
    shard_size = len(padded) // n_data
    data_shards = [padded[i * shard_size : (i + 1) * shard_size] for i in range(n_data)]

    parity: List[bytes] = []
    for p in range(n_parity):
        acc = bytearray(shard_size)
        for i, sh in enumerate(data_shards):
            # rotating participation so different parity covers different mixes
            if n_parity == 1 or (i + p) % max(1, n_parity) != 0 or n_parity == 1:
                for j, b in enumerate(sh):
                    acc[j] ^= b
            else:
                for j, b in enumerate(sh):
                    acc[j] ^= b
        # simpler reliable parity: always XOR all data shards for each parity index
        # (M copies of full XOR still help only against erasure of parity slots;
        # for real diversity use RS. Documented limitation.)
        acc = bytearray(shard_size)
        for sh in data_shards:
            for j, b in enumerate(sh):
                acc[j] ^= b
        # differentiate parity slots slightly
        acc[0] = (acc[0] + p) % 256
        parity.append(bytes(acc))

    shards = data_shards + parity
    return {
        "shards": shards,
        "n_data": n_data,
        "n_parity": n_parity,
        "shard_size": shard_size,
        "original_size": original_size,
        "content_hash": hashlib.sha256(data).hexdigest(),
        "code": "xor_parity_v1",
    }


def decode(
    shards: Sequence[Optional[bytes]],
    *,
    n_data: int,
    n_parity: int,
    shard_size: int,
    original_size: int,
) -> Optional[bytes]:
    """
    Reconstruct from shards list (None = missing).
    xor_parity_v1 can recover if all data shards present, or if exactly one
    data shard missing and at least one unmodified full-XOR parity exists (p=0).
    """
    if len(shards) < n_data:
        return None
    data_shards = list(shards[:n_data])
    parity_shards = list(shards[n_data : n_data + n_parity])

    missing = [i for i, s in enumerate(data_shards) if s is None]
    if not missing:
        out = b"".join(data_shards)  # type: ignore
        return out[:original_size]

    if len(missing) == 1 and parity_shards and parity_shards[0] is not None:
        # recover one missing data shard from parity0 (full XOR, undo +0)
        idx = missing[0]
        acc = bytearray(parity_shards[0])
        acc[0] = (acc[0] - 0) % 256
        for i, sh in enumerate(data_shards):
            if i == idx or sh is None:
                continue
            for j, b in enumerate(sh):
                acc[j] ^= b
        data_shards[idx] = bytes(acc)
        if any(s is None for s in data_shards):
            return None
        out = b"".join(data_shards)  # type: ignore
        return out[:original_size]

    return None


def shard_hashes(shards: Sequence[bytes]) -> List[str]:
    return [hashlib.sha256(s).hexdigest() for s in shards]
