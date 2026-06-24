import os
import time
import logging
import subprocess
import re
import signal
import sys
import prometheus_client as prom
from control.bus import Bus

"""
Aurora Swarm BTC - Production Miner Worker

This worker runs bfgminer and reports metrics + status to the control bus.
It is designed to be resilient and observable.
"""

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("aurora-worker")
bus = Bus()

# Prometheus Metrics
HASH_RATE = prom.Gauge('aurora_worker_hashrate_ghs', 'Current hashrate GH/s')
SHARES_ACCEPTED = prom.Counter('aurora_shares_accepted_total', 'Accepted shares')
WORKER_STATUS = prom.Gauge('aurora_worker_status', '1 = running, 0 = stopped')

# Config
GPUS_PER_POD = int(os.getenv("GPUS_PER_POD", "1"))
WALLET = os.getenv("MINING_WALLET", "bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g")
POOL_URL = os.getenv("POOL_URL", "stratum+tcp://stratum.braiins.com:3333")
WORKER_NAME = os.getenv("WORKER_NAME", "aurora-gpu1")
INTENSITY = os.getenv("INTENSITY", "19")

miner_process = None


def parse_hashrate(line: str) -> float:
    match = re.search(r'(\d+\.?\d*)\s*(KH|MH|GH|TH)/s', line, re.IGNORECASE)
    if match:
        rate = float(match.group(1))
        unit = match.group(2).upper()
        multipliers = {'KH': 1e3, 'MH': 1e6, 'GH': 1e9, 'TH': 1e12}
        return rate * multipliers.get(unit, 1.0)
    return 0.0


def start_miner():
    global miner_process
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
    miner_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    WORKER_STATUS.set(1)
    return miner_process


def stop_miner():
    global miner_process
    if miner_process and miner_process.poll() is None:
        logger.info("Stopping miner gracefully...")
        miner_process.terminate()
        try:
            miner_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Miner did not stop in time, killing...")
            miner_process.kill()
        WORKER_STATUS.set(0)
        miner_process = None


def shutdown_handler(signum, frame):
    logger.info("Shutdown signal received")
    stop_miner()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    prom.start_http_server(8000)
    logger.info(f"Aurora Miner Worker started ({GPUS_PER_POD} GPU(s))")

    while True:
        try:
            process = start_miner()

            for line in process.stdout:
                hashrate = parse_hashrate(line)
                if hashrate > 0:
                    gh = hashrate / 1e9
                    HASH_RATE.set(round(gh, 2))
                    bus.set("worker:hashrate", round(gh, 2))
                    bus.set("worker:status", "mining")

                if "accepted" in line.lower():
                    SHARES_ACCEPTED.inc()
                    bus.increment("cluster:shares_accepted", 1)
                    logger.info("Share accepted")

            logger.warning("Miner process ended unexpectedly. Restarting in 10s...")
            WORKER_STATUS.set(0)
            time.sleep(10)

        except Exception as e:
            logger.error(f"Critical worker error: {e}")
            WORKER_STATUS.set(0)
            time.sleep(15)


if __name__ == "__main__":
    main()