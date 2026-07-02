# Private Repo Structure: aurora-coordination

This document outlines the recommended structure for the new **private** repository `TheBabelDragon/aurora-coordination`.

This repo will contain privileged coordination logic, advanced policy, and the **Overlord / Throne Room** layer.

## Recommended Folder Structure

```
aurora-coordination/
├── overlord/                      # Highest privilege layer (Throne Room / Overlord Synergy)
│   ├── __init__.py
│   ├── throne_room.py             # Core high-privilege coordination & visibility
│   ├── synergy_engine.py          # Cross-system intelligence & decision fusion
│   └── command_authority.py       # Final privileged command issuance
├── coordination/                  # General coordination logic
│   ├── __init__.py
│   └── coordinator.py
├── agents/                        # Future autonomous agents
├── integration/
│   ├── __init__.py
│   └── aurora_mesh_adapter.py   # Clean adapter to public CommsLayer
├── README.md
└── requirements.txt
```

## Naming Philosophy

- `overlord/` = The "Throne Room" — highest level of synergy and control
- Not everything in the swarm should have visibility or access here
- This layer can evolve independently from the public mesh

## Relationship to Public Repo

- Public repo (`aurora-swarm-btc`): Mesh foundation + node capabilities
- Private repo (`aurora-coordination`): Privileged coordination + Overlord logic
- Communication happens via Redis mesh + well-defined contracts
