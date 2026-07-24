FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Build context is repo root
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/miner_worker.py .
COPY comms/ ./comms/

# BFGMiner is NOT built in this image (source builds are fragile).
# On single-machine host networking, install bfgminer on the host and
# mount it into the container (see docker-compose.worker.yml).

CMD ["python", "miner_worker.py"]
