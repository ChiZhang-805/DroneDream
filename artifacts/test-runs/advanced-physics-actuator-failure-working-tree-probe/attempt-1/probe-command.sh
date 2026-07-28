#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY_ROOT="/mnt/z/DroneDream-worktrees/aurora-20260728"
readonly RUN_DIR="${REPOSITORY_ROOT}/artifacts/test-runs/advanced-physics-actuator-failure-working-tree-probe/attempt-1"
readonly INPUT_PATH="${RUN_DIR}/trial-input.json"
readonly OUTPUT_PATH="${RUN_DIR}/trial-result.json"
readonly REQUEST_PATH="${RUN_DIR}/scenario_effects.request.json"
readonly EVIDENCE_PATH="${RUN_DIR}/scenario_effects.applied.json"

unset OPENAI_API_KEY
export PYTHONPATH="${REPOSITORY_ROOT}/backend"
export PX4_GAZEBO_DRY_RUN=false
export PX4_GAZEBO_HEADLESS=true
export PX4_GAZEBO_LAUNCH_GUI_CLIENT=false
export PX4_GAZEBO_DRAW_TRACK_MARKER=false
export PX4_GAZEBO_TIMEOUT_SECONDS=900
export PX4_GAZEBO_KEEP_RAW_LOGS=true
export PX4_GAZEBO_WORKDIR="${REPOSITORY_ROOT}"
export PX4_AUTOPILOT_DIR="/opt/PX4-Autopilot"
export PX4_SETUP_COMMANDS="source /opt/dronedream/venv/bin/activate"
export PX4_PARAMETER_TRANSPORT=environment
export PX4_TELEMETRY_MODE=ulog
export PX4_ULOG_ROOT="/opt/PX4-Autopilot/build/px4_sitl_default/rootfs/log"
export PX4_ENABLE_OFFBOARD_EXECUTOR=true
export PX4_GAZEBO_LAUNCH_COMMAND="/opt/dronedream/venv/bin/python3 ${REPOSITORY_ROOT}/scripts/simulators/local_px4_launch_wrapper.py --run-dir {run_dir} --input {trial_input} --params {params_json} --px4-params {px4_params_json} --track {track_json} --telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} --vehicle {vehicle} --airframe {airframe} --simulator-model {simulator_model} --world {world} --px4-version {px4_version} --headless {headless}"
export PX4_OFFBOARD_EXECUTOR_COMMAND="/opt/dronedream/venv/bin/python3 ${REPOSITORY_ROOT}/scripts/simulators/px4_offboard_track_executor.py"
export DRONEDREAM_PX4_EXECUTABLE="/opt/PX4-Autopilot/build/px4_sitl_default/bin/px4"
export DRONEDREAM_GAZEBO_EXECUTABLE="/usr/bin/gz"

process_count() {
  { pgrep -ax "px4|gz|mavsdk_server" || true; } | awk 'END { print NR + 0 }'
}

readonly PREEXISTING_PROCESS_COUNT="$(process_count)"
if [[ "${PREEXISTING_PROCESS_COUNT}" -ne 0 ]]; then
  echo "refusing to start with ${PREEXISTING_PROCESS_COUNT} residual process(es)" >&2
  pgrep -ax "px4|gz|mavsdk_server" >&2 || true
  exit 67
fi

cd "${REPOSITORY_ROOT}"
readonly SUBJECT_HEAD="793f02089413f2baa8ea78387cd1e9e078f02b83"
printf '%s  %s\n' \
  "$(sha256sum backend/app/simulator/scenario_effects.py | awk '{print $1}')" \
  "backend/app/simulator/scenario_effects.py" \
  "$(sha256sum scripts/simulators/local_px4_launch_wrapper.py | awk '{print $1}')" \
  "scripts/simulators/local_px4_launch_wrapper.py" \
  "$(sha256sum scripts/simulators/px4_gazebo_runner.py | awk '{print $1}')" \
  "scripts/simulators/px4_gazebo_runner.py" \
  "$(sha256sum scripts/simulators/px4_offboard_track_executor.py | awk '{print $1}')" \
  "scripts/simulators/px4_offboard_track_executor.py" \
  > "${RUN_DIR}/source-inventory.sha256"
readonly SOURCE_INVENTORY_SHA256="$(
  sha256sum "${RUN_DIR}/source-inventory.sha256" | awk '{print $1}'
)"

readonly START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
readonly START_EPOCH="${SECONDS}"
set +e
/opt/dronedream/venv/bin/python3 \
  "${REPOSITORY_ROOT}/scripts/simulators/px4_gazebo_runner.py" \
  --input "${INPUT_PATH}" \
  --output "${OUTPUT_PATH}" \
  > "${RUN_DIR}/runner-console.log" 2>&1
readonly RUNNER_RC="$?"
set -e

readonly TRIAL_SUCCESS="$(
  if [[ -f "${OUTPUT_PATH}" ]]; then
    /opt/dronedream/venv/bin/python3 -c \
      'import json,sys; print(str(json.load(open(sys.argv[1], encoding="utf-8")).get("success") is True).lower())' \
      "${OUTPUT_PATH}"
  else
    printf false
  fi
)"
readonly PHYSICAL_EFFECT_VERIFIED="$(
  if [[ -f "${REQUEST_PATH}" && -f "${EVIDENCE_PATH}" ]]; then
    /opt/dronedream/venv/bin/python3 -c \
      'import json,sys; from app.simulator.scenario_effects import validate_scenario_effect_evidence; request=json.load(open(sys.argv[1], encoding="utf-8")); evidence=json.load(open(sys.argv[2], encoding="utf-8")); result=validate_scenario_effect_evidence(request,evidence); print(str(result.get("verification_status") == "verified_applied").lower())' \
      "${REQUEST_PATH}" "${EVIDENCE_PATH}"
  else
    printf false
  fi
)"
readonly ACCEPTANCE_RC="$(
  if [[ "${PHYSICAL_EFFECT_VERIFIED}" == "true" ]]; then
    printf 0
  elif [[ "${RUNNER_RC}" -ne 0 ]]; then
    printf '%s' "${RUNNER_RC}"
  else
    printf 69
  fi
)"

sleep 2
readonly END_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
readonly DURATION_SECONDS="$((SECONDS - START_EPOCH))"
readonly RESIDUAL_PROCESS_COUNT="$(process_count)"
printf '{\n  "schema_version": "dronedream.advanced-physics-actuator-failure-probe/v1",\n  "subject_head": "%s",\n  "source_inventory_sha256": "%s",\n  "started_at": "%s",\n  "ended_at": "%s",\n  "duration_seconds": %s,\n  "runner_exit_code": %s,\n  "trial_success": %s,\n  "physical_effect_verified": %s,\n  "acceptance_exit_code": %s,\n  "preexisting_process_count": %s,\n  "residual_process_count": %s,\n  "openai_api_key_used": false\n}\n' \
  "${SUBJECT_HEAD}" \
  "${SOURCE_INVENTORY_SHA256}" \
  "${START_UTC}" \
  "${END_UTC}" \
  "${DURATION_SECONDS}" \
  "${RUNNER_RC}" \
  "${TRIAL_SUCCESS}" \
  "${PHYSICAL_EFFECT_VERIFIED}" \
  "${ACCEPTANCE_RC}" \
  "${PREEXISTING_PROCESS_COUNT}" \
  "${RESIDUAL_PROCESS_COUNT}" \
  > "${RUN_DIR}/execution-window.json"

printf 'RUNNER_RC=%s\nTRIAL_SUCCESS=%s\nPHYSICAL_EFFECT_VERIFIED=%s\nDURATION_SECONDS=%s\nRESIDUAL_PROCESS_COUNT=%s\n' \
  "${RUNNER_RC}" \
  "${TRIAL_SUCCESS}" \
  "${PHYSICAL_EFFECT_VERIFIED}" \
  "${DURATION_SECONDS}" \
  "${RESIDUAL_PROCESS_COUNT}"
if [[ "${RESIDUAL_PROCESS_COUNT}" -ne 0 ]]; then
  pgrep -ax "px4|gz|mavsdk_server" >&2 || true
  exit 68
fi
exit "${ACCEPTANCE_RC}"
