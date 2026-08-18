"""
Pluggable Bitcoin broadcasters.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

from .payload import short_op_return_payload, full_record_json
from .records import AnchorRecord

logger = logging.getLogger("aurora.btc_anchor.broadcast")


class BroadcastResult:
    def __init__(
        self,
        ok: bool,
        txid: Optional[str] = None,
        error: Optional[str] = None,
        method: str = "unknown",
        network: str = "bitcoin",
    ):
        self.ok = ok
        self.txid = txid
        self.error = error
        self.method = method
        self.network = network


class Broadcaster(ABC):
    @abstractmethod
    def broadcast(self, record: AnchorRecord) -> BroadcastResult:
        """Attempt to write the commitment. Return txid on success."""


class NullBroadcaster(Broadcaster):
    def broadcast(self, record: AnchorRecord) -> BroadcastResult:
        return BroadcastResult(ok=False, error="null broadcaster", method="null")


class LogBroadcaster(Broadcaster):
    def __init__(self, network: str = "signet"):
        self.network = network

    def broadcast(self, record: AnchorRecord) -> BroadcastResult:
        try:
            if record.meta and record.meta.get("op_return_hex"):
                op_ret = bytes.fromhex(record.meta["op_return_hex"])
            else:
                op_ret = short_op_return_payload(record.commitment)
            full = full_record_json(record.commitment, record.asset_id)
            import hashlib
            synth = hashlib.sha256(op_ret + record.asset_id.encode()).hexdigest()
            logger.info(
                f"[LOG-BROADCAST] network={self.network} asset={record.asset_id[:16]}… "
                f"op_return={op_ret!r} full={full} synth_txid={synth[:16]}…"
            )
            return BroadcastResult(
                ok=True,
                txid=f"log:{synth}",
                method="log_op_return",
                network=self.network,
            )
        except Exception as e:
            return BroadcastResult(ok=False, error=str(e), method="log_op_return")


def default_broadcaster() -> Broadcaster:
    mode = (os.getenv("AURORA_BTC_BROADCASTER") or "").strip().lower()
    network = (os.getenv("AURORA_BTC_NETWORK") or "signet").strip().lower()
    enabled = os.getenv("AURORA_BTC_ANCHOR_BROADCAST", "").strip() in ("1", "true", "yes")
    cli_send = os.getenv("AURORA_BTC_CLI_SEND", "").strip() in ("1", "true", "yes")

    if mode == "cli":
        from .cli_broadcaster import BitcoinCLIBroadcaster
        return BitcoinCLIBroadcaster(network=network, send=cli_send)
    if mode == "log" or (not mode and enabled):
        return LogBroadcaster(network=network)
    if mode == "null" or not mode:
        return NullBroadcaster()
    logger.warning(f"Unknown AURORA_BTC_BROADCASTER={mode!r}, using null")
    return NullBroadcaster()
