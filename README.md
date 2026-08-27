# Aurora Swarm BTC

Entropy-driven Bitcoin mining swarm with a Comms Layer mesh, sensing contract, and a growing hybrid path into [MetaField](https://github.com/TheBabelDragon/metafield).

**They yearn for the mines.**

This repo is the swarm substrate: node discovery, Redis mesh, dashboard command-and-control, CPU-first mining, and a mod system. Pair it with `wifi-sensing-system` for physical-spatial context and with MetaField for lattice / optical / ZVS field intelligence.

## Quick start (Arch, CPU only)

No CUDA required. Default miner backend is CPU.

```bash
sudo pacman -S --needed git docker docker-compose python python-pip python-virtualenv

git clone https://github.com/TheBabelDragon/aurora-swarm-btc.git
cd aurora-swarm-btc
cp .env.example .env

# unique node id on this machine
export AURORA_NODE_ID=${AURORA_NODE_ID:-$(hostname)-aurora}
export AURORA_MINER_BACKEND=cpu
export AURORA_AUTO_MINE=0

docker compose -f docker-compose.solo.yml up -d --build
```

Open http://127.0.0.1:8000

- Comms Layer: mesh peers, LAN discovery, join pack
- Mining: Start / Stop / Status (standalone path does not block if Redis is down)
- Auto-mine stays **off** until you press Start

Stop:

```bash
docker compose -f docker-compose.solo.yml down
```

### Local Python dashboard (no compose)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r dashboard/requirements.txt
export REDIS_URL=redis://127.0.0.1:6379/0
export AURORA_MINER_BACKEND=cpu
python dashboard/dashboard.py
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
3. Bridge copies live HMC / geometry / attractor scalars onto:
   - `aurora:metafield:stats`
   - `aurora:metafield:heartbeat`
   - optional merge into `aurora:sensing:context.metafield`

Redis is optional. If Redis is down the bridge stays file-only and does not crash the swarm.

```bash
# MetaField side (other repo, CPU torch)
python meta_field_distributed.py --world-size 1 --diagnostic --continuous --export-stats --aurora-feed

# Aurora side
python -m mods.metafield_bridge.entrypoint --once
```

See `INTEGRATION_CONTRACT.md` and MetaField `HYBRID_VISION.md`.

## Mods System

All experiments live in `mods/`. Core stays stable. Mods attach through `scheduler/hook_registry.py`.

Current mods: `thermal_aware_scheduler`, `gpu_utilization_balancer`, `torrent_protocol`, `asset_fabric`, `btc_anchor`, `btc_identity`, `ln_tips`, `bvl`, `mining_engine`, `metafield_bridge`.

See `mods/README.md`.

## Tests

```bash
python -m unittest tests.test_metafield_bridge tests.test_mod_loader -v
```

## Related

- [metafield](https://github.com/TheBabelDragon/metafield) — lattice + learned geometry + field bodies
- [wifi-sensing-system](https://github.com/TheBabelDragon/wifi-sensing-system) — WiFi CSI sensing
