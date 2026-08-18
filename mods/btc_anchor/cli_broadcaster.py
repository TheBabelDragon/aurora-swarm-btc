"""
Bitcoin Core CLI broadcaster.

When AURORA_BTC_BROADCASTER=cli (and optional AURORA_BTC_CLI_SEND=1):
  1. Build OP_RETURN script hex from commitment / batch meta
  2. createrawtransaction with data output
  3. fundrawtransaction + signrawtransactionwithwallet + sendrawtransaction

Without a funded wallet / bitcoind, runs in dry-run mode and returns a
synthetic cli-dry: txid while still proving the full script path.

Network: controlled by bitcoin.conf / -datadir; we label via AURORA_BTC_NETWORK.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import List, Optional

from .broadcaster import Broadcaster, BroadcastResult
from .payload import short_op_return_payload
from .records import AnchorRecord

logger = logging.getLogger("aurora.btc_anchor.cli")


def _bitcoin_cli(args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    bin_name = os.getenv("AURORA_BITCOIN_CLI", "bitcoin-cli")
    extra = os.getenv("AURORA_BITCOIN_CLI_ARGS", "").split()
    cmd = [bin_name] + [a for a in extra if a] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _op_return_script_hex(data: bytes) -> str:
    """
    Minimal OP_RETURN script: OP_RETURN <push data>
    Only for data length <= 75 (single-byte push).
    """
    if len(data) > 75:
        raise ValueError("OP_RETURN data too long for simple push")
    # 0x6a = OP_RETURN, then length byte, then data
    return "6a" + f"{len(data):02x}" + data.hex()


class BitcoinCLIBroadcaster(Broadcaster):
    def __init__(self, network: str = "signet", send: bool = False):
        self.network = network
        self.send = send
        self.cli_available = shutil.which(os.getenv("AURORA_BITCOIN_CLI", "bitcoin-cli")) is not None

    def broadcast(self, record: AnchorRecord) -> BroadcastResult:
        try:
            # Prefer batch meta op_return if present
            if record.meta and record.meta.get("op_return_hex"):
                data = bytes.fromhex(record.meta["op_return_hex"])
            else:
                data = short_op_return_payload(record.commitment)
            script_hex = _op_return_script_hex(data)
        except Exception as e:
            return BroadcastResult(ok=False, error=f"payload: {e}", method="bitcoin_cli")

        if not self.cli_available or not self.send:
            import hashlib
            synth = hashlib.sha256(script_hex.encode() + record.asset_id.encode()).hexdigest()
            logger.info(
                f"[CLI-DRY] network={self.network} asset={record.asset_id[:16]}… "
                f"script={script_hex} (set AURORA_BTC_CLI_SEND=1 + bitcoind to broadcast)"
            )
            return BroadcastResult(
                ok=True,
                txid=f"cli-dry:{synth}",
                method="bitcoin_cli_dry",
                network=self.network,
            )

        try:
            # data output via createrawtransaction null data
            # bitcoin-cli createrawtransaction '[]' '{"data":"<hex>"}'
            outs = json.dumps({"data": data.hex()})
            r1 = _bitcoin_cli(["createrawtransaction", "[]", outs])
            if r1.returncode != 0:
                return BroadcastResult(ok=False, error=r1.stderr.strip() or r1.stdout, method="bitcoin_cli")
            raw = r1.stdout.strip()

            r2 = _bitcoin_cli(["fundrawtransaction", raw])
            if r2.returncode != 0:
                return BroadcastResult(ok=False, error=r2.stderr.strip() or r2.stdout, method="bitcoin_cli")
            funded = json.loads(r2.stdout)
            hex_funded = funded.get("hex") or raw

            r3 = _bitcoin_cli(["signrawtransactionwithwallet", hex_funded])
            if r3.returncode != 0:
                return BroadcastResult(ok=False, error=r3.stderr.strip() or r3.stdout, method="bitcoin_cli")
            signed = json.loads(r3.stdout)
            if not signed.get("complete"):
                return BroadcastResult(ok=False, error="sign incomplete", method="bitcoin_cli")

            r4 = _bitcoin_cli(["sendrawtransaction", signed["hex"]])
            if r4.returncode != 0:
                return BroadcastResult(ok=False, error=r4.stderr.strip() or r4.stdout, method="bitcoin_cli")
            txid = r4.stdout.strip()
            logger.info(f"[CLI] broadcast ok txid={txid} asset={record.asset_id[:12]}…")
            return BroadcastResult(ok=True, txid=txid, method="bitcoin_cli", network=self.network)
        except subprocess.TimeoutExpired:
            return BroadcastResult(ok=False, error="bitcoin-cli timeout", method="bitcoin_cli")
        except Exception as e:
            logger.exception("CLI broadcast failed")
            return BroadcastResult(ok=False, error=str(e), method="bitcoin_cli")
