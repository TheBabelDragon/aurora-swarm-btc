# metafield_bridge

First-class Aurora seam for [MetaField](https://github.com/TheBabelDragon/metafield).

MetaField already consumes Aurora (`aurora_feed.py`, read-only). This mod is the other direction:

- Read `stats.json` written by `meta_field_distributed.py --export-stats`
- Never require torch / MetaField on the Aurora process path
- Optionally publish to Redis so the dashboard and `aurora_feed` see lattice health
- Soft-rank nodes that advertise a live MetaField body when the task looks like a field job

## Paths tried (first hit wins)

1. `$METAFIELD_STATS_PATH`
2. `$METAFIELD_RUNTIME_DIR/stats.json`
3. `$XDG_RUNTIME_DIR/metafield/stats.json`
4. `/tmp/metafield/stats.json`

## Redis keys (optional)

| Key | Meaning |
|-----|---------|
| `aurora:metafield:stats` | Full compact snapshot |
| `aurora:metafield:heartbeat` | `{timestamp, health, live}` |
| `aurora:sensing:context` | Merges `metafield` object; does not wipe WiFi tracks |

Set `METAFIELD_BRIDGE_PUBLISH=0` to stay file-only.

## CLI

```bash
python -m mods.metafield_bridge.entrypoint --once
python -m mods.metafield_bridge.entrypoint --watch --interval 15
```
