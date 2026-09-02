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
```

Bitcoin is not the artifact store.
Bitcoin is not the torrent protocol.
Bitcoin does not define artifact identity.
Bitcoin supplies an independently verifiable temporal/scarcity anchor
that turns "the swarm remembers this" into
"the swarm remembers this relative to a globally costly chain position."

An artifact can live without Bitcoin.
Bitcoin can anchor an artifact without storing it.
Torrent can transport an artifact without understanding Bitcoin.
Asset Fabric can represent possession without trusting peers.
Artifact history can be replicated independently.

```
BTC proof-of-work chain
      │
      ▼
btc_anchor          canonical temporal anchor
      │
      ▼
asset_fabric        artifact epoch / possession history
      │
      ▼
torrent_protocol    piece distribution
      │
      ▼
swarm peers
```

Public verbs: `ensure` / `publish` / `possession` / `history` / `clock` / `verify`.

## Quick start (Arch, CPU only)

```bash
sudo pacman -S --needed git docker docker-compose
git clone https://github.com/TheBabelDragon/aurora-swarm-btc.git
cd aurora-swarm-btc
chmod +x scripts/aurora-up.sh
./scripts/aurora-up.sh
```

Open http://127.0.0.1:8000 and press **Start mining** when you want hashes.

Second machine on the same LAN: same three lines. Do **not** copy join packs or curl anything. UDP 7379 + TCP 6379 are enough; the dashboard joins the leader Redis the moment it hears a beacon.

Stop:

```bash
docker compose -f docker-compose.solo.yml down
```

## Architecture

| Piece | Role |
|-------|------|
| `comms/layer.py` | Mesh: register, heartbeat, targeted + broadcast messages |
| `dashboard/` | Command UI + mining status truth + artifact clock panel |
| `mods/mining_engine` | Stratum / CPU hashing path |
| `mods/asset_fabric` | Durable asset object, possession, history, Bitcoin clock |
| `mods/btc_anchor` | Commitment, broadcast, inclusion, confirmation, reorg |
| `mods/torrent_protocol` | Piece transport under the fabric |
| `scheduler/` | Recovery + hook registry for mods |
| `sensing/` | Contract with `wifi-sensing-system` |
| `mods/metafield_bridge` | Reads MetaField `stats.json`, optional Redis publish |

Shared truth lives on **one Redis**. LAN UDP discovery uses port **7379**. See `MESH.md`.

## Artifact clock

`btc_height` is the coarse temporal coordinate. Cumulative work is scarcity weight.
`observed_at` is informational. Local wall time is never the artifact epoch.

Unanchored artifacts are valid assets with no authoritative Bitcoin epoch.

## MetaField hybrid (Phase 1 seam)

MetaField already *reads* Aurora (`aurora_feed.py`). This repo now has the matching publish path:

1. Run MetaField with `--export-stats` (writes `/tmp/metafield/stats.json` by default).
2. Enable `mods/metafield_bridge` (on by default).
3. Bridge copies live HMC / geometry / attractor scalars onto the mesh when Redis is up.

Redis is optional for the bridge. See `INTEGRATION_CONTRACT.md`.

## Mods System

Experiments live in `mods/`. Core stays stable.

## Tests

```bash
python -m unittest discover -s tests -v

python -m unittest \
  tests.test_artifact_clock \
  tests.test_asset_btc_anchor \
  tests.test_temporal_possession \
  tests.test_anchor_reorg \
  tests.test_torrent_clock_metadata \
  -v
```
