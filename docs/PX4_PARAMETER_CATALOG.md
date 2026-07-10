# PX4 Parameter Catalog and Application Evidence

DroneDream exposes a curated multicopter parameter catalog at
`GET /api/v1/parameter-catalog`. The current revision is
`dronedream.px4.multicopter.2026-07-r1` and supports the PX4 version selectors
`v1.16`, `v1.17`, and `main`.

The catalog is intentionally narrower than the complete PX4 parameter set. It
contains 25 real PX4 names that can be applied to SITL without translating from
DroneDream's legacy `kp_xy`-style Offboard settings:

| Group | Parameters |
| --- | --- |
| XY position/velocity | `MPC_XY_P`, `MPC_XY_VEL_P_ACC`, `MPC_XY_VEL_I_ACC`, `MPC_XY_VEL_D_ACC` |
| Z position/velocity | `MPC_Z_P`, `MPC_Z_VEL_P_ACC`, `MPC_Z_VEL_I_ACC`, `MPC_Z_VEL_D_ACC` |
| Attitude | `MC_ROLL_P`, `MC_PITCH_P`, `MC_YAW_P` |
| Angular rate | `MC_ROLLRATE_P`, `MC_ROLLRATE_I`, `MC_ROLLRATE_D`, `MC_PITCHRATE_P`, `MC_PITCHRATE_I`, `MC_PITCHRATE_D`, `MC_YAWRATE_P`, `MC_YAWRATE_I` |
| Motion limits | `MPC_XY_VEL_MAX`, `MPC_Z_VEL_MAX_UP`, `MPC_Z_VEL_MAX_DN`, `MPC_ACC_HOR`, `MPC_ACC_HOR_MAX`, `MPC_JERK_AUTO` |

Every entry includes type, unit, upstream/guardrail hard bounds, narrower
DroneDream safe bounds, search step, group, risk, reboot flag, dependencies,
and English and Simplified Chinese UI text.

Hard bounds are an absolute validation boundary. Safe bounds are a conservative
search envelope for simulation; they are not a claim that a value is safe for
every physical airframe. Searches outside safe bounds require an explicit
expert/admin override, but values outside hard bounds are always rejected.

The values are based on the
[PX4 parameter reference](https://docs.px4.io/main/en/advanced_config/parameter_reference).
PX4's declared bounds are used where they are finite. DroneDream supplies a
finite guardrail for parameters where upstream does not declare a finite
maximum. The revision is pinned so later PX4 changes can be introduced as a new
catalog rather than silently changing an existing experiment.

## API

List everything or one group:

```http
GET /api/v1/parameter-catalog?px4_version=v1.17
GET /api/v1/parameter-catalog?px4_version=v1.17&group=angular_rate
GET /api/v1/parameter-catalog/MC_ROLLRATE_P?px4_version=v1.17
GET /api/v1/parameter-catalog/groups?px4_version=v1.17
```

Validate a Job `parameter_space` before creation:

```http
POST /api/v1/parameter-catalog/validate
Content-Type: application/json

{
  "px4_version": "v1.17",
  "enforce_safe_bounds": true,
  "selections": [
    {
      "name": "MPC_XY_P",
      "baseline": 0.95,
      "minimum": 0.7,
      "maximum": 1.2,
      "step": 0.1,
      "scale": "linear",
      "value_type": "float",
      "choices": null,
      "enabled": true,
      "locked": false
    }
  ]
}
```

The validator also accepts the API-oriented aliases `search_min`, `search_max`,
and `initial_value`. Disabled and locked entries are reported under `ignored`.
The response contains normalized selections, blocking errors, and non-blocking
dependency warnings suitable for direct display in the experiment UI.

## Trial input contract

The runner looks for real parameters in this order:

1. top-level `px4_parameters`;
2. `job_config.px4_parameters`;
3. real `MC_*`/`MPC_*` keys inside the existing candidate `parameters` object.

The third path lets `Candidate.parameter_json` carry real PX4 names immediately
while the six legacy Offboard fields continue to drive old experiments. The
two namespaces remain separate: a real PX4 gain never masquerades as an
Offboard trajectory setting.

By default the runner enforces safe bounds. An operator may set
`PX4_ENFORCE_SAFE_PARAMETER_BOUNDS=false` for an expert experiment that has
already passed hard-bound validation.

## Application transports

The local wrapper accepts `--px4-params <json>` or the equivalent inherited
`PX4_PARAMETER_REQUEST_PATH`.

`PX4_PARAMETER_TRANSPORT=environment` is the default. It adds the official SITL
overrides `PX4_PARAM_<REAL_NAME>=<value>` to the PX4 process environment and,
after PX4 is available, uses MAVSDK to read every value back before flight. PX4
documents these simulation overrides in its
[simulation guide](https://docs.px4.io/main/en/simulation/).

`PX4_PARAMETER_TRANSPORT=mavsdk` starts PX4 without those overrides, reads the
current values, writes the requested values through MAVSDK, and reads them back
before the Offboard executor starts.

Relevant settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PX4_PARAMETER_TRANSPORT` | `environment` | `environment` or `mavsdk` |
| `PX4_PARAMETER_CONNECTION` | `PX4_OFFBOARD_CONNECTION` | MAVSDK connection URL |
| `PX4_PARAMETER_TIMEOUT_SECONDS` | `15` | connection/readback timeout |
| `PX4_PARAMETER_PX4_VERSION` | inherited runner version | catalog selector |
| `PX4_PARAMETER_ENFORCE_SAFE_BOUNDS` | `true` | reject requests outside safe bounds |
| `PX4_WINDOWS_COMMAND_SHELL` | `powershell` | Windows launcher shell; `direct`, `bash`, and `wsl` are also supported |

MAVSDK is imported only by a real parameter transaction. Catalog/API use and
fake-client unit tests do not require MAVSDK to be installed.

## Evidence and failure semantics

Each Trial with real PX4 parameters must contain:

- `px4_parameters.requested.json` — normalized request and catalog revision;
- `px4_parameters.before.json` — values before a MAVSDK write, or the previous
  process environment overrides for environment transport;
- `px4_parameters.applied.json` — actual PX4 readback, tolerance, mismatches,
  and a `verification.verified` flag.

All three records include transport, PX4 version, timestamp, and Trial context.
The runner publishes them as artifacts and refuses to compute a successful
result if any file is missing, malformed, inconsistent with the request, or
has `verification.verified != true`.

`PX4_GAZEBO_DRY_RUN` and `PX4_SITE_DRY_RUN` produce the same files with
`status=simulated`. This is explicit fixture evidence, not proof that a real
PX4 instance accepted the values.

The reusable `app.simulator.px4_parameters` module exposes an async
`PX4ParameterClient` protocol, a MAVSDK adapter, environment construction, and
apply/readback functions. Tests use a fake client to cover successful writes,
readback mismatch failures, and evidence preservation without a simulator.
