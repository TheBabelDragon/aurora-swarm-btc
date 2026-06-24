# Aurora Swarm BTC v1.0 — Final Production

**They yearn for the mines.**

Now with deep integration to the WiFi CSI Spatial Intelligence System.

## Rich Secure Data Sharing

The swarm receives rich structured context from the sensing system via namespaced Redis channels (`aurora:sensing:*`):
- Full track data
- Events & behaviors
- Memory summaries
- Spatial occupancy

The `sensing/integration.py` + `example_policies.py` show how to consume and react to this data securely.

See: [wifi-sensing-system](https://github.com/TheBabelDragon/wifi-sensing-system)

## Quick Deploy

```bash
helm upgrade --install aurora ./helm/aurora --set mining.wallet=YOUR_WALLET
```

**They do yearn. Now they have eyes.**