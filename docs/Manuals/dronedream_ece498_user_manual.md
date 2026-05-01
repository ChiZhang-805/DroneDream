# DroneDream ECE498 Page User Manual

## 1. Purpose

The **ECE498** page is a guided experiment page for comparing different levels of automated parameter tuning.

It is organized around three assignment modes:

1. **Baseline (No Tool)**
2. **Tool-Augmented (CMA-ES)**
3. **Tool + Refinement (CMA-ES Loop)**

The page lets you configure track geometry, baseline controller parameters, environment, verifier thresholds, execution backend, and optional advanced scenario settings. It then runs jobs and summarizes results in tables.

---

## 2. The three assignment modes

### Baseline (No Tool)

This mode runs the baseline controller parameters without an optimizer.

Internally, it maps to:

```text
optimizer_strategy = none
```

Use this as the control condition.

### Tool-Augmented (CMA-ES)

This mode runs CMA-ES once.

Internally, it maps to:

```text
optimizer_strategy = cma_es
max_iterations = 1
```

Use this to test whether a tool-assisted optimization pass improves performance over the baseline.

### Tool + Refinement (CMA-ES Loop)

This mode runs CMA-ES through multiple refinement generations.

Internally, it maps to:

```text
optimizer_strategy = cma_es
max_iterations = 3
```

Use this to evaluate whether iterative refinement improves over a single tool-augmented pass.

---

## 3. Basic workflow

1. Open **ECE498** from the left sidebar.
2. Review the **Assignment Modes** explanation.
3. Configure:
   - **Job & Track Configuration**
   - **Baseline Controller Parameters**
   - **Environment**
   - **Verifier / Acceptance Criteria**
   - **Execution Backend**
   - **Advanced Scenario** *(optional)*
4. Click one of the run buttons:
   - **Run Baseline (No Tool)**
   - **Run Tool-Augmented (CMA-ES)**
   - **Run Tool + Refinement (CMA-ES Loop)**
5. Wait for the selected mode to finish.
6. Review:
   - **Run Results**
   - **Candidate / Refinement Turns**

---

## 4. Assignment Modes section

This section explains how the three modes differ.

It does not contain editable fields.

---

## 5. Job & Track Configuration

This section defines the job label, reference path, starting point, and altitude.

### Job Name

Optional human-readable name.

Example:

```text
ece498-circle-baseline
```

### Track Type

Allowed values:

| Value | Meaning |
|---|---|
| `circle` | Circular track. |
| `u_turn` | U-turn path. |
| `lemniscate` | Figure-eight path. |
| `custom` | Custom JSON reference track. |

### Start X and Start Y

Starting point or track origin coordinates.

Example:

```text
Start X = 0
Start Y = 0
```

### Altitude (m)

Flight altitude in meters.

Example:

```text
Altitude = 3
```

### Circle Radius (m)

Shown when `Track Type = circle`.

Example:

```text
Circle Radius = 5
```

### U-turn Straight Length (m)

Shown when `Track Type = u_turn`.

Example:

```text
U-turn Straight Length = 10
```

### U-turn Radius (m)

Shown when `Track Type = u_turn`.

Example:

```text
U-turn Radius = 3
```

### Figure-eight Scale (m)

Shown when `Track Type = lemniscate`.

Example:

```text
Figure-eight Scale = 4
```

### Custom Reference Track JSON

Shown when `Track Type = custom`.

Example:

```json
[
  { "x": 0, "y": 0, "z": 3 },
  { "x": 5, "y": 0, "z": 3 },
  { "x": 5, "y": 5, "z": 3 }
]
```

Rules:

- Must be valid JSON.
- Must be an array.
- Must contain at least 2 points.
- Each point must include numeric `x` and `y`.
- `z` is optional.

---

## 6. Baseline Controller Parameters

This section defines the baseline controller parameter set used by all three ECE498 modes.

### kp_xy

Horizontal proportional gain.

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

Default:

```text
0.05
```

Validation range:

```text
0 – 0.25
```

### vel_limit

Velocity limit.

Default:

```text
5
```

Validation range:

```text
2 – 10
```

### accel_limit

Acceleration limit.

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

Default:

```text
0.5
```

Validation range:

```text
0 – 1
```

### Reset Baseline Defaults

Resets the baseline controller parameters to:

```text
kp_xy = 1
kd_xy = 0.2
ki_xy = 0.05
vel_limit = 5
accel_limit = 4
disturbance_rejection = 0.5
```

It does not reset the track, environment, backend, or advanced scenario settings.

---

## 7. Environment

This section defines wind and sensor noise.

### Wind North

Northward wind component in meters per second.

Validation range:

```text
-10 – 10
```

### Wind East

Eastward wind component in meters per second.

Validation range:

```text
-10 – 10
```

### Wind South

Southward wind component in meters per second.

Validation range:

```text
-10 – 10
```

### Wind West

Westward wind component in meters per second.

Validation range:

```text
-10 – 10
```

### Sensor Noise Level

Allowed values:

| Value | Meaning |
|---|---|
| `low` | Low noise. |
| `medium` | Default noise. |
| `high` | High noise. |

---

## 8. Verifier / Acceptance Criteria

This section defines how the ECE498 page decides pass/fail.

### Objective Profile

Allowed values:

| Value | Typical use |
|---|---|
| `stable` | Stable behavior. |
| `fast` | Faster completion. |
| `smooth` | Smooth trajectory. |
| `robust` | Robustness to disturbances. |
| `custom` | Custom objective profile. |

### Target RMSE

Optional RMSE threshold.

Example:

```text
0.5
```

If blank, this threshold is skipped.

### Target Max Error

Optional maximum tracking error threshold.

Example:

```text
2.0
```

If blank, this threshold is skipped.

### Min Pass Rate

Minimum fraction of completed trials that must pass.

Validation range:

```text
0 – 1
```

Example:

```text
0.8
```

means at least 80% of trials must pass.

---

## 9. Execution Backend

### Simulator Backend

Allowed values:

| Value | Meaning |
|---|---|
| `mock` | Built-in simulator. Fast and good for development/testing. |
| `real_cli` | External PX4/Gazebo command-line simulator. Slower and environment-dependent. |

Recommendation:

Use `mock` for initial ECE498 experiments. Use `real_cli` only after verifying that your Runpod PX4/Gazebo setup is working.

---

## 10. Advanced Scenario

This section is optional. Click **Show Advanced scenario** to expand it.

### Enable advanced scenario

Controls whether `advanced_scenario_config` is sent to the backend.

| Value | Behavior |
|---|---|
| `no` | Do not include advanced scenario configuration. |
| `yes` | Include wind gust, sensor degradation, battery, payload, and obstacle settings. |

### Enable gust

Controls whether wind gust settings are enabled.

### Gust magnitude (m/s)

Magnitude of wind gusts.

Validation range:

```text
0 – 30
```

### Gust direction (deg)

Direction of wind gusts in degrees.

Validation range:

```text
0 <= direction < 360
```

### Gust period (s)

Period of gust oscillation.

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

### Battery initial percent

Initial battery percentage.

Validation range:

```text
0 – 100
```

### Battery voltage sag

Controls whether battery voltage sag is modeled.

### Payload mass (kg)

Optional payload mass.

Validation range:

```text
0 – 20
```

Leave blank for no payload.

### Obstacles JSON

JSON array of obstacles.

Use:

```json
[]
```

for no obstacles.

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

Validation rules:

- Must be valid JSON.
- Must be a JSON array.
- Advanced scenario validation applies only when **Enable advanced scenario = yes**.

---

## 11. Run buttons

### Run Baseline (No Tool)

Creates a job using the current configuration and `optimizer_strategy = none`.

Use this first.

### Run Tool-Augmented (CMA-ES)

Creates a job using the current configuration and `optimizer_strategy = cma_es`, with one optimization generation.

Use this after baseline.

### Run Tool + Refinement (CMA-ES Loop)

Creates a job using the current configuration and `optimizer_strategy = cma_es`, with three optimization generations.

Use this after the one-pass tool-augmented run.

---

## 12. Results

After a run finishes, the page displays result tables.

### Run Results table

Contains:

| Column | Meaning |
|---|---|
| Mode | Baseline, Tool-Augmented, or Tool + Refinement. |
| Job Name | User-provided label. |
| Job ID | Link to the created job. |
| Status | Final job status. |
| Pass / Fail | Verifier result. |
| RMSE | Selected candidate RMSE. |
| Max Error | Selected candidate maximum error. |
| Pass Rate | Fraction of passing completed trials. |
| Score | Candidate score. |
| Optimization Outcome | Backend optimization outcome. |
| Best Candidate ID | Candidate selected by the job. |
| Completed Trials | Number of completed trials. |
| Failed Trials | Number of failed trials. |
| Reason | Explanation of pass/fail. |

### Candidate / Refinement Turns table

Contains candidate-level details:

| Column | Meaning |
|---|---|
| Mode | Which ECE498 mode produced the candidate. |
| Role | Baseline, Tool Turn 1, Refinement Turn 2, Refinement Turn 3, or Other. |
| Candidate Label | Candidate label from the backend. |
| Generation | Candidate generation index. |
| Candidate ID | Candidate identifier. |
| Source | Candidate source type. |
| Trial Count | Total trials for this candidate. |
| Completed | Completed trials. |
| Failed | Failed trials. |
| Passing | Passing completed trials. |
| Pass Rate | Passing ratio. |
| Mean RMSE | Mean RMSE across completed trials. |
| Mean Max Error | Mean max error across completed trials. |
| Mean Score | Mean score across completed trials. |
| Pass / Fail | Candidate verifier result. |

---

## 13. Recommended experiment sequence

Use this sequence for a clear ECE498 workflow:

1. Set `Simulator Backend = mock`.
2. Use the default `circle` track.
3. Use the default baseline controller parameters.
4. Use:
   ```text
   Target RMSE = 0.5
   Target Max Error = 2.0
   Min Pass Rate = 0.8
   ```
5. Run **Baseline (No Tool)**.
6. Run **Tool-Augmented (CMA-ES)**.
7. Run **Tool + Refinement (CMA-ES Loop)**.
8. Compare the Run Results and Candidate / Refinement Turns tables.

---

## 14. Detailed example: basic ECE498 mock experiment

### Job & Track Configuration

```text
Job Name: ece498-circle-basic
Track Type: circle
Start X: 0
Start Y: 0
Altitude (m): 3
Circle Radius (m): 5
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

### Environment

```text
Wind North: 0
Wind East: 0
Wind South: 0
Wind West: 0
Sensor Noise Level: medium
```

### Verifier / Acceptance Criteria

```text
Objective Profile: robust
Target RMSE: 0.5
Target Max Error: 2.0
Min Pass Rate: 0.8
```

### Execution Backend

```text
Simulator Backend: mock
```

### Advanced Scenario

Keep disabled:

```text
Enable advanced scenario: no
```

### Run order

Click these in order:

1. **Run Baseline (No Tool)**
2. **Run Tool-Augmented (CMA-ES)**
3. **Run Tool + Refinement (CMA-ES Loop)**

### Expected review

After all three runs finish, compare:

- Whether CMA-ES improves RMSE over baseline.
- Whether the refinement loop improves over one CMA-ES pass.
- Whether pass rate reaches the threshold.
- Which candidate generation produced the best score.

---

## 15. Detailed example: robust scenario with wind and sensor degradation

### Job & Track Configuration

```text
Job Name: ece498-robust-wind-test
Track Type: circle
Start X: 0
Start Y: 0
Altitude (m): 3
Circle Radius (m): 5
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

### Environment

```text
Wind North: 0
Wind East: 2
Wind South: 0
Wind West: 0
Sensor Noise Level: high
```

### Verifier / Acceptance Criteria

```text
Objective Profile: robust
Target RMSE: 0.75
Target Max Error: 2.5
Min Pass Rate: 0.8
```

### Execution Backend

```text
Simulator Backend: mock
```

### Advanced Scenario

Open **Show Advanced scenario** and configure:

```text
Enable advanced scenario: yes
Enable gust: yes
Gust magnitude (m/s): 2.5
Gust direction (deg): 45
Gust period (s): 10
GPS noise (m): 0.5
Baro noise (m): 0.2
IMU noise scale: 1.2
Dropout rate: 0.1
Battery initial percent: 85
Battery voltage sag: yes
Payload mass (kg): 0.2
Obstacles JSON: []
```

### Run order

1. Run **Baseline (No Tool)**.
2. Run **Tool-Augmented (CMA-ES)**.
3. Run **Tool + Refinement (CMA-ES Loop)**.

### Expected review

This setup is harder than the basic experiment. The baseline may fail, while tool-augmented or refined candidates may improve pass rate and tracking metrics.

---

## 16. Common mistakes

### Mistake 1: Running real_cli before the environment is ready

`real_cli` depends on external PX4/Gazebo configuration. Use `mock` first.

### Mistake 2: Invalid obstacle JSON

Wrong:

```json
{ "type": "cylinder" }
```

Correct:

```json
[
  { "type": "cylinder", "x": 3, "y": 2, "z": 0, "radius": 0.5, "height": 2.0 }
]
```

### Mistake 3: Too strict verifier thresholds

If every mode fails, relax:

```text
Target RMSE
Target Max Error
Min Pass Rate
```

Example:

```text
Target RMSE: 0.75
Target Max Error: 2.5
Min Pass Rate: 0.7
```

### Mistake 4: Comparing modes with different configurations

For a fair ECE498 comparison, keep the same track, baseline, environment, backend, and thresholds for all three modes. Change only the run mode.
