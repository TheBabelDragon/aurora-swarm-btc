import os
import time
import logging
import subprocess
import re
import signal
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_APP = Path(__file__).resolve().parent
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import prometheus_client as prom
from comms.layer import CommsLayer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("aurora-worker-mesh")

comms = CommsLayer(node_id=os.getenv("WORKER_NAME", "aurora-gpu1"))

HASH_RATE = prom.Gauge("aurora_worker_hashrate_ghs", "Current hashrate GH/s")
SHARES_ACCEPTED = prom.Counter("aurora_shares_accepted_total", "Accepted shares")
WORKER_STATUS = prom.Gauge("aurora_worker_status", "Worker status")
HEALTH = prom.Gauge("aurora_worker_health", "Health status")

GPUS_PER_POD = int(os.getenv("GPUS_PER_POD", "1"))
WALLET = os.getenv("MINING_WALLET", "bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g")
POOL_URL = os.getenv("POOL_URL", "stratum+tcp://stratum.braiins.com:3333")
WORKER_NAME = os.getenv("WORKER_NAME", "aurora-gpu1")
INTENSITY = os.getenv("INTENSITY", "19")

miner_process = None
healthy = True
paused = False
current_intensity = INTENSITY


def parse_hashrate(line: str) -> float:
    match = re.search(r"(\d+\.?\d*)\s*(KH|MH|GH|TH)/s", line, re.IGNORECASE)
    if match:
        rate = float(match.group(1))
        unit = match.group(2).upper()
        multipliers = {"KH": 1e3, "MH": 1e6, "GH": 1e9, "TH": 1e12}
        return rate * multipliers.get(unit, 1.0)
    return 0.0


def start_miner(intensity: str = None):
    global miner_process, healthy, current_intensity, paused
    use_intensity = intensity or current_intensity
    current_intensity = use_intensity

    cmd = [
        "bfgminer",
        "-o", POOL_URL,
        "-u", f"{WALLET}.{WORKER_NAME}",
        "-p", "x",
        "--no-getwork",
        "-S", "opencl:auto",
        "--intensity", str(use_intensity),
        "--api-listen",
        "--quiet",
    ]
    if GPUS_PER_POD > 1:
        cmd.extend(["--set", f"gpu_count={GPUS_PER_POD}"])

    logger.info(f"Starting bfgminer with intensity={use_intensity} ({GPUS_PER_POD} GPU(s))...")
    try:
        miner_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        WORKER_STATUS.set(1)
        HEALTH.set(1)
        healthy = True
        paused = False
        return miner_process
    except Exception as e:
        logger.error(f"Failed to start miner: {e}")
        HEALTH.set(0)
        healthy = False
        return None


def stop_miner():
    global miner_process, healthy, paused
    if miner_process and miner_process.poll() is None:
        logger.info("Stopping miner...")
        miner_process.terminate()
        try:
            miner_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            miner_process.kill()
        WORKER_STATUS.set(0)
        HEALTH.set(0)
        healthy = False
        paused = True
        miner_process = None


def handle_mesh_command(msg):
    global current_intensity, paused

    if not isinstance(msg, dict):
        return

    payload = msg.get("payload", msg)
    action = payload.get("action") or msg.get("action")

    if action == "adjust_intensity":
        new_intensity = str(payload.get("factor", current_intensity))
        logger.info(f"[MESH CMD] Adjusting intensity to {new_intensity}")
        if miner_process:
            stop_miner()
            time.sleep(2)
            start_miner(new_intensity)
        else:
            current_intensity = new_intensity

    elif action == "pause":
        logger.info("[MESH CMD] Pausing miner")
        stop_miner()
        paused = True

    elif action == "resume":
        logger.info("[MESH CMD] Resuming miner")
        if paused or not miner_process:
            start_miner(current_intensity)

    elif action == "restart_miner":
        logger.info("[MESH CMD] Restarting miner")
        stop_miner()
        time.sleep(3)
        start_miner(current_intensity)

    else:
        logger.info(f"[MESH CMD] Unknown command received: {action}")


def shutdown_handler(signum, frame):
    logger.info("Shutdown signal received")
    stop_miner()
    try:
        comms.close()
    except Exception:
        pass
    sys.exit(0)


def main():
    global healthy

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    prom.start_http_server(8000)
    logger.info(f"[MESH] Aurora Miner Worker started ({GPUS_PER_POD} GPU(s)) - joining comms mesh...")

    caps = ["gpu_mining", "intensity_control", "pause_resume", "restart"]
    meta = {"gpus": GPUS_PER_POD, "pool": POOL_URL, "wallet": WALLET}
    try:
        from mods.btc_identity.identity import NodeIdentity
        ident = NodeIdentity(comms)
        view = ident.identity_view()
        meta["btc_identity"] = {
            "fingerprint": view.get("fingerprint"),
            "address_style": view.get("address_style"),
            "backend": view.get("backend"),
        }
        caps = caps + ["btc_identity"]
        logger.info(f"[MESH] btc_identity fingerprint={view.get('fingerprint')}")
        ident.register_with_identity(
            capabilities=caps,
            metadata={"gpus": GPUS_PER_POD, "pool": POOL_URL, "wallet": WALLET},
        )
    except Exception as e:
        logger.debug(f"btc_identity optional: {e}")
        comms.register_node(node_type="worker", capabilities=caps, metadata=meta)

    comms.heartbeat()
    comms.subscribe(f"node:{comms.node_id}", handle_mesh_command)

    last_health_report = time.time()
    last_mesh_heartbeat = time.time()

    start_miner()

    while True:
        try:
            if miner_process is None and not paused:
                start_miner(current_intensity)
                time.sleep(5)
                continue

            if miner_process:
                for line in miner_process.stdout:
                    hashrate = parse_hashrate(line)
                    if hashrate > 0:
                        gh = hashrate / 1e9
                        HASH_RATE.set(round(gh, 2))
                        comms.publish_telemetry({"hashrate_ghs": round(gh, 2), "status": "mining"})
                        comms.set_state("worker:hashrate", round(gh, 2))

                    if "accepted" in line.lower():
                        SHARES_ACCEPTED.inc()
                        current = comms.get_state("cluster:shares_accepted", 0) or 0
                        try:
                            current = int(current)
                        except Exception:
                            current = 0
                        comms.set_state("cluster:shares_accepted", current + 1)

                    now = time.time()
                    if now - last_health_report > 30:
                        comms.heartbeat(
                            metadata={
                                "status": "mining" if healthy else "degraded",
                                "intensity": current_intensity,
                            }
                        )
                        comms.publish_event(
                            "worker_heartbeat",
                            {"healthy": healthy, "intensity": current_intensity},
                        )
                        last_health_report = now

                    if now - last_mesh_heartbeat > 15:
                        comms.heartbeat()
                        last_mesh_heartbeat = now

            time.sleep(1)

        except Exception as e:
            logger.error(f"Worker error: {e}")
            HEALTH.set(0)
            healthy = False
            time.sleep(10)


if __name__ == "__main__":
    main()
