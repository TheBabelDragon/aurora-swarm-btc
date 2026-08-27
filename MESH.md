# Multi-node mesh (collective)

Aurora peers through **shared Redis**. LAN **UDP discovery** (port **7379**) auto-announces join URLs.

Beacons are HMAC-signed. Set the **same** `AURORA_MESH_SECRET` on every node and `AURORA_MESH_REQUIRE_AUTH=1` so a random box on Wi‑Fi cannot advertise a fake Redis and steal the mesh.

After a node joins the leader, it **re-advertises the leader Redis URL** (not its own empty instance). That was the split-brain bug.

## Fastest path — auto export

On the hub dashboard:

1. Open **Comms Layer**
2. Click **Export join pack** or download **join.sh** / **.env**
3. On the other machine: run the script or `source` the env, then start compose

API:

- `GET /comms/export` — full JSON pack
- `GET /comms/export.env` — shell exports
- `GET /comms/export.sh` — one-shot join script
- `GET /comms/discovery` — LAN beacons heard (includes `auth_ok`)

## Manual

**Hub** (`192.168.1.10`):

```bash
export AURORA_NODE_ID=node-a
export AURORA_MESH_SECRET='pick-a-long-random-string'
export AURORA_MESH_REQUIRE_AUTH=1
docker compose -f docker-compose.solo.yml up -d --build
# open http://192.168.1.10:8000 → Comms → Export
```

**Peer**:

```bash
export REDIS_URL=redis://192.168.1.10:6379/0
export AURORA_NODE_ID=node-b
export AURORA_MESH_SECRET='pick-a-long-random-string'
export AURORA_MESH_REQUIRE_AUTH=1
docker compose -f docker-compose.solo.yml up -d --build
```

Open **TCP 6379** and **UDP 7379** between machines. Guest Wi‑Fi AP isolation will silently kill discovery.

## If LAN count stays 0

```bash
sudo ss -ulnp | grep 7379
docker compose -f docker-compose.solo.yml logs dashboard | grep -i discovery
curl -s http://127.0.0.1:8000/comms/discovery | python -m json.tool
```

`listen_ok` must be true. If bind failed, something else owns UDP 7379.
