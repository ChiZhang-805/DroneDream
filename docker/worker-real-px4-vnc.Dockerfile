FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv git build-essential cmake ninja-build make curl ca-certificates \
    xvfb x11vnc fluxbox novnc websockify && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt mavsdk pyulog
COPY backend /app/backend
COPY scripts /app/scripts
RUN chmod +x /app/scripts/hosted-b/start-real-px4-worker-vnc.sh /app/scripts/run-gazebo-vnc.sh
ENV PYTHONPATH=/app/backend
CMD ["/app/scripts/hosted-b/start-real-px4-worker-vnc.sh"]
