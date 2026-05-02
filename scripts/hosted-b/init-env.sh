#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; ENVF="$ROOT/deploy/hosted-b/.env"; EX="$ROOT/deploy/hosted-b/.env.example"
[ -f "$ENVF" ] || cp "$EX" "$ENVF"
python3 - <<'PY' "$ENVF"
import pathlib
import re
import secrets
import sys

p = pathlib.Path(sys.argv[1])
s = p.read_text()
if 'APP_SECRET_KEY=replace-me' in s:
    s = s.replace('APP_SECRET_KEY=replace-me', f'APP_SECRET_KEY={secrets.token_urlsafe(32)}')
if 'DRONEDREAM_DEMO_TOKEN=replace-demo-token' in s:
    token = secrets.token_urlsafe(24)
    s = s.replace('DRONEDREAM_DEMO_TOKEN=replace-demo-token', f'DRONEDREAM_DEMO_TOKEN={token}')
    s = re.sub(r'DEMO_AUTH_TOKENS=.*', f'DEMO_AUTH_TOKENS=demo@dronedream.local:{token}', s)
p.write_text(s)

env = {}
for line in p.read_text().splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or '=' not in stripped:
        continue
    key, value = stripped.split('=', 1)
    env[key] = value

print(f'Initialized {p}')
print('')
print('Hosted B environment summary:')
print(f'  .env path: {p}')
print(f"  PUBLIC_SITE_URL: {env.get('PUBLIC_SITE_URL', '(not set)')}")
print(f"  DRONEDREAM_DEMO_TOKEN: {env.get('DRONEDREAM_DEMO_TOKEN', '(not set)')}")
print('')
print('Next steps:')
print('  scripts/hosted-b/up.sh')
print('  scripts/hosted-b/smoke.sh')
print('  scripts/hosted-b/down.sh')
print('')
print('Reminder: do not commit deploy/hosted-b/.env')
PY
