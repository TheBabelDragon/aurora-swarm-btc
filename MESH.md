# Multi-node mesh (collective)

Aurora peers through **shared Redis**. LAN **UDP discovery** (port **7379**) auto-announces join URLs.

## Fastest path — auto export

On the hub dashboard:

1. Open **Comms Layer**
2. Click **Export join pack** or download **join.sh** / **.env**
3. On the other machine: run the script or `source` the env, then start compose

API:

- `GET /comms/export` — full JSON pack
- `GET /comms/export.env` — shell exports
- `GET /comms/export.sh` — one-shot join script
- `GET /comms/discovery` — LAN beacons heard

## Manual

**Hub** (`192.168.1.10`):

```bash
export AURORA_NODE_ID=node-a
docker compose -f docker-compose.solo.yml up -d --build
# open http://192.168.1.10:8000 → Comms → Export
```

**Peer**:

```bash
# from export, or:
export REDIS_URL=redis://192.168.1.10:6379/0
export AURORA_NODE_ID=node-b
docker compose -f docker-compose.solo.yml up -d --build
```

Open TCP **6379** and UDP **7379** between machines.
