# Aurora Swarm BTC v1.0 — Final Production

**They yearn for the mines.**

Production-ready entropy-driven Bitcoin mining swarm with Kubernetes + Helm.

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
- Redis control bus
- Intelligent scheduler
- Auto-scaling HPA
- Real-time dashboard
- CI/CD with GitHub Actions

**They do yearn.** 🚀