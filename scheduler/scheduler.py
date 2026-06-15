import time
import logging
from control.bus import Bus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
bus = Bus()

def main():
    logger.info("Scheduler started - Monitoring entropy")
    while True:
        entropy = bus.get("entropy", 1.0)
        logger.info(f"Current entropy: {entropy}")
        time.sleep(60)

if __name__ == "__main__":
    main()