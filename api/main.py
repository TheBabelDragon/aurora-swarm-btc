"""
Aurora Swarm BTC - External API (v1)

This is the recommended way for external systems to interact with the swarm.

Design goals:
- Clean, versioned REST API
- Good documentation (auto-generated)
- Secure by default (API key auth scaffolding)
- Easy to extend
- Works alongside existing Redis bus and Prometheus
"""

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from .routers import status, commands, metrics

app = FastAPI(
    title="Aurora Swarm BTC API",
    description="External API for interacting with the Aurora mining swarm.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Simple API Key authentication (can be upgraded to JWT later)
API_KEY = "aurora-swarm-secret-key-change-me"  # TODO: Move to env/config
api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API Key"
        )
    return api_key

# Include routers
app.include_router(status.router, prefix="/api/v1/status", tags=["Status"], dependencies=[Depends(verify_api_key)])
app.include_router(commands.router, prefix="/api/v1/commands", tags=["Commands"], dependencies=[Depends(verify_api_key)])
app.include_router(metrics.router, prefix="/api/v1/metrics", tags=["Metrics"], dependencies=[Depends(verify_api_key)])

@app.get("/", include_in_schema=False)
def root():
    return {"message": "Aurora Swarm BTC API is running. See /docs for documentation."}
