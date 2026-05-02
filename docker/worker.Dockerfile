FROM python:3.11-slim
WORKDIR /app
COPY backend /app/backend
COPY worker /app/worker
COPY scripts /app/scripts
RUN pip install --no-cache-dir -e 'backend[postgres,storage]' && pip install --no-cache-dir -e worker
CMD ["drone-dream-worker"]
