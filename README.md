# Aurora Swarm BTC

Entropy-driven Bitcoin mining swarm with a Comms Layer mesh, sensing contract, and a growing hybrid path into [MetaField](https://github.com/TheBabelDragon/metafield).

**They yearn for the mines.**

## Layers

```
CONTENT     immutable artifact          (content hash = identity)
FABRIC      artifact lifecycle + possession
TORRENT     piece transport
BTC         scarce external temporal ordering
HISTORY     replicated artifact memory
EVIDENCE    integrity-checked evidence objects (mods/evidence_integrity)
```

Bitcoin is not the artifact store. Bitcoin supplies an independently verifiable temporal/scarcity anchor.

## Shared Evidence Contract

Aurora Mesh evidence integrity (`mods/evidence_integrity`) provides content-hash identity, integrity verification, and append-only replication. See `docs/SHARED_EVIDENCE_CONTRACT.md`.

```bash
python -m pytest tests/test_evidence_integrity.py -q
```

---

## Arch Linux walkthrough (solo node)

End-to-end path on a fresh Arch install: install Docker, clone, start the swarm, open the dashboard.

### 1. Install system packages

```bash
sudo pacman -Syu --needed git docker docker-compose base-devel
```

Enable and start the Docker daemon (and optionally the socket for your user):

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
# log out and back in (or newgrp docker) so the group takes effect
```

Verify:

```bash
docker version
docker compose version
```

### 2. Clone and configure

```bash
git clone https://github.com/TheBabelDragon/aurora-swarm-btc.git
cd aurora-swarm-btc
cp -n .env.example .env
```

Optional edits in `.env`:

| Variable | Purpose |
|----------|----------|
| `MINING_WALLET` | Your BTC receive address |
| `AURORA_NODE_ID` | Stable name for this machine (default: hostname-based) |
| `AURORA_DASHBOARD_API_KEY` | If set, mutation APIs require `X-API-Key` |
| `AURORA_MESH_SECRET` | Shared HMAC secret for LAN discovery auth |
| `AEGIS_ENABLED` | AEGIS-42 security oversight (default `1`; set `0` to disable) |

Solo Redis binds **127.0.0.1 only** (no unauthenticated exposure on the LAN).

### 3. Start

One-shot helper:

```bash
chmod +x scripts/aurora-up.sh
./scripts/aurora-up.sh
```

Equivalent compose command:

```bash
docker compose -f docker-compose.solo.yml up -d --build
```

### 4. Open the dashboard

```bash
# browser or:
xdg-open http://127.0.0.1:8000
```

- **Start mining** when you want hashes (CPU path is default).
- **Comms / Destination Routing** panels work without curl.
- Mesh join on the same LAN is automatic via UDP **7379** when discovery is enabled.

### 5. Sanity checks

```bash
curl -s http://127.0.0.1:8000/comms/status | python -m json.tool
curl -s http://127.0.0.1:8000/comms/network/status | python -m json.tool
curl -s http://127.0.0.1:8000/aegis/status | python -m json.tool
docker compose -f docker-compose.solo.yml logs --tail=50 dashboard
```

Confirm Redis is loopback-only:

```bash
ss -lntp | grep 6379
# expect 127.0.0.1:6379 (not 0.0.0.0:6379)
```

### 6. Stop / update

```bash
docker compose -f docker-compose.solo.yml down
# update:
git pull
docker compose -f docker-compose.solo.yml up -d --build
```

### Arch notes

- **Firewall:** if using `firewalld`/`nftables`, allow **UDP 7379** between LAN peers for discovery; TCP **6379** only for deliberate multi-node mesh (with password).
- **CPU miner:** default backend is pure-Python/stratum CPU; no bfgminer required for the stock path.
- **GPU / host tools:** optional worker compose mounts host tools; see `docker-compose.worker.yml` and `worker/README.md`.
- **AUR / extra packages:** not required for solo CPU + Docker. Install host miners only if you intentionally use the worker path.

---

## Multi-node mesh (brief)

Full detail: **`MESH.md`**.

1. Hub: set `REDIS_PASSWORD` and `AURORA_MESH_SECRET`, start with mesh compose `--profile hub`.
2. Peer: same password/secret, `REDIS_URL=redis://:PASSWORD@HUB_IP:6379/0`.
3. Open TCP **6379** and UDP **7379** between machines; guest Wi-Fi AP isolation breaks discovery.

Never run unauthenticated Redis on an untrusted network.

---

## Destination routing (v0.1)

Optional subsystem under `comms/routing/` (enabled in solo compose for the UI).

- Resolves service / node / hostname / IP / content targets
- Authenticated gateway capability *claims* (not automatic trust)
- Policy-first routes; connection-time `deny_private`
- Mesh delivery: `POST /comms/route_send` (node/service only)
- Diagnostics: `/comms/destinations/resolve`, `/comms/routes`, `/comms/gateways`, `/comms/network/status`
- **Egress relay is not implemented** (`RELAY_IMPLEMENTED = False`)
- Delivery outcomes are explicit: `send_accepted` means transport published; recipient ack only when the transport provides evidence

```bash
curl -s 'http://127.0.0.1:8000/comms/destinations/resolve?target=dashboard' | python -m json.tool
curl -s -X POST http://127.0.0.1:8000/comms/route_send \
  -H 'Content-Type: application/json' \
  -d '{"target":"dashboard","payload":{"text":"route ping"}}'
```

See `docs/DESTINATION_ROUTING.md`.

---

## AEGIS-42 security oversight

First-class, local-first security oversight integrated into the Aurora node lifecycle (`mods/aegis_42`). Starts automatically on boot; disable with `AEGIS_ENABLED=0`.

- **Deterministic policy** — works with every AI model disabled; models are advisory only
- Monitors worker lifecycle, tool invocation, capability changes, auth failures, routing/egress decisions, replay, and bypass attempts
- Hash-chained audit log with integrity verification
- Narrow containment only (revoke capability/identity, pause/quarantine, rate-limit) — no remote shell or host-wide kill
- API: `/aegis/status`, `/aegis/events`, `/aegis/audit`, `/aegis/identities`, `/aegis/containment`

```bash
curl -s http://127.0.0.1:8000/aegis/status | python -m json.tool
python -m pytest tests/test_aegis_42.py -q
```

Full design, threat model, and non-goals: **`docs/AEGIS_42.md`**.

---

## Architecture

| Piece | Role |
|-------|------|
| `comms/layer.py` | Mesh: register, heartbeat, targeted + broadcast |
| `comms/routing/` | Destination discovery + gateway routing |
| `dashboard/` | UI + mining status + routing panel |
| `mods/aegis_42` | Security oversight: policy, identity, audit, containment |
| `mods/mining_engine` | Stratum / CPU hashing |
| `mods/asset_fabric` | Asset object, possession, history, Bitcoin clock |
| `mods/btc_anchor` | Commitment, inclusion, reorg |
| `mods/torrent_protocol` | Piece transport |
| `mods/evidence_integrity` | Shared Evidence Contract |
| `scheduler/` | Recovery + mod hooks |
| `sensing/` | Contract with wifi-sensing-system |
| `mods/metafield_bridge` | MetaField stats → mesh |

Shared truth lives on **one Redis**. LAN discovery uses UDP **7379**.

---

## Security defaults

- Solo Redis: loopback only + protected-mode
- Mesh Redis: `REDIS_PASSWORD` required
- `/comms/status` never returns credential-bearing Redis URLs
- Optional `AURORA_DASHBOARD_API_KEY` protects mutation endpoints
- Public TCP relay remains disabled
- AEGIS-42 enabled by default; model-independent baseline policy on node boot

---

## Tests

```bash
# Arch: pytest from pacman or a venv
sudo pacman -S --needed python-pytest
python -m pytest tests/test_destination_routing.py \
  tests/test_routing_live_caller.py \
  tests/test_routing_security_hardening.py \
  tests/test_evidence_integrity.py \
  tests/test_aegis_42.py -q
```

---

## MetaField hybrid

1. Run MetaField with `--export-stats`.
2. Enable `mods/metafield_bridge` (on by default).
3. Bridge copies live scalars onto the mesh when Redis is up.

See `INTEGRATION_CONTRACT.md`.

## Docs map

| Doc | Topic |
|-----|--------|
| `MESH.md` | Multi-node Redis mesh, discovery, Redis auth |
| `docs/DESTINATION_ROUTING.md` | Destination resolve, routes, delivery semantics |
| `docs/SHARED_EVIDENCE_CONTRACT.md` | Evidence integrity |
| `docs/AEGIS_42.md` | Security oversight architecture and threat model |
| `docs/ARCHITECTURE.md` | Layer stack (content → fabric → torrent → BTC) |
| `INTEGRATION_CONTRACT.md` | Sensing ↔ swarm ↔ MetaField |

## License

See repository license file.
