# DroneDream New Job User Manual

## 1. Purpose

The **New Job** page creates one optimization job. A job defines the flight track, baseline controller parameters, environment, optional advanced scenario, objective profile, simulator backend, and optimizer strategy. After submission, DroneDream stores the job in the backend, and the worker picks it up for execution.

Use **New Job** when you want to run one controlled experiment.

Use **New Batch** instead when you want to submit several jobs at once.

---

## 2. Basic workflow

1. Open **New Job** from the left sidebar.
2. Configure the job in the form sections:
   - **Job & Track Configuration**
   - **Baseline Controller Parameters**
   - **Advanced scenario** *(optional)*
   - **Environment configuration**
   - **Optimization objective**
   - **Execution Backend & Auto-Tuning**
3. Click **Create Job**.
4. The page redirects to the Job Detail page.
5. Wait until the job reaches a terminal state:
   - `COMPLETED`
   - `FAILED`
   - `CANCELLED`
6. Review reports, metrics, trials, artifacts, and trajectory data from the Job Detail page.

---

## 3. Job & Track Configuration

This section defines the flight path and initial position.

### Job Name

Optional human-readable label for the job.

Examples:

```text
circle-real-cli-gpt-run-01
mock-heuristic-baseline-test
robust-wind-test
```

The system still uses the generated `job_id` as the canonical identifier.

### Track Type

Selects the reference trajectory.

Allowed values:

| Value | Meaning |
|---|---|
| `circle` | Circular track. |
| `u_turn` | U-turn path. |
| `lemniscate` | Figure-eight path. |
| `custom` | User-provided waypoint array. |

### Circle Radius (m)

Shown when `Track Type = circle`.

Defines the circle radius in meters.

Typical values:

```text
3
5
10
```

### U-turn Straight Length (m)

Shown when `Track Type = u_turn`.

Defines the straight segment length before and after the turn.

Typical values:

```text
8
10
20
```

### U-turn Radius (m)

Shown when `Track Type = u_turn`.

Defines the turn radius.

Typical values:

```text
2
3
5
```

### Figure-eight Scale (m)

Shown when `Track Type = lemniscate`.

Controls the scale of the figure-eight path.

Typical values:

```text
4
6
8
```

### Start X and Start Y

Initial horizontal position of the track origin.

Example:

```text
Start X = 0
Start Y = 0
```

### Altitude (m)

Flight altitude in meters.

Validation range:

```text
1.0 – 20.0
```

Typical values:

```text
3
5
10
```

### Reference track (JSON)

Shown when `Track Type = custom`.

Provide a JSON array of waypoint objects. Each waypoint requires `x` and `y`; `z` is optional.

Example:

```json
[
  { "x": 0, "y": 0, "z": 3 },
  { "x": 5, "y": 0, "z": 3 },
  { "x": 5, "y": 5, "z": 3 },
  { "x": 0, "y": 5, "z": 3 }
]
```

Rules:

- Must be a JSON array.
- Must contain at least 2 points for a custom track.
- Each point must be an object.
- `x` and `y` must be numeric.
- `z` must be numeric if provided.

---

## 4. Baseline Controller Parameters

This section defines the baseline controller parameter set. The optimizer starts from or compares against these values.

### kp_xy

Horizontal proportional gain.

Higher values usually make the vehicle respond more aggressively to position error.

Default:

```text
1
```

Validation range:

```text
0.3 – 2.5
```

### kd_xy

Horizontal derivative gain.

This dampens velocity or motion error.

Default:

```text
0.2
```

Validation range:

```text
0.05 – 0.8
```

### ki_xy

Horizontal integral gain.

This helps reject steady-state error but can cause instability if too high.

Default:

```text
0.05
```

Validation range:

```text
0 – 0.25
```

### vel_limit

Velocity limit used by the controller.

Default:

```text
5
```

Validation range:

```text
2 – 10
```

### accel_limit

Acceleration limit used by the controller.

Default:

```text
4
```

Validation range:

```text
2 – 8
```

### disturbance_rejection

Disturbance rejection factor.

Higher values increase the controller's resistance to wind or noise disturbances.

Default:

```text
0.5
```

Validation range:

```text
0 – 1
```

### Reset Baseline Defaults

Click **Reset Baseline Defaults** to reset only these six baseline controller parameters:

- `kp_xy`
- `kd_xy`
- `ki_xy`
- `vel_limit`
- `accel_limit`
- `disturbance_rejection`

It does not reset the job name, track, environment, objective, optimizer, or advanced scenario settings.

---

## 5. Advanced scenario

This section is optional. Click **Show Advanced scenario** to open it.

### Enable advanced scenario

Controls whether the advanced scenario object is included in the submitted job payload.

| Value | Behavior |
|---|---|
| `no` | Do not send `advanced_scenario_config`. |
| `yes` | Send advanced wind, sensor, battery, payload, and obstacle configuration. |

### Enable gust

Controls whether wind gusts are enabled inside the advanced scenario.

### Gust magnitude (m/s)

Wind gust magnitude in meters per second.

Validation range:

```text
0 – 30
```

### Gust direction (deg)

Wind gust direction in degrees.

Validation range:

```text
0 <= direction < 360
```

### Gust period (s)

Wind gust period in seconds.

Validation range:

```text
0 < period <= 300
```

### GPS noise (m)

Additional GPS noise in meters.

Validation range:

```text
0 – 100
```

### Baro noise (m)

Additional barometer noise in meters.

Validation range:

```text
0 – 100
```

### IMU noise scale

IMU noise multiplier.

Validation range:

```text
0 – 100
```

### Dropout rate

Sensor dropout rate.

Validation range:

```text
0 – 1
```

Example:

```text
0.2
```

means 20% dropout.

### Battery initial percent

Initial battery percentage.

Validation range:

```text
0 – 100
```

### Battery voltage sag

Controls whether battery voltage sag is modeled.

### Payload mass (kg)

Optional extra payload mass.

Validation range:

```text
0 – 20
```

Leave blank for no payload.

### Obstacles JSON

JSON array of obstacle objects.

Use:

```json
[]
```

when there are no obstacles.

Example:

```json
[
  {
    "type": "cylinder",
    "x": 3,
    "y": 2,
    "z": 0,
    "radius": 0.5,
    "height": 2.0
  },
  {
    "type": "box",
    "x": -2,
    "y": 4,
    "z": 0,
    "size_x": 1.0,
    "size_y": 1.5,
    "size_z": 2.0
  }
]
```

---

## 6. Environment configuration

This section defines wind and sensor noise.

### Wind North, Wind East, Wind South, Wind West

Wind components in meters per second.

Validation range for each field:

```text
-10 – 10
```

Example with mild east wind:

```text
Wind North = 0
Wind East = 2
Wind South = 0
Wind West = 0
```

### Sensor Noise Level

Allowed values:

| Value | Meaning |
|---|---|
| `low` | Low simulated sensor noise. |
| `medium` | Default sensor noise. |
| `high` | High simulated sensor noise. |

---

## 7. Optimization objective

### Objective Profile

Defines how DroneDream scores candidate parameters.

Allowed values:

| Value | Typical interpretation |
|---|---|
| `stable` | Prioritize stable tracking. |
| `fast` | Prioritize speed or completion time. |
| `smooth` | Prioritize smooth trajectories and lower oscillation. |
| `robust` | Prioritize robustness under noise/wind. |
| `custom` | Custom objective profile reserved for extended workflows. |

---

## 8. Execution Backend & Auto-Tuning

This section controls how the job runs and how controller parameters are optimized.

### Simulator Backend

Allowed values:

| Value | Meaning |
|---|---|
| `mock` | Built-in deterministic simulator. Best for quick testing. |
| `real_cli` | External simulator command, usually PX4/Gazebo. Slower and depends on Runpod/environment setup. |

Recommendation:

- Use `mock` first to test workflow.
- Use `real_cli` only after PX4/Gazebo, worker, and artifacts are configured.

### Optimizer Strategy

Allowed values:

| Value | Meaning |
|---|---|
| `none` | No optimization. Runs baseline parameters only. |
| `heuristic` | Deterministic perturbation-based search. |
| `cma_es` | CMA-ES-like adaptive parameter search. |
| `gpt` | Uses OpenAI to propose candidate parameters. |

### Max Iterations

Maximum optimizer generations after baseline.

Validation range:

```text
1 – 20
```

### Trials per Candidate

Number of scenarios/trials used to score each candidate.

Validation range:

```text
1 – 10
```

Increasing this makes evaluation more robust but slower.

### Target RMSE

Optional threshold for root mean squared tracking error.

Leave blank to skip this threshold.

### Target Max Error

Optional threshold for maximum tracking error.

Leave blank to skip this threshold.

### Min Pass Rate

Fraction of trials that must pass for a candidate to be accepted.

Validation range:

```text
0 – 1
```

Examples:

| Value | Meaning |
|---|---|
| `0.5` | At least 50% of trials must pass. |
| `0.8` | At least 80% of trials must pass. |
| `1.0` | All trials must pass. |

### OpenAI API Key

Shown only when `Optimizer Strategy = gpt`.

Required for GPT-based optimization.

The key is used by the backend for the job and is not returned by the API.

### OpenAI Model

Optional.

Leave blank to use the backend default.

Example:

```text
gpt-4.1
```

---

## 9. Buttons

### Create Job

Submits the job to the backend.

If validation passes, you are redirected to the Job Detail page.

### Reset to defaults

Resets the entire New Job form to its default state.

This is different from **Reset Baseline Defaults**, which resets only the six baseline controller parameters.

---

## 10. Detailed example: quick mock heuristic job

Use this setup to test the workflow without real PX4/Gazebo and without an OpenAI key.

### Job & Track Configuration

```text
Job Name: quick-circle-heuristic
Track Type: circle
Circle Radius (m): 5
Start X: 0
Start Y: 0
Altitude (m): 3
```

### Baseline Controller Parameters

```text
kp_xy: 1
kd_xy: 0.2
ki_xy: 0.05
vel_limit: 5
accel_limit: 4
disturbance_rejection: 0.5
```

### Advanced scenario

Keep it disabled:

```text
Enable advanced scenario: no
```

### Environment configuration

```text
Wind North: 0
Wind East: 0
Wind South: 0
Wind West: 0
Sensor Noise Level: medium
```

### Optimization objective

```text
Objective Profile: robust
```

### Execution Backend & Auto-Tuning

```text
Simulator Backend: mock
Optimizer Strategy: heuristic
Max Iterations: 3
Trials per Candidate: 3
Target RMSE: 0.5
Target Max Error: 2.0
Min Pass Rate: 0.8
```

### Expected result

This should create a job quickly. The worker should execute the mock simulation and update the job status. Once completed, open the Job Detail page to review metrics, trials, reports, and artifacts.

---

## 11. Detailed example: GPT job with real_cli

Use this only when PX4/Gazebo and the real simulator command are properly configured.

### Job & Track Configuration

```text
Job Name: real-cli-gpt-circle-robust
Track Type: circle
Circle Radius (m): 5
Start X: 0
Start Y: 0
Altitude (m): 3
```

### Baseline Controller Parameters

```text
kp_xy: 1
kd_xy: 0.2
ki_xy: 0.05
vel_limit: 5
accel_limit: 4
disturbance_rejection: 0.5
```

### Environment configuration

```text
Wind North: 0
Wind East: 1
Wind South: 0
Wind West: 0
Sensor Noise Level: medium
```

### Optimization objective

```text
Objective Profile: robust
```

### Execution Backend & Auto-Tuning

```text
Simulator Backend: real_cli
Optimizer Strategy: gpt
Max Iterations: 10
Trials per Candidate: 3
Target RMSE: 0.75
Target Max Error: 2.0
Min Pass Rate: 0.8
OpenAI API Key: your key
OpenAI Model: gpt-4.1
```

### Expected result

This job may take significantly longer than a mock job. Use the Job Detail page to monitor progress. If the simulator or OpenAI configuration is invalid, the job may fail with an error message.
