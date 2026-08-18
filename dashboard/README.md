# Aurora Dashboard

Operations center for assets, attestation, BVL, and mining provenance.

## Mount optional ops

At the bottom of `dashboard.py` (or on startup):

```python
from mount_all import mount_optional_ops
mount_optional_ops(
    app,
    get_comms=lambda: comms,
    get_torrent_manager=get_torrent_manager,
    get_anchor=get_anchor,
    get_identity=get_identity,
)
```

This attaches:

- `fabric_ops` — who / repair / epoch / reconstruct  
- `mining_ops` — who / worker / provenance / observe  
- `bvl_ops` — ledger  
- `btc_ops` — anchor / identity  

## Architecture

See `docs/ARCHITECTURE.md` and `docs/PROBLEMS_SOLVED.md`.
