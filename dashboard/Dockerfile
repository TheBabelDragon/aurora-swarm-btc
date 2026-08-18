FROM python:3.11-slim

WORKDIR /app

# Build context is repo root (docker-compose.yml).
COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Full dashboard package + core + mods
COPY dashboard/ ./dashboard/
COPY control/ ./control/
COPY comms/ ./comms/
COPY mods/ ./mods/

ENV PYTHONPATH=/app

EXPOSE 8000

# ship.py installs fabric/mining/bvl/btc routers then serves app
CMD ["python", "-m", "uvicorn", "dashboard.ship:app", "--host", "0.0.0.0", "--port", "8000"]
