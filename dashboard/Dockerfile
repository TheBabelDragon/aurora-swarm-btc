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

# Use dashboard.dashboard:app — proven to load (bvl/btc mount in logs).
# Identity + BVL routes come from btc_ops / bvl_ops at module import.
CMD ["python", "-m", "uvicorn", "dashboard.dashboard:app", "--host", "0.0.0.0", "--port", "8000"]
