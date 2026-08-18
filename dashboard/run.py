"""Uvicorn target: dashboard.run:app"""
from __future__ import annotations

# Mining is already on app via dashboard.py — do not re-boot here.
from dashboard.dashboard import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
