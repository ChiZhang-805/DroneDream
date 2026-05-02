FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# This image wires worker + noVNC + DISPLAY for Hosted B strict real_cli mode.
# Full PX4/Gazebo runtime can still require site-specific dependencies/toolchains
# and/or a mounted or prebuilt PX4-Autopilot workspace.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv git build-essential cmake ninja-build make curl ca-certificates \
    xvfb x11vnc fluxbox novnc websockify \
    && rm -rf /var/lib/apt/lists/*

COPY backend /app/backend
COPY worker /app/worker
COPY scripts /app/scripts

RUN pip3 install --no-cache-dir -e '/app/backend[postgres,storage]' \
    && pip3 install --no-cache-dir -e /app/worker \
    && pip3 install --no-cache-dir mavsdk pyulog

RUN chmod +x /app/scripts/hosted-b/start-real-px4-worker-vnc.sh /app/scripts/run-gazebo-vnc.sh

ENV PYTHONPATH=/app/backend
CMD ["/app/scripts/hosted-b/start-real-px4-worker-vnc.sh"]
