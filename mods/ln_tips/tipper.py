"""Pluggable Lightning tip backends."""

from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("aurora.ln_tips")


class TipResult:
    def __init__(self, ok: bool, payment_id: Optional[str] = None, error: Optional[str] = None, method: str = "unknown"):
        self.ok = ok
        self.payment_id = payment_id
        self.error = error
        self.method = method


class Tipper(ABC):
    @abstractmethod
    def tip(self, *, node_id: str, amount_sats: int, memo: str, ln_address: Optional[str] = None) -> TipResult:
        ...


class NullTipper(Tipper):
    def tip(self, *, node_id: str, amount_sats: int, memo: str, ln_address: Optional[str] = None) -> TipResult:
        return TipResult(ok=False, error="null tipper", method="null")


class LogTipper(Tipper):
    def tip(self, *, node_id: str, amount_sats: int, memo: str, ln_address: Optional[str] = None) -> TipResult:
        pid = f"log-tip:{node_id}:{int(time.time())}:{amount_sats}"
        logger.info(f"[LN-TIP-LOG] node={node_id} sats={amount_sats} memo={memo!r} ln={ln_address or '-'}")
        return TipResult(ok=True, payment_id=pid, method="log")


class LNDRestTipper(Tipper):
    """
    Minimal LND REST adapter.

    Env:
      AURORA_LND_REST=https://localhost:8080
      AURORA_LND_MACAROON_HEX=<admin/invoice macaroon hex>
      AURORA_LND_TLS_CERT optional path

    Without config, tips fail soft with a clear error.
    """

    def __init__(self):
        self.base = (os.getenv("AURORA_LND_REST") or "").rstrip("/")
        self.macaroon = os.getenv("AURORA_LND_MACAROON_HEX") or ""

    def tip(self, *, node_id: str, amount_sats: int, memo: str, ln_address: Optional[str] = None) -> TipResult:
        if not self.base or not self.macaroon:
            return TipResult(ok=False, error="LND REST not configured", method="lnd_rest")
        # Placeholder for invoice/pay flow — record intent for operators
        logger.info(
            f"[LN-TIP-LND] would pay node={node_id} sats={amount_sats} "
            f"via {self.base} memo={memo!r} ln_address={ln_address or '-'}"
        )
        return TipResult(
            ok=True,
            payment_id=f"lnd-intent:{node_id}:{amount_sats}:{int(time.time())}",
            method="lnd_rest_intent",
        )


def default_tipper() -> Tipper:
    mode = (os.getenv("AURORA_LN_TIPPER") or "log").strip().lower()
    if mode == "lnd":
        return LNDRestTipper()
    if mode == "null":
        return NullTipper()
    return LogTipper()
