FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# Hosted B strict real_cli worker:
# - DroneDream worker
# - noVNC/Xvfb display stack
# - PX4 Python deps
# - Gazebo Harmonic runtime/dev deps for gz_x500
#
# PX4-Autopilot itself is mounted at runtime from PX4_AUTOPILOT_HOST_DIR
# into PX4_AUTOPILOT_DIR, usually /opt/PX4-Autopilot.

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python-is-python3 \
    git \
    build-essential \
    cmake \
    ninja-build \
    make \
    ccache \
    curl \
    wget \
    gnupg \
    lsb-release \
    ca-certificates \
    file \
    zip \
    unzip \
    rsync \
    bc \
    pkg-config \
    protobuf-compiler \
    libprotobuf-dev \
    libzmq3-dev \
    cppzmq-dev \
    default-jdk-headless \
    libopencv-dev \
    libeigen3-dev \
    libjsoncpp-dev \
    libyaml-dev \
    libzip-dev \
    libcurl4-openssl-dev \
    uuid-dev \
    libtinyxml2-dev \
    xvfb \
    x11vnc \
    fluxbox \
    novnc \
    websockify \
    x11-utils \
    wmctrl \
    xdotool \
    x11-utils \
    dbus-x11 \
    xauth \
    xterm \
    libgl1 \
    libglx-mesa0 \
    libgl1-mesa-dri \
    libegl1 \
    libglu1-mesa \
    mesa-utils \
    libxkbcommon-x11-0 \
    libxcb-xinerama0 \
    libxcb-xinput0 \
    libxcb-cursor0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-randr0 \
    libxcb-xfixes0 \
    libxcb-sync1 \
    libxcb-xkb1 \
    libxrender1 \
    libxrandr2 \
    libxi6 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxtst6 \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    && rm -rf /var/lib/apt/lists/*

RUN wget -qO /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg \
      https://packages.osrfoundation.org/gazebo.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] http://packages.osrfoundation.org/gazebo/ubuntu-stable $(. /etc/os-release && echo ${UBUNTU_CODENAME:-$VERSION_CODENAME}) main" \
      > /etc/apt/sources.list.d/gazebo-stable.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      gz-harmonic \
      libgz-transport13-dev \
      libgz-sim8-dev \
      libgz-sensors8-dev \
      libgz-plugin2-dev \
      libgz-msgs10-dev \
      libgz-common5-dev \
      libgz-gui8-dev \
      libgz-rendering8-dev \
      libgz-physics7-dev \
      libsdformat14-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend /app/backend
COPY worker /app/worker
COPY scripts /app/scripts

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir '/app/backend[postgres,storage]' /app/worker mavsdk pyulog \
    && pip install --no-cache-dir \
      kconfiglib \
      jinja2 \
      pyyaml \
      numpy \
      packaging \
      jsonschema \
      pyserial \
      toml \
      empy==3.3.4 \
      cerberus \
      lxml \
      future \
      pyros-genmsg \
      catkin_pkg \
      rospkg

RUN chmod +x /app/scripts/hosted-b/start-real-px4-worker-vnc.sh \
    && chmod +x /app/scripts/run-gazebo-vnc.sh

ENV PYTHONPATH=/app/backend
ENV QT_X11_NO_MITSHM=1
ENV LIBGL_ALWAYS_SOFTWARE=1

CMD ["/app/scripts/hosted-b/start-real-px4-worker-vnc.sh"]
