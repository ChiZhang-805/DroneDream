#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; ENVF="$ROOT/deploy/hosted-b/.env"; EX="$ROOT/deploy/hosted-b/.env.example"
[ -f "$ENVF" ] || cp "$EX" "$ENVF"
python3 - <<'PY' "$ENVF"
import sys,secrets,pathlib,re
p=pathlib.Path(sys.argv[1]);s=p.read_text()
def ensure(k,v):
 global s
 if re.search(rf'^{k}=.+',s,flags=re.M): return
 s+=f'\n{k}={v}\n'
if 'APP_SECRET_KEY=replace-me' in s: s=s.replace('APP_SECRET_KEY=replace-me',f'APP_SECRET_KEY={secrets.token_urlsafe(32)}')
if 'DRONEDREAM_DEMO_TOKEN=replace-demo-token' in s:
 t=secrets.token_urlsafe(24); s=s.replace('DRONEDREAM_DEMO_TOKEN=replace-demo-token',f'DRONEDREAM_DEMO_TOKEN={t}'); s=re.sub(r'DEMO_AUTH_TOKENS=.*',f'DEMO_AUTH_TOKENS=demo@dronedream.local:{t}',s)
p.write_text(s)
PY
echo "Initialized $ENVF"
