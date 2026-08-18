FROM python:3.11-slim

WORKDIR /app

# Build context is repo root (docker-compose.yml).
COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Dashboard package (ops routers included)
COPY dashboard/ ./dashboard/

# Runtime deps used by fabric / mining / bvl / torrent
COPY control/ ./control/
COPY comms/ ./comms/
COPY mods/ ./mods/

ENV PYTHONPATH=/app

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "dashboard.dashboard:app", "--host", "0.0.0.0", "--port", "8000"]
