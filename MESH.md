# Multi-node mesh (collective)

Aurora peers **only** through Redis. Two solo stacks = two separate universes.

## Why you saw 1 node / 1 worker

1. Each machine ran its **own Redis** (`docker-compose.solo.yml`)
2. Both used `AURORA_NODE_ID=dashboard` (same identity)

## Fix — share one Redis on the LAN

**Machine A** (hub, note its IP e.g. `192.168.1.10`):

```bash
export AURORA_NODE_ID=node-a
docker compose -f docker-compose.mesh.yml --profile hub up -d --build
```

**Machine B**:

```bash
export REDIS_URL=redis://192.168.1.10:6379/0
export AURORA_NODE_ID=node-b
docker compose -f docker-compose.mesh.yml up -d --build
```

Open either dashboard → Nodes should list **both** ids.

Allow TCP **6379** between the machines.
