# DroneDream New Batch User Manual

## 1. Purpose

The **New Batch** page creates multiple jobs in one request. A batch is a convenient way to run a group of related experiments, such as:

- Comparing different tracks.
- Comparing different objective profiles.
- Sweeping multiple baseline controller parameter sets.
- Running the same setup under different wind or noise conditions.
- Submitting multiple mock or real simulator jobs at once.

A batch is not a separate simulator run. It is a container that creates many child jobs.

---

## 2. Basic workflow

1. Open **New Batch** from the left sidebar.
2. Enter a **Batch Name**.
3. Optionally enter a **Description**.
4. Paste a JSON array into **Jobs JSON Array**.
5. Click **Create Batch**.
6. DroneDream creates a batch and child jobs.
7. The page redirects to the Batch Detail page.
8. On the Batch Detail page, monitor progress and open child jobs.
9. When at least two child jobs are completed, click **Compare completed** to compare their results.

---

## 3. Important rule: Jobs JSON Array must be an array

The **Jobs JSON Array** field must contain only an array of job objects.

Correct:

```json
[
  {
    "track_type": "circle",
    "start_point": { "x": 0, "y": 0 },
    "altitude_m": 3,
    "wind": { "north": 0, "east": 0, "south": 0, "west": 0 },
    "sensor_noise_level": "medium",
    "objective_profile": "robust"
  }
]
```

Incorrect:

```json
{
  "name": "my-batch",
  "jobs": [
    {
      "track_type": "circle"
    }
  ]
}
```

The page already has separate fields for **Batch Name** and **Description**. Do not include them inside the JSON textarea.

---

## 4. Batch-level fields

### Batch Name

Human-readable batch name.

Example:

```text
circle-parameter-sweep
```

### Description

Optional notes about the experiment.

Example:

```text
Compare three baseline parameter sets on a circular track using the mock simulator.
```

### Jobs JSON Array

Array of job creation objects. The array size must be between 1 and 50.

---

## 5. Child job object schema

Each object in the array is equivalent to a New Job payload.

### Minimal required fields

A minimal job should include:

```json
{
  "track_type": "circle",
  "start_point": {
    "x": 0,
    "y": 0
  },
  "altitude_m": 3,
  "wind": {
    "north": 0,
    "east": 0,
    "south": 0,
    "west": 0
  },
  "sensor_noise_level": "medium",
  "objective_profile": "robust"
}
```

### Common optional fields

Most practical batch jobs should include:

```json
{
  "display_name": "job-label",
  "simulator_backend": "mock",
  "optimizer_strategy": "heuristic",
  "max_iterations": 3,
  "trials_per_candidate": 3,
  "acceptance_criteria": {
    "target_rmse": 0.5,
    "target_max_error": 2.0,
    "min_pass_rate": 0.8
  },
  "baseline_parameters": {
    "kp_xy": 1,
    "kd_xy": 0.2,
    "ki_xy": 0.05,
    "vel_limit": 5,
    "accel_limit": 4,
    "disturbance_rejection": 0.5
  }
}
```

---

## 6. Job parameters inside a batch

### display_name

Optional label for the child job.

Example:

```json
"display_name": "circle-low-gain"
```

### track_type

Allowed values:

```text
circle
u_turn
lemniscate
custom
```

### reference_track

Required only for `custom` tracks. It must be an array of waypoint objects.

Example:

```json
"reference_track": [
  { "x": 0, "y": 0, "z": 3 },
  { "x": 5, "y": 0, "z": 3 },
  { "x": 5, "y": 5, "z": 3 }
]
```

### start_point

Track origin.

Example:

```json
"start_point": {
  "x": 0,
  "y": 0
}
```

### altitude_m

Flight altitude in meters.

Typical value:

```json
"altitude_m": 3
```

### wind

Wind vector components in meters per second.

Validation range for each component is usually:

```text
-10 – 10
```

Example:

```json
"wind": {
  "north": 0,
  "east": 2,
  "south": 0,
  "west": 0
}
```

### sensor_noise_level

Allowed values:

```text
low
medium
high
```

### objective_profile

Allowed values:

```text
stable
fast
smooth
robust
custom
```

### baseline_parameters

Controller parameters used as the baseline.

```json
"baseline_parameters": {
  "kp_xy": 1,
  "kd_xy": 0.2,
  "ki_xy": 0.05,
  "vel_limit": 5,
  "accel_limit": 4,
  "disturbance_rejection": 0.5
}
```

### simulator_backend

Allowed values:

```text
mock
real_cli
```

Use `mock` for fast workflow testing.

Use `real_cli` only when PX4/Gazebo and the external simulator runner are configured.

### optimizer_strategy

Allowed values:

```text
none
heuristic
cma_es
gpt
```

Recommendations:

- Use `heuristic` or `cma_es` for batch tests.
- Avoid `gpt` in the first batch test because each GPT job needs an API key.

### max_iterations

Maximum optimizer generations.

Typical values:

```text
1
3
5
10
```

### trials_per_candidate

Number of trials used to score each candidate.

Typical values:

```text
1
3
5
```

### acceptance_criteria

Thresholds used to decide whether a candidate is acceptable.

```json
"acceptance_criteria": {
  "target_rmse": 0.5,
  "target_max_error": 2.0,
  "min_pass_rate": 0.8
}
```

Fields:

| Field | Meaning |
|---|---|
| `target_rmse` | Optional RMSE threshold. Use `null` to skip. |
| `target_max_error` | Optional maximum-error threshold. Use `null` to skip. |
| `min_pass_rate` | Fraction from `0` to `1`. |

### openai

Required only when `optimizer_strategy = gpt`.

```json
"openai": {
  "api_key": "your-openai-api-key",
  "model": "gpt-4.1"
}
```

### advanced_scenario_config

Optional advanced scenario configuration.

```json
"advanced_scenario_config": {
  "wind_gusts": {
    "enabled": true,
    "magnitude_mps": 2.5,
    "direction_deg": 45,
    "period_s": 10
  },
  "sensor_degradation": {
    "gps_noise_m": 0.5,
    "baro_noise_m": 0.2,
    "imu_noise_scale": 1.2,
    "dropout_rate": 0.1
  },
  "battery": {
    "initial_percent": 85,
    "voltage_sag": true,
    "mass_payload_kg": 0.2
  },
  "obstacles": []
}
```

---

## 7. After creating a batch

The Batch Detail page shows:

### Progress

Batch-level status and counts:

- Total child jobs.
- Completed jobs.
- Failed jobs.
- Cancelled jobs.
- Terminal jobs.

### Child Jobs

A table of child jobs with:

- Job ID.
- Status.
- Track type.
- Objective profile.

Click a Job ID to open the child Job Detail page.

### Cancel Batch

Cancels non-terminal child jobs.

### Compare completed

Enabled when at least two child jobs are `COMPLETED`.

This opens the comparison page with completed child jobs pre-selected.

---

## 8. Detailed example: compare two tracks with mock + heuristic

Paste this into **Jobs JSON Array**.

```json
[
  {
    "display_name": "batch-circle-robust",
    "track_type": "circle",
    "start_point": {
      "x": 0,
      "y": 0
    },
    "altitude_m": 3,
    "wind": {
      "north": 0,
      "east": 0,
      "south": 0,
      "west": 0
    },
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "simulator_backend": "mock",
    "optimizer_strategy": "heuristic",
    "max_iterations": 3,
    "trials_per_candidate": 3,
    "acceptance_criteria": {
      "target_rmse": 0.5,
      "target_max_error": 2.0,
      "min_pass_rate": 0.8
    },
    "baseline_parameters": {
      "kp_xy": 1,
      "kd_xy": 0.2,
      "ki_xy": 0.05,
      "vel_limit": 5,
      "accel_limit": 4,
      "disturbance_rejection": 0.5
    }
  },
  {
    "display_name": "batch-lemniscate-smooth",
    "track_type": "lemniscate",
    "start_point": {
      "x": 0,
      "y": 0
    },
    "altitude_m": 3,
    "wind": {
      "north": 0,
      "east": 0,
      "south": 0,
      "west": 0
    },
    "sensor_noise_level": "medium",
    "objective_profile": "smooth",
    "simulator_backend": "mock",
    "optimizer_strategy": "heuristic",
    "max_iterations": 3,
    "trials_per_candidate": 3,
    "acceptance_criteria": {
      "target_rmse": 0.5,
      "target_max_error": 2.0,
      "min_pass_rate": 0.8
    },
    "baseline_parameters": {
      "kp_xy": 1,
      "kd_xy": 0.2,
      "ki_xy": 0.05,
      "vel_limit": 5,
      "accel_limit": 4,
      "disturbance_rejection": 0.5
    }
  }
]
```

Suggested batch fields:

```text
Batch Name: track-comparison-mock
Description: Compare circle and lemniscate tracks with mock heuristic optimization.
```

---

## 9. Detailed example: baseline parameter sweep

This example keeps the same track and objective but changes baseline controller parameters.

```json
[
  {
    "display_name": "low-gain-circle",
    "track_type": "circle",
    "start_point": {
      "x": 0,
      "y": 0
    },
    "altitude_m": 3,
    "wind": {
      "north": 0,
      "east": 0,
      "south": 0,
      "west": 0
    },
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "simulator_backend": "mock",
    "optimizer_strategy": "heuristic",
    "max_iterations": 3,
    "trials_per_candidate": 3,
    "acceptance_criteria": {
      "target_rmse": 0.5,
      "target_max_error": 2.0,
      "min_pass_rate": 0.8
    },
    "baseline_parameters": {
      "kp_xy": 0.8,
      "kd_xy": 0.15,
      "ki_xy": 0.03,
      "vel_limit": 4,
      "accel_limit": 3,
      "disturbance_rejection": 0.4
    }
  },
  {
    "display_name": "default-gain-circle",
    "track_type": "circle",
    "start_point": {
      "x": 0,
      "y": 0
    },
    "altitude_m": 3,
    "wind": {
      "north": 0,
      "east": 0,
      "south": 0,
      "west": 0
    },
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "simulator_backend": "mock",
    "optimizer_strategy": "heuristic",
    "max_iterations": 3,
    "trials_per_candidate": 3,
    "acceptance_criteria": {
      "target_rmse": 0.5,
      "target_max_error": 2.0,
      "min_pass_rate": 0.8
    },
    "baseline_parameters": {
      "kp_xy": 1,
      "kd_xy": 0.2,
      "ki_xy": 0.05,
      "vel_limit": 5,
      "accel_limit": 4,
      "disturbance_rejection": 0.5
    }
  },
  {
    "display_name": "higher-gain-circle",
    "track_type": "circle",
    "start_point": {
      "x": 0,
      "y": 0
    },
    "altitude_m": 3,
    "wind": {
      "north": 0,
      "east": 0,
      "south": 0,
      "west": 0
    },
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "simulator_backend": "mock",
    "optimizer_strategy": "heuristic",
    "max_iterations": 3,
    "trials_per_candidate": 3,
    "acceptance_criteria": {
      "target_rmse": 0.5,
      "target_max_error": 2.0,
      "min_pass_rate": 0.8
    },
    "baseline_parameters": {
      "kp_xy": 1.5,
      "kd_xy": 0.35,
      "ki_xy": 0.08,
      "vel_limit": 6,
      "accel_limit": 5,
      "disturbance_rejection": 0.7
    }
  }
]
```

Suggested batch fields:

```text
Batch Name: baseline-parameter-sweep
Description: Compare low, default, and higher gain baselines on the same circle track.
```

---

## 10. Detailed example: real_cli batch

Use this only when the real simulator environment is configured.

```json
[
  {
    "display_name": "real-cli-circle-robust",
    "track_type": "circle",
    "start_point": {
      "x": 0,
      "y": 0
    },
    "altitude_m": 3,
    "wind": {
      "north": 0,
      "east": 1,
      "south": 0,
      "west": 0
    },
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "simulator_backend": "real_cli",
    "optimizer_strategy": "cma_es",
    "max_iterations": 3,
    "trials_per_candidate": 3,
    "acceptance_criteria": {
      "target_rmse": 0.75,
      "target_max_error": 2.0,
      "min_pass_rate": 0.8
    },
    "baseline_parameters": {
      "kp_xy": 1,
      "kd_xy": 0.2,
      "ki_xy": 0.05,
      "vel_limit": 5,
      "accel_limit": 4,
      "disturbance_rejection": 0.5
    }
  },
  {
    "display_name": "real-cli-lemniscate-robust",
    "track_type": "lemniscate",
    "start_point": {
      "x": 0,
      "y": 0
    },
    "altitude_m": 3,
    "wind": {
      "north": 0,
      "east": 1,
      "south": 0,
      "west": 0
    },
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "simulator_backend": "real_cli",
    "optimizer_strategy": "cma_es",
    "max_iterations": 3,
    "trials_per_candidate": 3,
    "acceptance_criteria": {
      "target_rmse": 0.75,
      "target_max_error": 2.0,
      "min_pass_rate": 0.8
    },
    "baseline_parameters": {
      "kp_xy": 1,
      "kd_xy": 0.2,
      "ki_xy": 0.05,
      "vel_limit": 5,
      "accel_limit": 4,
      "disturbance_rejection": 0.5
    }
  }
]
```

---

## 11. Common mistakes

### Mistake 1: The JSON is not an array

Wrong:

```json
{
  "track_type": "circle"
}
```

Correct:

```json
[
  {
    "track_type": "circle"
  }
]
```

### Mistake 2: GPT strategy without OpenAI key

Wrong:

```json
{
  "optimizer_strategy": "gpt"
}
```

Correct:

```json
{
  "optimizer_strategy": "gpt",
  "openai": {
    "api_key": "your-key",
    "model": "gpt-4.1"
  }
}
```

### Mistake 3: Invalid custom track

Wrong:

```json
"reference_track": [
  { "x": 0, "y": 0 }
]
```

Correct:

```json
"reference_track": [
  { "x": 0, "y": 0, "z": 3 },
  { "x": 5, "y": 0, "z": 3 }
]
```

### Mistake 4: Too many jobs

The Jobs JSON Array must contain between 1 and 50 jobs.

---

## 12. Recommended first batch

For the first test, use:

```text
simulator_backend: mock
optimizer_strategy: heuristic
max_iterations: 3
trials_per_candidate: 3
```

After confirming that batch creation, child jobs, and comparison work, move to `real_cli` or `gpt`.
