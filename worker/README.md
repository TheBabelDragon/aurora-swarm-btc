# Aurora Miner Worker

## Single-machine (recommended)

```bash
# Terminal A — Redis
cd ~/aurora-swarm-btc
docker compose up -d redis

# Install miner on Arch host
yay -S bfgminer
which bfgminer   # note the path

# .env
# REDIS_URL=redis://127.0.0.1:6379/0
# MINING_WALLET=bc1q...
# BFGMINER_PATH=/usr/bin/bfgminer   # optional if not at /usr/bin/bfgminer

docker compose -f docker-compose.worker.yml up -d --build
docker compose -f docker-compose.worker.yml logs -f
```

## Host process (no Docker worker)

```bash
cd ~/aurora-swarm-btc
python3 -m venv .venv && source .venv/bin/activate
pip install -r worker/requirements.txt
export REDIS_URL=redis://127.0.0.1:6379/0
export MINING_WALLET=bc1q...
export WORKER_NAME=aurora-gpu1
python worker/miner_worker.py
```
