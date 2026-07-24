FROM python:3.11-slim

WORKDIR /app

# Build context is repo root (docker-compose.yml).
COPY scheduler/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scheduler/scheduler.py .
COPY scheduler/hook_registry.py .
COPY scheduler/node_selector.py .
COPY control/ ./control/
COPY comms/ ./comms/

CMD ["python", "scheduler.py"]
