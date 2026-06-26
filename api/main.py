"""
Aurora Swarm BTC - External API v1

Smart, future-proof external API for the mining swarm.

Features:
- Versioned REST API (/api/v1)
- Automatic OpenAPI documentation
- API Key authentication (easy to upgrade to JWT)
- WebSocket support for real-time events
- Clean router structure
- Designed to integrate with Redis bus + Prometheus
"""

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.security import APIKeyHeader
from typing import List

import os

from .routers import status, commands, metrics, workers, events

app = FastAPI(
    title="Aurora Swarm BTC API",
    description="External API for interacting with the Aurora mining swarm.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# API Key authentication
API_KEY = os.getenv("AURORA_API_KEY", "aurora-swarm-secret-key-change-me")
api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API Key"
        )
    return api_key

# Public health check (no auth)
@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "aurora-swarm-api"}

# Include routers
app.include_router(status.router, prefix="/api/v1/status", tags=["Status"], dependencies=[Depends(verify_api_key)])
app.include_router(commands.router, prefix="/api/v1/commands", tags=["Commands"], dependencies=[Depends(verify_api_key)])
app.include_router(metrics.router, prefix="/api/v1/metrics", tags=["Metrics"], dependencies=[Depends(verify_api_key)])
app.include_router(workers.router, prefix="/api/v1/workers", tags=["Workers"], dependencies=[Depends(verify_api_key)])
app.include_router(events.router, prefix="/api/v1/events", tags=["Events"], dependencies=[Depends(verify_api_key)])

# WebSocket for real-time events (authenticated)
active_connections: List[WebSocket] = []

@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo or handle client messages if needed
            await websocket.send_text(f"Message received: {data}")
    except WebSocketDisconnect:
        active_connections.remove(websocket)

@app.get("/", include_in_schema=False)
def root():
    return {
        "message": "Aurora Swarm BTC API is running.",
        "docs": "/docs",
        "health": "/health"
    }
