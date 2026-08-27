# mine_governor

Actuator under `mods/mine_governor/`.

| piece | job |
|-------|-----|
| `control.py` | map actions → stop/start/restart/threads |
| `apply.py` | call `mining_standalone` |
| `agent.py` | publish posture, consume `minecmd:{node}` |
| `history.py` | last N applies |
| `routes.py` | `GET /mining/governor` `POST /mining/governor/command` |
| `hooks/on_node_select.py` | prefer governor nodes for mining tasks |

Local test without mesh:

```bash
curl -s http://127.0.0.1:8000/mining/governor
```
