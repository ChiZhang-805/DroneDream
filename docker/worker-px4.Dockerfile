# Optional starter image only for Hosted B experimentation.
# This Dockerfile does NOT guarantee a complete PX4/Gazebo runtime environment.
# Real execution still requires site-specific dependencies and integration:
# PX4/Gazebo installation, plugins, telemetry, and MAVSDK/ULog setup as required.
FROM ubuntu:22.04
ARG PX4_REF=main
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip git build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend /app/backend
COPY worker /app/worker
COPY scripts /app/scripts
RUN pip3 install --no-cache-dir -e /app/backend[postgres,storage] && pip3 install --no-cache-dir -e /app/worker
CMD ["drone-dream-worker"]
