# Aurora Swarm BTC v1.0 — Final Production

**They yearn for the mines.**

Production-ready entropy-driven Bitcoin mining swarm with Kubernetes + Helm.

## Now With Spatial Intelligence

This swarm is now integrated with the **WiFi CSI Spatial Intelligence System**.

The physical mining hall has "eyes and ears" via WiFi sensing:
- Real-time occupancy & behavior detection
- Anomaly alerts near rigs
- Thermal/occupancy context pushed into the control bus
- Agent-driven decisions that can scale or pause mining based on human presence

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

Open: http://localhost:8000/status

## Features
- GPU-accelerated workers
- Redis control bus (now receives sensing events)
- Intelligent scheduler
- Auto-scaling HPA
- Real-time dashboard
- CI/CD with GitHub Actions
- **Physical context awareness** via WiFi CSI

**They do yearn.** Now they also know who’s watching. 🚀