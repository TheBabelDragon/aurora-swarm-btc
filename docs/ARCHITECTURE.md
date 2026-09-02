# Architecture

```
BTC proof-of-work chain
      │
      ▼
btc_anchor                 canonical temporal / scarcity anchor
      │
      ▼
asset_fabric               artifact object, possession, history, clock
      │
      ▼
torrent_protocol           piece distribution
      │
      ▼
swarm peers
```

Do not invert this dependency. New code speaks `ensure` / `publish` /
`possession` / `history` / `clock` / `verify`. Torrent remains the
transport implementation.

## Separation of concerns

| Layer | Defines | Does not define |
|-------|---------|-----------------|
| CONTENT | immutable artifact identity | when it existed |
| FABRIC | lifecycle, verified possession | wall-clock time |
| TORRENT | piece movement, rarest-first | Bitcoin epochs |
| BTC | scarce external ordering | artifact bytes / identity |
| HISTORY | append-only memory | canonical chain status |

`asset_id` is content-addressed. `anchor_id` is a temporal observation.
A peer saying "asset X existed at block 900000" is evidence to verify,
not truth.

An artifact can live without Bitcoin. Bitcoin can anchor an artifact
without storing it. Torrent can transport an artifact without
understanding Bitcoin.
