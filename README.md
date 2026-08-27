# Aurora Swarm BTC

Entropy-driven Bitcoin mining swarm with a Comms Layer mesh, sensing contract, and a growing hybrid path into [MetaField](https://github.com/TheBabelDragon/metafield).

**They yearn for the mines.**

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
| `dashboard/` | Command UI + mining status truth |
| `mods/mining_engine` | Stratum / CPU hashing path |
| `scheduler/` | Recovery + hook registry for mods |
| `sensing/` | Contract with `wifi-sensing-system` |
| `mods/metafield_bridge` | Reads MetaField `stats.json`, optional Redis publish |

Shared truth lives on **one Redis**. LAN UDP discovery uses port **7379**. See `MESH.md`.

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
python -m unittest tests.test_metafield_bridge tests.test_mod_loader tests.test_mesh_discovery -v
```
