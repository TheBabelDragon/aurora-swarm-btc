"""
Systematic Reed-Solomon erasure coding over GF(256).

Split a blob into ``n_data`` equal data shards and ``n_parity`` parity shards.
Any ``n_data`` of the ``n_data + n_parity`` shards reconstruct the original.

Public API
----------
encode(data, n_data=4, n_parity=2) -> dict
decode(shards, n_data=..., n_parity=..., shard_size=..., original_size=...) -> bytes|None
selftest() -> bool

Constraints: 1 ≤ n_data, 0 ≤ n_parity, n_data + n_parity ≤ 255.

GF(256) uses primitive polynomial 0x11d (same family as common RS libraries).
Pure Python — no external codec dependency.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional, Sequence

# ---------------------------------------------------------------------------
# GF(256) with primitive polynomial 0x11d
# ---------------------------------------------------------------------------

_PRIM = 0x11D
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256


def _init_gf():
    x = 1
    for i in range(255):
        _GF_EXP[i] = x
        _GF_LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= _PRIM
    for i in range(255, 512):
        _GF_EXP[i] = _GF_EXP[i - 255]


_init_gf()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _gf_div(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("GF div by zero")
    if a == 0:
        return 0
    return _GF_EXP[(_GF_LOG[a] - _GF_LOG[b]) % 255]


def _mat_mul_vec(mat: List[List[int]], vec: List[int]) -> List[int]:
    rows = len(mat)
    cols = len(vec)
    out = [0] * rows
    for r in range(rows):
        s = 0
        row = mat[r]
        for c in range(cols):
            s ^= _gf_mul(row[c], vec[c])
        out[r] = s
    return out


def _mat_invert(mat: List[List[int]]) -> List[List[int]]:
    n = len(mat)
    a = [row[:] + [1 if i == j else 0 for j in range(n)] for i, row in enumerate(mat)]
    for col in range(n):
        piv = None
        for r in range(col, n):
            if a[r][col] != 0:
                piv = r
                break
        if piv is None:
            raise ValueError("singular matrix — cannot invert")
        if piv != col:
            a[col], a[piv] = a[piv], a[col]
        inv = _gf_div(1, a[col][col])
        a[col] = [_gf_mul(x, inv) for x in a[col]]
        for r in range(n):
            if r == col:
                continue
            factor = a[r][col]
            if factor == 0:
                continue
            a[r] = [a[r][c] ^ _gf_mul(factor, a[col][c]) for c in range(2 * n)]
    return [row[n:] for row in a]


def _parity_matrix(n_data: int, n_parity: int) -> List[List[int]]:
    """
    Cauchy matrix for systematic parity.
    P[p][d] = 1 / (x_p ⊕ y_d) with distinct nonzero x, y.
    """
    if n_data + n_parity > 255:
        raise ValueError("n_data + n_parity must be ≤ 255")
    P: List[List[int]] = []
    for p in range(n_parity):
        x = n_data + 1 + p
        row = []
        for d in range(n_data):
            y = d + 1
            row.append(_gf_div(1, x ^ y))
        P.append(row)
    return P


def encode(data: bytes, n_data: int = 4, n_parity: int = 2) -> dict:
    if n_data < 1 or n_parity < 0:
        raise ValueError("invalid n_data / n_parity")
    if n_data + n_parity > 255:
        raise ValueError("n_data + n_parity must be ≤ 255")

    original_size = len(data)
    content_hash = hashlib.sha256(data).hexdigest()

    shard_size = (original_size + n_data - 1) // n_data if original_size else 1
    need = shard_size * n_data
    if len(data) < need:
        data = data + b"\x00" * (need - len(data))

    data_shards = [data[i * shard_size : (i + 1) * shard_size] for i in range(n_data)]

    if n_parity == 0:
        return {
            "shards": data_shards,
            "n_data": n_data,
            "n_parity": 0,
            "shard_size": shard_size,
            "original_size": original_size,
            "content_hash": content_hash,
            "code": "reed_solomon_v1",
        }

    P = _parity_matrix(n_data, n_parity)
    parity_shards = [bytearray(shard_size) for _ in range(n_parity)]

    for off in range(shard_size):
        vec = [data_shards[d][off] for d in range(n_data)]
        par = _mat_mul_vec(P, vec)
        for p in range(n_parity):
            parity_shards[p][off] = par[p]

    shards: List[bytes] = data_shards + [bytes(p) for p in parity_shards]
    return {
        "shards": shards,
        "n_data": n_data,
        "n_parity": n_parity,
        "shard_size": shard_size,
        "original_size": original_size,
        "content_hash": content_hash,
        "code": "reed_solomon_v1",
    }


def decode(
    shards: Sequence[Optional[bytes]],
    *,
    n_data: int,
    n_parity: int,
    shard_size: int,
    original_size: int,
) -> Optional[bytes]:
    if n_data < 1:
        return None
    total = n_data + n_parity

    present = []
    for i, s in enumerate(list(shards)[:total]):
        if s is not None:
            if len(s) != shard_size:
                return None
            present.append((i, s))

    if len(present) < n_data:
        return None

    data_present = [(i, s) for i, s in present if i < n_data]
    if len(data_present) >= n_data:
        ordered = [None] * n_data
        for i, s in data_present:
            ordered[i] = s
        if all(x is not None for x in ordered):
            return b"".join(ordered)[:original_size]  # type: ignore

    chosen = present[:n_data]
    indices = [i for i, _ in chosen]
    P = _parity_matrix(n_data, n_parity) if n_parity else []

    G_rows: List[List[int]] = []
    for i in indices:
        if i < n_data:
            row = [0] * n_data
            row[i] = 1
        else:
            row = P[i - n_data][:]
        G_rows.append(row)

    try:
        inv = _mat_invert(G_rows)
    except ValueError:
        return None

    recovered = [bytearray(shard_size) for _ in range(n_data)]
    chosen_bytes = [s for _, s in chosen]

    for off in range(shard_size):
        vec = [chosen_bytes[j][off] for j in range(n_data)]
        data_syms = _mat_mul_vec(inv, vec)
        for d in range(n_data):
            recovered[d][off] = data_syms[d]

    return b"".join(bytes(r) for r in recovered)[:original_size]


def shard_hashes(shards: Sequence[bytes]) -> List[str]:
    return [hashlib.sha256(s).hexdigest() for s in shards]


def selftest() -> bool:
    payload = b"Aurora RS erasure test payload " * 17 + b"\x00\x01\xff"
    enc = encode(payload, n_data=4, n_parity=2)
    shards: List[Optional[bytes]] = list(enc["shards"])
    shards[1] = None
    shards[4] = None
    out = decode(
        shards,
        n_data=enc["n_data"],
        n_parity=enc["n_parity"],
        shard_size=enc["shard_size"],
        original_size=enc["original_size"],
    )
    if out != payload:
        return False
    if hashlib.sha256(out).hexdigest() != enc["content_hash"]:
        return False
    # drop first two data shards — recover from remaining data + parity
    shards = list(enc["shards"])
    shards[0] = None
    shards[1] = None
    out2 = decode(
        shards,
        n_data=enc["n_data"],
        n_parity=enc["n_parity"],
        shard_size=enc["shard_size"],
        original_size=enc["original_size"],
    )
    return out2 == payload
