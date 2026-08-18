"""Earn / spend policy for BVL (env-overridable)."""

from __future__ import annotations

import os


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


class BVLPolicy:
    """
    Units are abstract BVL credits (not sats).

    Suggested mapping later: N BVL → tip via ln_tips (burn BVL, pay sats).
    """

    def __init__(self):
        self.seed_hold = _f("AURORA_BVL_SEED_HOLD", 1.0)          # per complete asset held when scored
        self.attest = _f("AURORA_BVL_ATTEST", 2.0)                # when node anchors an asset
        self.uptime_tick = _f("AURORA_BVL_UPTIME", 0.1)            # periodic heartbeat reward
        self.transfer_fee = _f("AURORA_BVL_TRANSFER_FEE", 0.0)     # burned on transfer
        self.settle_sats_per_bvl = _f("AURORA_BVL_SATS_PER", 1.0)  # for ln settle bridge
