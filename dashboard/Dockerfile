FROM python:3.11-slim

WORKDIR /app

COPY dashboard/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/ ./dashboard/
COPY control/ ./control/
COPY comms/ ./comms/
COPY mods/ ./mods/

# Package imports (dashboard.*) and bare imports (btc_ops) both work
ENV PYTHONPATH=/app:/app/dashboard

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "dashboard.ship:app", "--host", "0.0.0.0", "--port", "8000"]
