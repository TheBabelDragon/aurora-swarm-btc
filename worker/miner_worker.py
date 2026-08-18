"""
Aurora miner worker — mesh node driving MiningEngine + bfgminer.

GPU hashing: bfgminer OpenCL
Swarm brain: mods.mining_engine (shares → provenance, adaptive intensity, fleet)
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import prometheus_client as prom
from comms.layer import CommsLayer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aurora-worker-mesh")

comms = CommsLayer(node_id=os.getenv("WORKER_NAME", "aurora-gpu1"))

HASH_RATE = prom.Gauge("aurora_worker_hashrate_ghs", "Current hashrate GH/s")
SHARES_ACCEPTED = prom.Counter("aurora_shares_accepted_total", "Accepted shares")
WORKER_STATUS = prom.Gauge("aurora_worker_status", "Worker status")
HEALTH = prom.Gauge("aurora_worker_health", "Health status")

engine = None


def _build_engine():
    from mods.mining_engine.engine import MiningEngine

    eng = MiningEngine(
        comms,
        worker_id=os.getenv("WORKER_NAME", comms.node_id),
        pool_url=os.getenv("POOL_URL", "stratum+tcp://stratum.braiins.com:3333"),
        wallet=os.getenv("MINING_WALLET", ""),
        intensity=os.getenv("INTENSITY", "19"),
        gpus=int(os.getenv("GPUS_PER_POD", "1")),
        facility_domain=os.getenv("FACILITY_DOMAIN", "unknown"),
        binary=os.getenv("BFGMINER_BIN", "bfgminer"),
    )

    def on_hr(gh: float):
        HASH_RATE.set(gh)

    eng.pipeline.on_hashrate = lambda gh: (on_hr(gh), eng._on_hashrate(gh))
    return eng


def handle_mesh_command(msg):
    global engine
    if engine is None:
        return
    if not isinstance(msg, dict):
        return
    payload = msg.get("payload", msg)
    action = payload.get("action") or msg.get("action")

    if action == "adjust_intensity":
        new_i = str(payload.get("factor", engine.cfg.intensity))
        logger.info(f"[MESH] intensity → {new_i}")
        engine.set_intensity(new_i)
    elif action == "pause":
        logger.info("[MESH] pause")
        engine.stop()
        WORKER_STATUS.set(0)
    elif action == "resume":
        logger.info("[MESH] resume")
        engine.start()
        WORKER_STATUS.set(1)
    elif action == "restart_miner":
        logger.info("[MESH] restart")
        engine.restart()
    else:
        logger.info(f"[MESH] unknown action: {action}")


def shutdown_handler(signum, frame):
    logger.info("shutdown")
    if engine:
        engine.stop()
    try:
        comms.close()
    except Exception:
        pass
    sys.exit(0)


def main():
    global engine

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    prom.start_http_server(int(os.getenv("WORKER_METRICS_PORT", "9100")))
    logger.info("[MESH] MiningEngine worker joining…")

    caps = ["gpu_mining", "intensity_control", "pause_resume", "restart", "mining_engine"]
    meta = {
        "gpus": int(os.getenv("GPUS_PER_POD", "1")),
        "pool": os.getenv("POOL_URL", ""),
        "wallet": os.getenv("MINING_WALLET", ""),
    }
    try:
        from mods.btc_identity.identity import NodeIdentity

        ident = NodeIdentity(comms)
        ident.register_with_identity(capabilities=caps, metadata=meta)
    except Exception as e:
        logger.debug(f"identity optional: {e}")
        comms.register_node(node_type="worker", capabilities=caps, metadata=meta)

    comms.heartbeat()
    try:
        # mesh command channels used by dashboard broadcast
        from comms.layer import SwarmMessage

        def _wrap(msg: SwarmMessage):
            handle_mesh_command(msg.model_dump() if hasattr(msg, "model_dump") else msg.dict())

        comms.subscribe("command.workers", _wrap)
        comms.subscribe(f"command.node.{comms.node_id}", _wrap)
    except Exception as e:
        logger.warning(f"subscribe: {e}")

    engine = _build_engine()
    if not engine.cfg.wallet:
        logger.warning("MINING_WALLET empty — miner may fail auth at pool")
    ok = engine.start()
    WORKER_STATUS.set(1 if ok else 0)
    HEALTH.set(1 if ok else 0)

    while True:
        try:
            st = engine.status()
            if st.get("shares_accepted"):
                # prometheus counter is monotonic — set via inc in pipeline path optionally
                pass
            HEALTH.set(1 if st.get("running") else 0)
            WORKER_STATUS.set(0 if st.get("paused") else (1 if st.get("running") else 0))
            time.sleep(5)
        except Exception as e:
            logger.error(f"worker loop: {e}")
            HEALTH.set(0)
            time.sleep(10)


if __name__ == "__main__":
    main()
