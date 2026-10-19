FROM python:3.11-slim

WORKDIR /app

COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# MultiFlow classical core (optional scheduling adapter). Fail soft if git unreachable.
RUN pip install --no-cache-dir "multiflow @ git+https://github.com/TheBabelDragon/MultiFlow.git" \
    || echo "WARNING: MultiFlow pip install skipped — adapter will report package_missing until available"

COPY dashboard/ ./dashboard/
COPY control/ ./control/
COPY comms/ ./comms/
COPY mods/ ./mods/
# Vendored MultiFlow snapshot (if present in build context)
COPY vendor/ ./vendor/

ENV PYTHONPATH=/app:/app/dashboard:/app/vendor
ENV PYTHONUNBUFFERED=1
# Adapter remains feature-flagged; default off until operator enables
ENV AURORA_MULTIFLOW_ENABLED=0

EXPOSE 8000

# run.py mounts ops + replaces /torrent/status with truthful reporting
CMD ["python", "-m", "uvicorn", "dashboard.run:app", "--host", "0.0.0.0", "--port", "8000"]
