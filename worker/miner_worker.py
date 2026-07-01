import os
import time
import logging
import subprocess
import re
import signal
import sys
import prometheus_client as prom
from comms.layer import CommsLayer

"""
Aurora Swarm BTC - Production Miner Worker (Mesh-enabled)

Every worker now participates in and perpetuates the Comms Layer mesh.
- Self-registers on startup
- Sends heartbeats
- Publishes telemetry and events via the mesh
- Can receive targeted commands
"""

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("aurora-worker-mesh")

comms = CommsLayer(node_id=os.getenv("WORKER_NAME", "aurora-gpu1"))

# Prometheus
HASH_RATE = prom.Gauge('aurora_worker_hashrate_ghs', 'Current hashrate GH/s')
SHARES_ACCEPTED = prom.Counter('aurora_shares_accepted_total', 'Accepted shares')
WORKER_STATUS = prom.Gauge('aurora_worker_status', 'Worker status')
HEALTH = prom.Gauge('aurora_worker_health', 'Health status')

# Config
GPUS_PER_POD = int(os.getenv("GPUS_PER_POD", "1"))
WALLET = os.getenv("MINING_WALLET", "bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g")
POOL_URL = os.getenv("POOL_URL", "stratum+tcp://stratum.braiins.com:3333")
WORKER_NAME = os.getenv("WORKER_NAME", "aurora-gpu1")
INTENSITY = os.getenv("INTENSITY", "19")

miner_process = None
healthy = True


def parse_hashrate(line: str) -> float:
    match = re.search(r'(\d+\.?\d*)\s*(KH|MH|GH|TH)/s', line, re.IGNORECASE)
    if match:
        rate = float(match.group(1))
        unit = match.group(2).upper()
        multipliers = {'KH': 1e3, 'MH': 1e6, 'GH': 1e9, 'TH': 1e12}
        return rate * multipliers.get(unit, 1.0)
    return 0.0


def start_miner():
    global miner_process, healthy
    cmd = [
        "bfgminer",
        "-o", POOL_URL,
        "-u", f"{WALLET}.{WORKER_NAME}",
        "-p", "x",
        "--no-getwork",
        "-S", "opencl:auto",
        "--intensity", INTENSITY,
        "--api-listen",
        "--quiet"
    ]
    if GPUS_PER_POD > 1:
        cmd.extend(["--set", f"gpu_count={GPUS_PER_POD}"])

    logger.info(f"Starting bfgminer ({GPUS_PER_POD} GPU(s))...")
    try:
        miner_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        WORKER_STATUS.set(1)
        HEALTH.set(1)
        healthy = True
        return miner_process
    except Exception as e:
        logger.error(f"Failed to start miner: {e}")
        HEALTH.set(0)
        healthy = False
        return None


def stop_miner():
    global miner_process, healthy
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
        miner_process = None


def shutdown_handler(signum, frame):
    logger.info("Shutdown signal received")
    stop_miner()
    comms.close()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    prom.start_http_server(8000)
    logger.info(f"[MESH] Aurora Miner Worker started ({GPUS_PER_POD} GPU(s)) - joining comms mesh...")

    # === MESH PARTICIPATION: Every worker perpetuates the Comms Layer ===
    comms.register_node(
        node_type="worker",
        metadata={
            "gpus": GPUS_PER_POD,
            "pool": POOL_URL.split("://")[1] if "://" in POOL_URL else POOL_URL,
            "version": "1.0-mesh"
        }
    )
    comms.heartbeat()  # initial heartbeat

    last_health_report = time.time()
    last_mesh_heartbeat = time.time()

    while True:
        try:
            process = start_miner()
            if process is None:
                time.sleep(15)
                continue

            for line in process.stdout:
                hashrate = parse_hashrate(line)
                if hashrate > 0:
                    gh = hashrate / 1e9
                    HASH_RATE.set(round(gh, 2))
                    # Publish via mesh (CommsLayer)
                    comms.publish_telemetry({
                        "hashrate_ghs": round(gh, 2),
                        "status": "mining"
                    })
                    comms.set_state("worker:hashrate", round(gh, 2))

                if "accepted" in line.lower():
                    SHARES_ACCEPTED.inc()
                    comms.set_state("cluster:shares_accepted", comms.get_state("cluster:shares_accepted", 0) + 1)
                    logger.info("Share accepted")

                # Periodic mesh heartbeat + health report (every 30s)
                now = time.time()
                if now - last_health_report > 30:
                    comms.heartbeat(metadata={"status": "mining" if healthy else "degraded"})
                    comms.publish_event("worker_heartbeat", {
                        "healthy": healthy,
                        "hashrate": round(gh, 2) if 'gh' in locals() else 0
                    })
                    last_health_report = now

                if now - last_mesh_heartbeat > 15:
                    comms.heartbeat()  # keep node alive in mesh registry
                    last_mesh_heartbeat = now

            logger.warning("Miner exited. Restarting in 10s...")
            WORKER_STATUS.set(0)
            HEALTH.set(0)
            healthy = False
            time.sleep(10)

        except Exception as e:
            logger.error(f"Worker error: {e}")
            HEALTH.set(0)
            healthy = False
            time.sleep(15)


if __name__ == "__main__":
    main()
