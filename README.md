# Aurora Swarm BTC v1.0 — Final Production

They yearn for the mines.

## Deploy
helm upgrade --install aurora ./helm/aurora \
  --set mining.wallet=bc1q... \
  --namespace aurora --create-namespace

kubectl port-forward svc/aurora-dashboard 8000:8000