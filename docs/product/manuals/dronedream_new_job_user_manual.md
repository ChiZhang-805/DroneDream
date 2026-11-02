# DroneDream optimization experiment guide

This guide describes the current five-step **Optimization Experiment** wizard. It
replaces the retired one-page and batch workflows.

## Before you start

- The desktop launcher checks and starts DroneDreamRuntime once per application
  session. A later page transition does not repeat the full environment probe.
- Use the settings button in the application header to change language or run an
  explicit environment check.
- `Mock` validates the workflow with deterministic synthetic results. It does not
  prove flight performance. Choose `PX4 / Gazebo` for physical SITL evaluation.
- A real run is accepted only when the worker reports the requested physical
  effects and provides verifiable artifacts. Unsupported effects fail closed.

Click **Optimization Experiment**. Before the wizard opens, enter a short,
recognizable experiment name. The name is stored with every trial and report.

## Navigation and saving

The wizard contains five steps:

1. **Flight Task**
2. **Parameters**
3. **Scenarios**
4. **Constraints & Budget**
5. **Review & Run**

**Next** validates and saves the current step. A later step cannot be opened until
the preceding step has completed. **Back** restores the previously saved values,
so you can revise an earlier step without losing later draft data. The final
button creates the experiment only after every step passes validation.

## 1. Flight Task

This step combines the vehicle, PX4 build, optimization objective, and reference
trajectory.

### Vehicle and simulator

- **Tuning mode** controls how much configuration is shown: Basic, Advanced, or
  Expert. It does not change the optimizer by itself.
- **PX4 version** selects the supported parameter catalogue. Expert mode can pin a
  firmware commit for reproducibility.
- **Vehicle type**, **airframe**, **Gazebo model**, and **Gazebo world** must form a
  compatible set.
- **Gazebo rendering** can be disabled for faster unattended runs. Advanced and
  Expert modes also expose simulation speed and PX4 instance ID.

Each drop-down has a value-specific one-line explanation. Read the explanation
after changing a value; it describes the selected configuration rather than a
generic field definition.

### Optimization objective

Choose Stability, Speed, Smoothness, Robustness, or Custom. Presets fill the
objective weights. Advanced and Expert modes can edit tracking, speed,
smoothness, and robustness weights and choose mean, worst-case, CVaR, or
percentile aggregation.

### Reference trajectory

Choose Circle, U-turn, Figure-eight, or Custom. The generated trajectories expose
only the dimensions they need. Custom trajectories open the waypoint editor:

- switch among XY, XZ, YZ, and 3D views;
- add, delete, undo, or clear waypoints with icon controls;
- edit X, Y, and Z numerically;
- select a plotted waypoint to scroll its table row into view; and
- import or export the complete trajectory as JSON.

Generated tracks may be converted to editable waypoints. The editor validates
finite coordinates, altitude limits, point count, and serialized size before the
wizard can continue.

## 2. Parameters

The parameter catalogue is loaded from the backend and grouped by PX4 controller
area. Expand one group at a time. The outer search-space panel scrolls while the
expanded group itself remains complete.

For each parameter you can:

- include or exclude it from tuning;
- review its PX4 variable name and localized meaning;
- inspect its baseline value and related parameters; and
- set a search lower and upper bound.

The backend validates finite values, ordering, catalogue limits, dependencies,
and parameters that require a PX4 restart. **Next** remains disabled until at
least one valid tunable parameter is selected. Safety details that do not fit the
compact UI belong in the PX4 parameter catalogue documentation.

## 3. Scenarios

Choose which scenario cases participate in search and which are reserved for
holdout validation. Search and holdout seeds must not overlap. Common random
numbers make candidates comparable by evaluating them under the same random
conditions.

The main page contains the compact scenario matrix and directional wind values.
Open **Advanced Environment Settings** for presets and physical effects:

- nominal, wind/gust, sensor-degradation, and combined stress presets;
- gust magnitude, direction, and period;
- GPS, barometer, and IMU noise;
- signal dropout;
- initial battery state and voltage sag;
- payload mass; and
- obstacle JSON.

PX4/Gazebo can represent advanced environments, but each effect needs a concrete
launcher/plugin and readback contract. The bundled runner currently proves
static box/cylinder obstacle injection; wind/gust, sensor/GPS, battery, payload,
and actuator-delay effects still require a Runtime extension. DroneDream rejects
a run when the runner cannot prove that every requested effect was physically
applied, preventing nominal physics from being mislabeled as a robustness test.

## 4. Constraints & Budget

Choose the simulator backend and optimizer, then set the experiment limits and
acceptance criteria.

### Optimizers

The seven experimental choices are constrained multi-objective Bayesian
optimization, multi-fidelity multi-objective Bayesian optimization, TuRBO,
SAASBO, surrogate-assisted CMA-ES, BIPOP-CMA-ES, and an adaptive optimizer
portfolio. Legacy heuristic, CMA-ES, GPT, and no-optimizer modes remain available
for comparison and compatibility.

GPT mode opens a separate model-provider dialog. API credentials are sent only
for the submitted run and are not written into the local draft.

### Budgets and acceptance

- **Maximum iterations** limits optimizer updates.
- **Trials per candidate** preserves compatibility with older workers.
- **Maximum total trials** is the hard cost ceiling, including failed trials.
- **Target RMSE**, **target maximum error**, and **minimum pass rate** define
  acceptance, not optimizer preference.

The planner rounds schedules down to complete candidate/scenario groups and
stops before exceeding the hard limit. Holdout trials are kept separate from
search trials so the optimizer cannot overfit the acceptance set.

## 5. Review & Run

Review the vehicle/runtime, parameter count and ranges, optimizer and aggregation,
scenario/search/holdout matrix, and scheduled budget. Any issue links back to the
step and control that needs attention. High-risk or restart-required parameters
remain visible at review time.

Click **Create Optimization Experiment** to submit. The worker then leases trials,
applies a fenced parameter set, runs the simulator, validates artifacts, aggregates
metrics, and asks the optimizer for the next candidate. Cancellation, lease loss,
or stale workers cannot commit a winning result.

## Reading results

The job page separates:

- live state, heartbeat, and cancellation;
- candidate and per-scenario trial metrics;
- reference and actual trajectory replay;
- acceptance and holdout results;
- optimizer provenance and reproducibility data; and
- downloadable artifacts and reports.

A `Mock` result is always labeled synthetic. Treat only a completed PX4/Gazebo run
with validated artifacts and effect evidence as physical simulation evidence.
