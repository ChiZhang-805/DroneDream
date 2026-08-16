# syntax=docker/dockerfile:1.7
ARG UBUNTU_BASE_IMAGE=ubuntu:24.04@sha256:52df9b1ee71626e0088f7d400d5c6b5f7bb916f8f0c82b474289a4ece6cf3faf
FROM ${UBUNTU_BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG PX4_VERSION=v1.16.0
ARG PX4_GIT_URL=https://github.com/PX4/PX4-Autopilot.git
ARG PX4_GIT_COMMIT=6ea3539157ca358c70a515878b77077af7d4611d
ARG GAZEBO_METAPACKAGE=gz-harmonic
ARG GAZEBO_METAPACKAGE_VERSION=1.0.0-1~noble
ARG GAZEBO_APT_KEY_URL=https://packages.osrfoundation.org/gazebo.gpg
ARG GAZEBO_APT_KEY_SHA256=15d0300460e0c9c0efb21fa9770c0bf228988a07d71c4fac985c2161954a25a4
ARG VALKEY_VERSION=8.1.4
ARG VALKEY_GIT_URL=https://github.com/valkey-io/valkey.git
ARG VALKEY_GIT_COMMIT=5f4bae3ea10174a7c872cc099c953b0e91afa93a
ARG PYTHON_VERSION=3.12
ARG BACKEND_VERSION=0.1.0
ARG WORKER_VERSION=0.1.0
ARG MAVSDK_VERSION=3.15.3
ARG PYULOG_VERSION=1.2.3
ARG PX4_BUILD_JOBS=2
ARG DRONEDREAM_UID=2000
ARG DRONEDREAM_GID=2000

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl wget git gnupg lsb-release sudo systemd systemd-sysv \
      python3 python3-pip python3-venv build-essential cmake ninja-build \
      pkg-config procps iproute2 rsync unzip zip jq sqlite3 libssl-dev libsystemd-dev \
      libffi-dev libxml2-dev libxslt1-dev libyaml-dev libsqlite3-dev && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid "${DRONEDREAM_GID}" dronedream && \
    useradd --create-home --uid "${DRONEDREAM_UID}" --gid dronedream --shell /bin/bash dronedream && \
    groupadd --system valkey && \
    useradd --system --gid valkey --home /var/lib/valkey --shell /usr/sbin/nologin valkey

RUN curl --fail --location --silent --show-error "${GAZEBO_APT_KEY_URL}" \
      --output /tmp/gazebo.gpg && \
    echo "${GAZEBO_APT_KEY_SHA256}  /tmp/gazebo.gpg" | sha256sum --check --strict && \
    install -m 0644 /tmp/gazebo.gpg /usr/share/keyrings/gazebo-archive-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/gazebo-archive-keyring.gpg] https://packages.osrfoundation.org/gazebo/ubuntu-stable noble main" \
      >/etc/apt/sources.list.d/gazebo-stable.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      "${GAZEBO_METAPACKAGE}=${GAZEBO_METAPACKAGE_VERSION}" && \
    rm -rf /var/lib/apt/lists/* /tmp/gazebo.gpg

RUN git clone --branch "${PX4_VERSION}" --depth 1 --recursive \
      "${PX4_GIT_URL}" /opt/PX4-Autopilot && \
    test "$(git -C /opt/PX4-Autopilot rev-parse HEAD)" = "${PX4_GIT_COMMIT}" && \
    cd /opt/PX4-Autopilot && \
    bash Tools/setup/ubuntu.sh --no-nuttx && \
    chown -R dronedream:dronedream /opt/PX4-Autopilot

USER dronedream
RUN cd /opt/PX4-Autopilot && \
    make px4_sitl_default -j"${PX4_BUILD_JOBS}"
USER root

RUN git clone --filter=blob:none "${VALKEY_GIT_URL}" /tmp/valkey && \
    git -C /tmp/valkey checkout --detach "${VALKEY_GIT_COMMIT}" && \
    test "$(git -C /tmp/valkey rev-parse HEAD)" = "${VALKEY_GIT_COMMIT}" && \
    make -C /tmp/valkey -j2 BUILD_TLS=yes USE_SYSTEMD=yes && \
    /tmp/valkey/src/valkey-server --version | grep -F "v=${VALKEY_VERSION} " && \
    install -m 0755 /tmp/valkey/src/valkey-server /usr/local/bin/valkey-server && \
    install -m 0755 /tmp/valkey/src/valkey-cli /usr/local/bin/valkey-cli && \
    install -D -m 0644 /tmp/valkey/COPYING /usr/share/doc/valkey/COPYING && \
    rm -rf /tmp/valkey

COPY . /opt/dronedream/source
ARG DRONEDREAM_SOURCE_COMMIT
RUN test -n "${DRONEDREAM_SOURCE_COMMIT}" && \
    python3 -m venv /opt/dronedream/venv && \
    /opt/dronedream/venv/bin/pip install --disable-pip-version-check --no-cache-dir \
      -r /opt/dronedream/source/runtime/locks/python-requirements.lock && \
    /opt/dronedream/venv/bin/pip install --disable-pip-version-check --no-cache-dir \
      --no-deps /opt/dronedream/source/backend /opt/dronedream/source/worker && \
    /opt/dronedream/venv/bin/pip check && \
    test "$(/opt/dronedream/venv/bin/python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')" = "${PYTHON_VERSION}" && \
    test "$(/opt/dronedream/venv/bin/python -c 'import importlib.metadata as m; print(m.version("drone-dream-backend"))')" = "${BACKEND_VERSION}" && \
    test "$(/opt/dronedream/venv/bin/python -c 'import importlib.metadata as m; print(m.version("drone-dream-worker"))')" = "${WORKER_VERSION}" && \
    test "$(/opt/dronedream/venv/bin/python -c 'import importlib.metadata as m; print(m.version("mavsdk"))')" = "${MAVSDK_VERSION}" && \
    test "$(/opt/dronedream/venv/bin/python -c 'import importlib.metadata as m; print(m.version("pyulog"))')" = "${PYULOG_VERSION}" && \
    test "$(dpkg-query -W -f='${Version}' "${GAZEBO_METAPACKAGE}")" = "${GAZEBO_METAPACKAGE_VERSION}" && \
    install -d -m 0755 /usr/share/doc/dronedream-runtime && \
    install -m 0644 /opt/dronedream/source/LICENSE \
      /usr/share/doc/dronedream-runtime/LICENSE && \
    install -m 0644 /opt/dronedream/source/runtime/THIRD_PARTY_NOTICES.md \
      /usr/share/doc/dronedream-runtime/THIRD_PARTY_NOTICES.md && \
    cmp /opt/dronedream/source/runtime/licenses/valkey-COPYING \
      /usr/share/doc/valkey/COPYING && \
    install -d -m 0755 /opt/dronedream/runtime && \
    /opt/dronedream/venv/bin/python /opt/dronedream/source/runtime/tools/runtime_manifest.py \
      generate --pins /opt/dronedream/source/runtime/pins.env \
      --python-lock /opt/dronedream/source/runtime/locks/python-requirements.lock \
      --source-commit "${DRONEDREAM_SOURCE_COMMIT}" \
      --output /opt/dronedream/runtime-manifest.json && \
    dpkg-query -W -f='${Package}=${Version}\n' | LC_ALL=C sort \
      >/opt/dronedream/runtime/apt-packages.lock && \
    /opt/dronedream/venv/bin/pip freeze --all | LC_ALL=C sort \
      >/opt/dronedream/runtime/python-installed.lock

COPY runtime/config/wsl.conf /etc/wsl.conf
COPY runtime/config/runtime.env.default /usr/lib/dronedream/runtime.env.default
COPY runtime/config/valkey.conf /etc/valkey/valkey.conf
COPY runtime/config/journald-dronedream.conf /etc/systemd/journald.conf.d/60-dronedream-runtime.conf
COPY runtime/scripts/runtime-init.sh /usr/lib/dronedream/runtime-init.sh
COPY runtime/scripts/runtime-check.sh /usr/lib/dronedream/runtime-check.sh
COPY runtime/scripts/px4-gazebo-smoke.py /usr/lib/dronedream/px4-gazebo-smoke.py
COPY runtime/scripts/px4-log-cleanup.py /usr/lib/dronedream/px4-log-cleanup.py
COPY runtime/scripts/engine-pack-manager.py /usr/lib/dronedream/engine-pack-manager.py
COPY runtime/scripts/component-pack-manager.py /usr/lib/dronedream/component-pack-manager.py
COPY engine-pack/tools/engine_pack.py /usr/lib/dronedream/engine_pack.py
COPY runtime/systemd/*.service /etc/systemd/system/
COPY runtime/systemd/*.timer /etc/systemd/system/

RUN chmod 0755 /usr/lib/dronedream/runtime-init.sh \
      /usr/lib/dronedream/runtime-check.sh /usr/lib/dronedream/px4-gazebo-smoke.py \
      /usr/lib/dronedream/px4-log-cleanup.py /usr/lib/dronedream/engine-pack-manager.py \
      /usr/lib/dronedream/component-pack-manager.py && \
    chmod 0644 /usr/lib/dronedream/engine_pack.py && \
    install -d -m 0750 -o root -g dronedream /etc/dronedream && \
    install -d -m 0750 -o dronedream -g dronedream /var/lib/dronedream/artifacts && \
    install -d -m 0750 -o dronedream -g dronedream /var/lib/dronedream/runtime-smoke && \
    install -d -m 0750 -o valkey -g valkey /var/lib/valkey && \
    install -d -m 0750 -o dronedream -g dronedream \
      /opt/PX4-Autopilot/build/px4_sitl_default/rootfs/log && \
    install -d -m 2755 -o root -g systemd-journal /var/log/journal && \
    chown -R root:root /opt/dronedream && \
    test -x /usr/lib/dronedream/runtime-init.sh && \
    test -x /usr/local/bin/valkey-server && \
    test -x /opt/dronedream/venv/bin/alembic && \
    test -x /opt/dronedream/venv/bin/uvicorn && \
    test -x /opt/dronedream/venv/bin/drone-dream-worker && \
    test -x /usr/lib/dronedream/px4-log-cleanup.py && \
    test -x /usr/lib/dronedream/engine-pack-manager.py && \
    test -x /usr/lib/dronedream/component-pack-manager.py && \
    test -s /usr/lib/dronedream/engine_pack.py && \
    test -x /usr/bin/curl && \
    test -x /usr/bin/timeout && \
    test -x /usr/bin/head && \
    test -x /usr/bin/systemctl && \
    test -x /usr/bin/journalctl && \
    test -x /usr/bin/ss && \
    test -x /usr/bin/ip && \
    test -s /usr/share/doc/valkey/COPYING && \
    test -s /usr/share/doc/dronedream-runtime/LICENSE && \
    test -s /usr/share/doc/dronedream-runtime/THIRD_PARTY_NOTICES.md && \
    systemd-analyze cat-config systemd/journald.conf >/dev/null && \
    systemd-analyze verify /etc/systemd/system/dronedream-runtime-init.service \
      /etc/systemd/system/valkey.service /etc/systemd/system/dronedream-api.service \
      /etc/systemd/system/dronedream-worker.service \
      /etc/systemd/system/dronedream-px4-log-cleanup.service \
      /etc/systemd/system/dronedream-px4-log-cleanup.timer && \
    systemctl enable dronedream-runtime-init.service valkey.service \
      dronedream-api.service dronedream-worker.service \
      dronedream-px4-log-cleanup.timer && \
    printf '[network]\ngenerateResolvConf=true\n' >/etc/wsl.conf.tmp && \
    cat /etc/wsl.conf >>/etc/wsl.conf.tmp && mv /etc/wsl.conf.tmp /etc/wsl.conf && \
    rm -f /var/lib/dbus/machine-id && \
    : >/etc/machine-id && \
    ln -s /etc/machine-id /var/lib/dbus/machine-id && \
    ln -sfn /dev/null /etc/systemd/system/systemd-firstboot.service && \
    rm -rf /root/.cache /home/dronedream/.cache /tmp/* /var/lib/apt/lists/*

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
