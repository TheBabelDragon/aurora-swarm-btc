FROM python:3.11-slim

WORKDIR /app

COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/ ./dashboard/
COPY control/ ./control/
COPY comms/ ./comms/
COPY mods/ ./mods/

ENV PYTHONPATH=/app:/app/dashboard
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# run.py mounts ops + replaces /torrent/status with truthful reporting
CMD ["python", "-m", "uvicorn", "dashboard.run:app", "--host", "0.0.0.0", "--port", "8000"]
