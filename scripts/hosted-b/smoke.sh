#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; ENVF="$ROOT/deploy/hosted-b/.env"
URL=${1:-http://localhost:8080}
TOKEN=$(python3 - <<'PY' "$ENVF"
import pathlib,sys,re
s=pathlib.Path(sys.argv[1]).read_text()
for k in ['DRONEDREAM_DEMO_TOKEN']:
 m=re.search(rf'^{k}=(.*)$',s,re.M)
 if m: print(m.group(1).strip()); break
PY)
AUTH=(); [ -n "$TOKEN" ] && AUTH=(-H "Authorization: Bearer $TOKEN")
curl -fsS "$URL/health" "${AUTH[@]}" >/dev/null
JOB=$(curl -fsS "$URL/api/v1/jobs" -H 'Content-Type: application/json' "${AUTH[@]}" -d '{"track_type":"circle","start_point":{"x":0,"y":0},"altitude_m":5,"wind":{"north":0,"east":0,"south":0,"west":0},"sensor_noise_level":"medium","objective_profile":"robust","simulator_backend":"real_cli","optimizer_strategy":"heuristic"}')
python3 - <<'PY' "$JOB" "$URL" "$TOKEN"
import json,sys,time,urllib.request
body=json.loads(sys.argv[1]); jid=body['data']['id']; print('job id:',jid)
url=sys.argv[2]; tok=sys.argv[3]
for _ in range(60):
 req=urllib.request.Request(f"{url}/api/v1/jobs/{jid}",headers={"Authorization":f"Bearer {tok}"} if tok else {})
 data=json.loads(urllib.request.urlopen(req).read().decode())['data']; st=data['status'];
 if st in ('COMPLETED','FAILED','CANCELLED'): print('final status:',st); print('summary:',json.dumps(data.get('latest_error'),indent=2)); break
 time.sleep(2)
PY
