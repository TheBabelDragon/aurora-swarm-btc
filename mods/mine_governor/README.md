# mine_governor

Closes the gap between fleet talk and the hasher that actually runs.

Lives under `mods/mine_governor/`.

- `control.py` — command map (pause → stop, factor → thread cap). No Redis.
- `apply.py` — calls `dashboard.mining_standalone.request_start/stop`.
- `agent.py` — publishes `aurora:mining:worker:{node}` and consumes `aurora:minecmd:{node}`.

Node Command Center / scheduler should write:

```
set_state minecmd:<node_id>  {action, factor?, threads?}
```

This node applies it to the local CPU miner within a few seconds.
