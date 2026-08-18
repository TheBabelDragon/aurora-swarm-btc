"""
Multi-coin mining profiles.

Ethereum mainnet is Proof-of-Stake (no PoW). We support:
  - BTC  — SHA256d (CPU stratum + optional bfgminer)
  - ETC  — Ethereum Classic Etchash (pool/job layer; hasher needs GPU tool)
  - generic stratum profiles for future algorithms
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .defaults import DEFAULT_MINING_WALLET, DEFAULT_POOL_URL


@dataclass
class PoolEndpoint:
    host: str
    port: int
    ssl: bool = False
    password: str = "x"

    @property
    def url(self) -> str:
        scheme = "stratum+ssl" if self.ssl else "stratum+tcp"
        return f"{scheme}://{self.host}:{self.port}"


@dataclass
class CoinProfile:
    symbol: str
    algorithm: str
    family: str  # bitcoin | ethash_family | other
    default_pools: List[PoolEndpoint] = field(default_factory=list)
    default_wallet_env: str = "MINING_WALLET"
    notes: str = ""
    hash_backend: str = "none"  # sha256d_cpu | bfgminer | external_gpu | none


COINS: Dict[str, CoinProfile] = {
    "BTC": CoinProfile(
        symbol="BTC",
        algorithm="sha256d",
        family="bitcoin",
        default_pools=[
            PoolEndpoint("stratum.braiins.com", 3333),
            PoolEndpoint("btc.global.luxor.tech", 700),
            PoolEndpoint("solo.ckpool.org", 3333),
        ],
        default_wallet_env="MINING_WALLET",
        notes="Live CPU + optional bfgminer. Default wallet from Aurora defaults.",
        hash_backend="sha256d_cpu",
    ),
    "ETC": CoinProfile(
        symbol="ETC",
        algorithm="etchash",
        family="ethash_family",
        default_pools=[
            PoolEndpoint("etc.2miners.com", 1010),
            PoolEndpoint("etc.f2pool.com", 8118),
        ],
        default_wallet_env="ETC_MINING_WALLET",
        notes=(
            "Ethereum Classic still PoW (Etchash). "
            "Aurora tracks jobs/pools; full DAG hashing needs a GPU miner binary."
        ),
        hash_backend="external_gpu",
    ),
    "ETH": CoinProfile(
        symbol="ETH",
        algorithm="none",
        family="proof_of_stake",
        default_pools=[],
        notes=(
            "Ethereum mainnet merged to Proof-of-Stake (Sep 2022). "
            "No PoW mining. Use ETC for ethash-family PoW, or monitor validators separately."
        ),
        hash_backend="none",
    ),
}


def get_coin(symbol: str) -> Optional[CoinProfile]:
    return COINS.get((symbol or "BTC").upper())


def list_coins() -> List[dict]:
    out = []
    for c in COINS.values():
        out.append(
            {
                "symbol": c.symbol,
                "algorithm": c.algorithm,
                "family": c.family,
                "hash_backend": c.hash_backend,
                "notes": c.notes,
                "pools": [{"host": p.host, "port": p.port, "ssl": p.ssl, "url": p.url} for p in c.default_pools],
                "mineable": c.hash_backend not in ("none",) or c.family != "proof_of_stake",
            }
        )
    return out


def default_pool_url(symbol: str = "BTC") -> str:
    c = get_coin(symbol)
    if c and c.default_pools:
        return c.default_pools[0].url
    return DEFAULT_POOL_URL
