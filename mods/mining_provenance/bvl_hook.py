"""
BVL credit when mining evidence advances — bound to event id (claim-deduped).
Not an open mint path from HTTP.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .models import EvidenceLevel, MiningEvent

logger = logging.getLogger("aurora.mining.bvl")

CREDIT = {
    int(EvidenceLevel.POOL_ACCEPTED): 0.01,
    int(EvidenceLevel.POOL_CREDITED): 0.05,
    int(EvidenceLevel.COINBASE_ASSOCIATED): 0.25,
}


def maybe_credit_bvl(comms: Any, event: MiningEvent) -> Optional[dict]:
    amount = CREDIT.get(int(event.evidence))
    if not amount:
        return None
    # Bind claim to event so the same share cannot be paid twice
    asset_id = f"mining:{event.event_id}:{event.evidence_label()}"
    try:
        from mods.bvl.ledger_service import BabelLedger

        led = BabelLedger(comms)
        return led.reward_seed(
            event.node_id or event.worker_id,
            asset_id=asset_id,
            amount=amount,
        )
    except Exception as e:
        logger.debug(f"bvl mining credit skip: {e}")
    return None
