# asset_fabric

**Content-addressed swarm Asset Fabric**

> Aurora does not require every node to be trustworthy.
> It requires every piece of state to be verifiable.

```
CONTENT     immutable artifact
FABRIC      artifact lifecycle + possession
TORRENT     piece transport          (implementation detail)
BTC         scarce external time
HISTORY     replicated artifact memory
```

Bitcoin is not the artifact store, not the torrent protocol, and not
artifact identity. It supplies an independently verifiable temporal /
scarcity anchor.

## Public API

```python
from mods.asset_fabric.fabric import AssetFabric

fabric = AssetFabric(comms)
asset_id = fabric.publish("/path/to/model.pt", asset_type="model")
fabric.ensure(asset_id)
fabric.possession(asset_id)     # temporally addressable, verified vs claimed
fabric.history(asset_id)        # append-only events
fabric.clock(asset_id)          # ArtifactClock (None epoch if unanchored)
fabric.verify(asset_id)         # peer claims are evidence, not truth
```

`asset_id` is the content-addressed identity. `anchor_id` is a temporal
observation of that identity. Same artifact + different Bitcoin anchors
is the same object, observed at different chain positions.

An artifact can exist before it is anchored. An unanchored artifact has
no authoritative Bitcoin epoch. Wall clocks, peer arrival time, and
torrent completion are observational metadata only.

## Artifact clock

```python
from mods.asset_fabric.btc_clock import BTCClock
from mods.btc_anchor.chain import SimulatedBitcoinChain

clock = BTCClock(comms, chain=SimulatedBitcoinChain())
clock.anchor_asset(asset_id, manifest_hash=manifest.identity_hash())
clock.get_asset_clock(asset_id)
clock.verify_asset_clock(asset_id, claimed=peer_claim)
clock.current_clock()
```

Do not import `torrent_manager` from `btc_clock`. The dependency is:

```
AssetFabric → BTCClock → BTCAnchor
```

## Epoch = Bitcoin-chain-relative artifact time

```python
from mods.asset_fabric.epoch import EpochBuilder, ChainEpoch

epoch = EpochBuilder(comms, chain=chain).from_local_state(...)
# epoch["epoch"] = {chain, height, block_hash, work} or None
```

Never derived from `time.time()`, `datetime.now()`, peer arrival, Redis
arrival, or torrent completion.

## History

Append-only: `PUBLISHED` `ANNOUNCED` `REQUESTED` `PIECE_VERIFIED`
`POSSESSION_VERIFIED` `COMPLETE` `ANCHORED` `REANCHORED`.

A reorg invalidates canonical status and retains the historical observation.

## Repair executor

```python
from mods.asset_fabric.repair_executor import RepairExecutor

execu = RepairExecutor(comms, planner, list_candidates=lambda: node_ids)
execu.run_for_asset(asset_id)
execu.place_rs(asset_id)
```

## Modules

| Module | Role |
|--------|------|
| `fabric` | public verbs |
| `artifact_clock` | canonical ArtifactClock |
| `btc_clock` | Asset Fabric ↔ BTC Anchor adapter |
| `history` | append-only artifact memory |
| `epoch` / `epoch_tick` | Bitcoin-relative state roots |
| `erasure` | Reed-Solomon |
| `topology` | failure domains |
| `repair` / `repair_executor` | verified availability plans |
| `challenge` / `merkle_pieces` / `peer_evidence` | Byzantine content path |
