# Multi-node mesh (collective)

Aurora peers through **shared Redis**. LAN **UDP discovery** (port **7379**) auto-announces join URLs.

Beacons are HMAC-signed. Set the **same** `AURORA_MESH_SECRET` on every node and `AURORA_MESH_REQUIRE_AUTH=1` so a random box on Wi-Fi cannot advertise a fake Redis and steal the mesh.

After a node joins the leader, it **re-advertises the leader Redis URL** (not its own empty instance). That was the split-brain bug.

## Redis security (required)

| Topology | Default bind | Auth |
|----------|--------------|------|
| **Solo** (`docker-compose.solo.yml`) | `127.0.0.1` only, `protected-mode yes` | none (loopback) |
| **Mesh hub** (`docker-compose.mesh.yml --profile hub`) | `0.0.0.0` | **`REDIS_PASSWORD` required** (`requirepass`) |
| **Control plane** (`docker-compose.yml`) | internal network only (no host port publish) | none (bridge isolation) |

**Migration from older unauthenticated defaults**

1. Solo: Redis no longer listens on all interfaces. Peers on other hosts cannot reach it without an explicit multi-node setup.
2. Multi-node: set the same `REDIS_PASSWORD` on hub and peers, and point `REDIS_URL` at `redis://:PASSWORD@HUB_IP:6379/0`.
3. Never commit real passwords. Prefer firewall rules limiting TCP 6379 to trusted peers.

## Fastest path — auto export

On the hub dashboard:

1. Open **Comms Layer**
2. Click **Export join pack** or download **join.sh** / **.env**
3. On the other machine: run the script or `source` the env, then start compose

API (when `AURORA_DASHBOARD_API_KEY` is set, send `X-API-Key`):

- `GET /comms/export` — full JSON pack (Redis URL redacted in JSON)
- `GET /comms/export.env` — shell exports
- `GET /comms/export.sh` — one-shot join script
- `GET /comms/discovery` — LAN beacons heard (includes `auth_ok`)

## Manual

**Hub** (`192.168.1.10`):

```bash
export AURORA_NODE_ID=node-a
export AURORA_MESH_SECRET='pick-a-long-random-string'
export AURORA_MESH_REQUIRE_AUTH=1
export REDIS_PASSWORD='another-long-random-string'
export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
docker compose -f docker-compose.mesh.yml --profile hub up -d --build
```

**Peer**:

```bash
export REDIS_PASSWORD='another-long-random-string'
export REDIS_URL="redis://:${REDIS_PASSWORD}@192.168.1.10:6379/0"
export AURORA_NODE_ID=node-b
export AURORA_MESH_SECRET='pick-a-long-random-string'
export AURORA_MESH_REQUIRE_AUTH=1
docker compose -f docker-compose.solo.yml up -d --build
```

Open **TCP 6379** and **UDP 7379** between machines. Guest Wi-Fi AP isolation will silently kill discovery.

## Dashboard authentication

| Endpoint class | Default (no key) | With `AURORA_DASHBOARD_API_KEY` |
|----------------|------------------|--------------------------------|
| Read status / discovery / routes / resolve | public | public |
| Mutation: join, route_send, export, chat send, broadcast, register | open | requires `X-API-Key` or `Authorization: Bearer` |

Do **not** rely on an unverified reverse proxy alone. Set the key when the dashboard port is reachable from untrusted clients.

## If LAN count stays 0

```bash
sudo ss -ulnp | grep 7379
docker compose -f docker-compose.solo.yml logs dashboard | grep -i discovery
curl -s http://127.0.0.1:8000/comms/discovery | python -m json.tool
```

`listen_ok` must be true. If bind failed, something else owns UDP 7379.

## Destination routing (v0.1)

Optional subsystem under `comms/routing/`. Enabled in solo compose for the UI; egress relay still off.

- Resolves service IDs, node IDs, hostnames, IP literals, and content IDs.
- Gateway capability advertisements are authenticated claims (not automatic routes).
- Local mesh continues without public connectivity.
- Egress **policy** is opt-in and denies private/reserved addresses by default.
- TCP **relay/proxy is not implemented** (`RELAY_IMPLEMENTED = False`).
- Mesh send outcomes are truthful: `send_accepted` means transport published; recipient acknowledgment is only reported when the transport provides evidence.

See `docs/DESTINATION_ROUTING.md`. Diagnostics: `/comms/destinations/resolve`, `/comms/routes`, `/comms/gateways`, `/comms/network/status`.
`POST /comms/route_send` for mesh-only delivery (node/service targets).
