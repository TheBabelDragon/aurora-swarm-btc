FROM python:3.11-slim

WORKDIR /app

# Build context is repo root (docker-compose.yml).
COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/dashboard.py .
COPY control/ ./control/
COPY comms/ ./comms/

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "dashboard:app", "--host", "0.0.0.0", "--port", "8000"]
