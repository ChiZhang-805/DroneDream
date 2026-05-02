#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/deploy/hosted-b"

strict_mode="$(python3 - <<'PY'
from pathlib import Path
v='true'
p=Path('.env')
if p.exists():
    for raw in p.read_text(encoding='utf-8').splitlines():
        s=raw.strip()
        if not s or s.startswith('#') or '=' not in s:
            continue
        k,val=s.split('=',1)
        if k.strip()!='HOSTED_REAL_CLI_REQUIRES_PX4':
            continue
        val=val.strip()
        if len(val)>=2 and val[0]==val[-1] and val[0] in {'"',"'"}:
            val=val[1:-1]
        v=val.lower()
        break
print(v)
PY
)"

if [[ "$strict_mode" == "true" ]] && [[ "${ALLOW_STRICT_REAL_CLI_WITH_DEFAULT_WORKER:-false}" != "true" ]]; then
  echo "HOSTED_REAL_CLI_REQUIRES_PX4=true detected in deploy/hosted-b/.env."
  echo "Delegating to scripts/hosted-b/up-real-px4.sh so strict real_cli jobs use the PX4/noVNC worker."
  exec "$ROOT/scripts/hosted-b/up-real-px4.sh" "$@"
fi

docker compose --env-file .env up -d --build "$@"
