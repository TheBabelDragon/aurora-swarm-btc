#!/usr/bin/env bash
# Ensure MultiFlow classical core is available under vendor/multiflow
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$ROOT/vendor/multiflow"
if [[ -f "$TARGET/__init__.py" ]]; then
  echo "MultiFlow vendor present: $TARGET"
  exit 0
fi
echo "Cloning MultiFlow into vendor/..."
TMP=$(mktemp -d)
git clone --depth 1 https://github.com/TheBabelDragon/MultiFlow.git "$TMP/MultiFlow"
mkdir -p "$ROOT/vendor"
rm -rf "$TARGET"
cp -a "$TMP/MultiFlow/src/multiflow" "$TARGET"
cp -f "$TMP/MultiFlow/LICENSE" "$ROOT/vendor/MULTIFLOW_LICENSE" 2>/dev/null || true
rm -rf "$TMP"
echo "Vendored MultiFlow classical core to $TARGET"
