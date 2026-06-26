"""
Aurora Swarm BTC - External API (Near Full Connection)

This API is now substantially connected to the swarm's internal systems.

Key capabilities:
- Send real commands via Redis
- Get live-ish status and metrics from Redis
- WebSocket for real-time event streaming
- Clean, versioned, documented
"""

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.security import APIKeyHeader
from typing import List
import json
import os

from .routers import status, commands, metrics, workers, events

app = FastAPI(
    title="Aurora Swarm BTC API",
    description="External API for interacting with the Aurora mining swarm.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

API_KEY = os.getenv("AURORA_API_KEY", "aurora-swarm-secret-key-change-me")
api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API Key")
    return api_key

active_connections: List[WebSocket] = []

async def broadcast_event(event: dict):
    """Broadcast an event to all connected WebSocket clients."""
    message = json.dumps(event)
    for connection in active_connections[:]:  # copy list
        try:
            await connection.send_text(message)
        except:
            active_connections.remove(connection)

@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            # Keep connection alive; clients can send pings if desired
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "service": "aurora-swarm-api"}

app.include_router(status.router, prefix="/api/v1/status", tags=["Status"], dependencies=[Depends(verify_api_key)])
app.include_router(commands.router, prefix="/api/v1/commands", tags=["Commands"], dependencies=[Depends(verify_api_key)])
app.include_router(metrics.router, prefix="/api/v1/metrics", tags=["Metrics"], dependencies=[Depends(verify_api_key)])
app.include_router(workers.router, prefix="/api/v1/workers", tags=["Workers"], dependencies=[Depends(verify_api_key)])
app.include_router(events.router, prefix="/api/v1/events", tags=["Events"], dependencies=[Depends(verify_api_key)])

@app.get("/", include_in_schema=False)
def root():
    return {"message": "Aurora Swarm BTC API running. See /docs"}
