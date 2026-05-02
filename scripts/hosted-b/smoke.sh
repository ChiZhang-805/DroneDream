#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENVF="$ROOT/deploy/hosted-b/.env"
if [ -f "$ENVF" ]; then
  DEFAULT_URL=$(python3 - <<'PY' "$ENVF"
import pathlib,re,sys
s=pathlib.Path(sys.argv[1]).read_text()
m=re.search(r'^PUBLIC_SITE_URL=(.*)$',s,re.M)
print((m.group(1).strip() if m else '') or 'http://localhost:8080')
PY
)
else
  DEFAULT_URL=http://localhost:8080
fi
URL=${1:-$DEFAULT_URL}
TOKEN=$(python3 - <<'PY' "$ENVF"
import pathlib,re,sys
p=pathlib.Path(sys.argv[1])
if not p.exists():
 print('')
 raise SystemExit
s=p.read_text()
m=re.search(r'^DRONEDREAM_DEMO_TOKEN=(.*)$',s,re.M)
print(m.group(1).strip() if m else '')
PY
)
AUTH=(); [ -n "$TOKEN" ] && AUTH=(-H "Authorization: Bearer $TOKEN")
for _ in $(seq 1 60); do
  if curl -fsS "$URL/health" "${AUTH[@]}" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "$URL/health" "${AUTH[@]}" >/dev/null
JOB=$(curl -fsS "$URL/api/v1/jobs" -H 'Content-Type: application/json' "${AUTH[@]}" -d '{"track_type":"circle","start_point":{"x":0,"y":0},"altitude_m":5,"wind":{"north":0,"east":0,"south":0,"west":0},"sensor_noise_level":"medium","objective_profile":"robust","simulator_backend":"real_cli","optimizer_strategy":"heuristic"}')
python3 - <<'PY' "$JOB" "$URL" "$TOKEN"
import json,sys,time,urllib.request,urllib.error
jid=json.loads(sys.argv[1])["data"]["id"]
url=sys.argv[2]; tok=sys.argv[3]
print("job id:",jid)
headers={"Authorization":f"Bearer {tok}"} if tok else {}
last=None
for _ in range(120):
 req=urllib.request.Request(f"{url}/api/v1/jobs/{jid}",headers=headers)
 last=json.loads(urllib.request.urlopen(req).read().decode())["data"]
 st=last.get("status")
 progress=last.get("progress") or {}
 completed=progress.get("completed_trials")
 total=progress.get("total_trials")
 phase=progress.get("current_phase")
 if st in ("COMPLETED","FAILED","CANCELLED"):
  print("final status:",st)
  print("latest_error:",last.get("latest_error"))
  print("progress:",f"{completed}/{total}")
  print("phase:",phase)
  print("last response summary:",json.dumps({"id":last.get("id"),"status":st,"phase":phase,"progress":progress},indent=2))
  sys.exit(0 if st=="COMPLETED" else 1)
 time.sleep(2)
print("final status:", last.get("status") if last else "unknown")
print("latest_error:", None if not last else last.get("latest_error"))
progress=(last.get("progress") if last else None) or {}
completed=progress.get("completed_trials")
total=progress.get("total_trials")
phase=progress.get("current_phase")
print("progress:", None if not last else f"{completed}/{total}")
print("phase:", None if not last else phase)
print("last response summary:", json.dumps({"id": None if not last else last.get("id"), "status": None if not last else last.get("status"), "phase": phase, "progress": progress}, indent=2)[:1200])
sys.exit(1)
PY
