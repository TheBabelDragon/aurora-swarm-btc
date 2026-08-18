#!/bin/sh
set -e
export PYTHONPATH="/app:/app/dashboard:${PYTHONPATH}"
exec python -m uvicorn dashboard.dashboard:app --host 0.0.0.0 --port 8000
