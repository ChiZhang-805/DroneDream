#!/usr/bin/env bash
set -euo pipefail

manifest=/opt/dronedream/runtime-manifest.json
environment=/etc/dronedream/runtime.env
template=/usr/lib/dronedream/runtime.env.default

install -d -m 0750 -o dronedream -g dronedream /var/lib/dronedream
install -d -m 0750 -o dronedream -g dronedream /var/lib/dronedream/artifacts
install -d -m 0750 -o dronedream -g dronedream /var/lib/dronedream/runtime-smoke
install -d -m 0750 -o valkey -g valkey /var/lib/valkey
install -d -m 0750 -o root -g dronedream /etc/dronedream

if [[ ! -f "$environment" ]]; then
  runtime_id=$(/usr/bin/python3 -c 'import json; print(json.load(open("/opt/dronedream/runtime-manifest.json"))["runtimeId"])')
  secret=$(/opt/dronedream/venv/bin/python -c \
    'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode("ascii"))')
  sed -e "s/__RUNTIME_ID__/${runtime_id}/g" -e "s/__APP_SECRET_KEY__/${secret}/g" \
    "$template" >"${environment}.tmp"
  chown root:dronedream "${environment}.tmp"
  chmod 0640 "${environment}.tmp"
  mv "${environment}.tmp" "$environment"
fi

test -s "$manifest"
test -s "$environment"
