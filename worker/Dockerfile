# Placeholder Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY miner_worker.py .
CMD ["python", "miner_worker.py"]