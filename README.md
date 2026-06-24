# Aurora Swarm BTC v1.0 — Final Production

**They yearn for the mines.**

Production-ready entropy-driven Bitcoin mining swarm with Kubernetes + Helm.

## Now With Physical Spatial Awareness

This swarm is tightly integrated with the **WiFi CSI Spatial Intelligence System**.

- Receives real-time occupancy, behavior, and anomaly events from ESP32 CSI nodes
- Can react to physical presence (power scaling, security alerts, etc.)
- Uses `sensing/integration.py` to listen on the Redis control bus

See: [wifi-sensing-system](https://github.com/TheBabelDragon/wifi-sensing-system)

## Quick Deploy

```bash
helm upgrade --install aurora ./helm/aurora \
  --set mining.wallet=bc1qYOURWALLET \
  --namespace aurora --create-namespace
```

```bash
kubectl port-forward svc/aurora-dashboard 8000:8000
```

## Features
- GPU-accelerated workers
- Redis control bus with sensing event support
- Intelligent scheduler
- Auto-scaling
- Real-time dashboard
- Physical context awareness via WiFi CSI

**They do yearn. Now they can see who's near them.**