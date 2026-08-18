# Aurora Dashboard — Comms Operations Center

```bash
cd dashboard && python dashboard.py
# http://localhost:8000
```

## Bitcoin-facing extras (`btc_ops.py`)

Mounted when the dashboard starts:

| Endpoint | Purpose |
|----------|--------|
| `GET /btc/status` | network, broadcaster mode, pending queue, mining wallet, identity |
| `POST /torrent/process_broadcasts_batched` | Merkle-batch drain of anchor queue |
| `POST /btc/identity/register` | Publish btc_identity claim on the mesh |

Env for real/dry CLI writes:

```bash
export AURORA_BTC_BROADCASTER=cli   # or log
export AURORA_BTC_NETWORK=signet
export AURORA_BTC_CLI_SEND=0        # 1 to actually send via bitcoin-cli
export AURORA_BITCOIN_CLI=bitcoin-cli
```
