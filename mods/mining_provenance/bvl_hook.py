"""
Optional BVL credit when mining evidence reaches pool_accepted+.

Incentives beyond the pool — without conflating BVL with sats.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .models import EvidenceLevel, MiningEvent

logger = logging.getLogger("aurora.mining.bvl")

# Small mesh credits by evidence tier (tunable)
CREDIT = {
    int(EvidenceLevel.POOL_ACCEPTED): 0.01,
    int(EvidenceLevel.POOL_CREDITED): 0.05,
    int(EvidenceLevel.COINBASE_ASSOCIATED): 0.25,
}


def maybe_credit_bvl(comms: Any, event: MiningEvent) -> Optional[dict]:
    amount = CREDIT.get(int(event.evidence))
    if not amount:
        return None
    try:
        from mods.bvl.ledger_service import BabelLedger

        led = BabelLedger(comms)
        # credit the worker node if ledger supports it
        if hasattr(led, "credit"):
            return led.credit(
                event.node_id or event.worker_id,
                amount,
                reason=f"mining:{event.evidence_label()}:{event.event_id}",
            )
        if hasattr(led, "mint"):
            return led.mint(
                amount,
                reason=f"mining:{event.evidence_label()}:{event.event_id}",
                to=event.node_id or event.worker_id,
            )
    except Exception as e:
        logger.debug(f"bvl mining credit skip: {e}")
    return None
