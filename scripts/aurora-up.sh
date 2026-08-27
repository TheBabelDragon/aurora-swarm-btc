#!/usr/bin/env bash
# One command: start this machine on the LAN mesh. No export pack, no curl.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "install docker first" >&2
  exit 1
fi

export AURORA_NODE_ID="${AURORA_NODE_ID:-$(hostname)-aurora}"
export AURORA_MINER_BACKEND="${AURORA_MINER_BACKEND:-cpu}"
export AURORA_AUTO_MINE="${AURORA_AUTO_MINE:-0}"
export AURORA_DISCOVERY="${AURORA_DISCOVERY:-1}"
export AURORA_AUTO_MESH="${AURORA_AUTO_MESH:-1}"
export AURORA_MESH_REQUIRE_AUTH="${AURORA_MESH_REQUIRE_AUTH:-0}"

if [[ ! -f .env ]]; then
  cp -n .env.example .env 2>/dev/null || true
fi

docker compose -f docker-compose.solo.yml up -d --build
echo "Aurora is up. Open http://127.0.0.1:8000 — mesh join is automatic on LAN."
