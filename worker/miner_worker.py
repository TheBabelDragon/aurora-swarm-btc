import os
import time
import logging
import subprocess
import re
import psutil
import prometheus_client as prom
from control.bus import Bus
from profitability import get_current_profitability, switch_miner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bus = Bus()

# Prometheus metrics
HASH_RATE = prom.Gauge('aurora_worker_hashrate', 'Current hashrate GH/s', ['gpu'])
SHARES_ACCEPTED = prom.Counter('aurora_shares_accepted_total', 'Accepted shares')

GPUS_PER_POD = int(os.getenv("GPUS_PER_POD", "1"))
WALLET = os.getenv("MINING_WALLET", "bc1qdpqzuem4dkamt8ckcwaul7a2rhqju30xwn3f5g")
POOL_URL = os.getenv("POOL_URL", "stratum+tcp://stratum.braiins.com:3333")
WORKER_NAME = os.getenv("WORKER_NAME", "aurora-gpu1")

def parse_bfg_output(line):
    # Extract hashrate, shares, etc.
    hr_match = re.search(r'(\d+\.?\d*)\s*(KH|MH|GH|TH)/s', line, re.IGNORECASE)
    if hr_match:
        rate = float(hr_match.group(1))
        unit = hr_match.group(2).upper()
        multipliers = {'KH':1e3,'MH':1e6,'GH':1e9,'TH':1e12}
        return rate * multipliers.get(unit, 1)
    return 0.0

def main():
    logger.info(f"🚀 Aurora Multi-GPU Worker starting - {GPUS_PER_POD} GPU(s)")
    logger.info(f"💰 Wallet: {WALLET}")

    # Start Prometheus metrics server
    prom.start_http_server(8000)

    # Periodic profitability check
    def profitability_loop():
        while True:
            coin, data = get_current_profitability()
            switch_miner(coin, data.get('algo', 'sha256d'))
            time.sleep(1800)  # Check every 30 min

    profitability_thread = threading.Thread(target=profitability_loop, daemon=True)
    profitability_thread.start()

    cmd = [
        "bfgminer",
        "-o", POOL_URL,
        "-u", f"{WALLET}.{WORKER_NAME}",
        "-p", "x",
        "--no-getwork",
        "-S", "opencl:auto",      # Auto all GPUs
        "--intensity", os.getenv("INTENSITY", "19"),
        "--api-listen",
        "--quiet"
    ]

    # Add GPU count hint
    if GPUS_PER_POD > 1:
        cmd.extend(["--set", f"gpu_count={GPUS_PER_POD}"])

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1)

        while True:
            line = process.stdout.readline()
            if line:
                hashrate = parse_bfg_output(line)
                if hashrate > 0:
                    gh = hashrate / 1e9
                    HASH_RATE.labels(gpu="total").set(gh)
                    bus.set("worker:hashrate", round(gh, 4))  # GH/s
                    bus.increment("cluster:total_hashrate_btc", int(hashrate))
                    bus.set("worker:status", "mining")

                if "accepted" in line.lower():
                    SHARES_ACCEPTED.inc()
                    bus.increment("cluster:shares_accepted", 1)
                    logger.info("✅ Share accepted!")

            if process.poll() is not None:
                logger.error("BFGMiner died, restarting in 10s...")
                time.sleep(10)
                break

            time.sleep(0.2)

    except Exception as e:
        logger.error(f"Critical error: {e}")

if __name__ == "__main__":
    main()