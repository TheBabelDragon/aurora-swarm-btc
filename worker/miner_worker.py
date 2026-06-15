import os
import time
import logging
from control.bus import Bus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bus = Bus()

def main():
    logger.info("🚀 Aurora Worker starting - They yearn for the mines")
    while True:
        # Simulate mining
        hashrate = 42.0  # TH/s placeholder
        bus.increment("cluster:total_hashrate_btc", int(hashrate))
        bus.set("worker:status", "hashing")
        time.sleep(30)

if __name__ == "__main__":
    main()