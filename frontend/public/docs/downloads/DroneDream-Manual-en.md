# DroneDream Manual

**Version 1.0.0 · Windows 10/11 x64**

DroneDream is a local-first workspace for configuring, simulating, and comparing PX4 controller parameters. Language models clarify intent and prepare reviewable drafts; deterministic validation, constraints, acceptance rules, and human review keep every experiment reproducible.

> **Engineering boundary**
>
> DroneDream can propose and compare candidates, but it never turns simulation output into automatic approval for hardware flight. Independently validate every selected parameter set in SITL before considering real hardware.

## Contents

- [1. Start here](#1-start-here)
- [2. Install and prepare](#2-install-and-prepare)
- [3. Create with Tuning Chat](#3-create-with-tuning-chat)
- [4. Complete the five-step experiment](#4-complete-the-five-step-experiment)
- [5. Edit a custom flight track](#5-edit-a-custom-flight-track)
- [6. Review history and evidence](#6-review-history-and-evidence)
- [7. Accounts, data, and safety](#7-accounts-data-and-safety)

## 1. Start here

DroneDream keeps experiment design, parameter bounds, scenario definitions, optimization budgets, and result evidence in one reviewable workflow. The language model may clarify a request and prepare a draft, while schema validation, coupling rules, simulation, and acceptance checks retain authority over every run.

Before opening the tuning workspace:

- Use Windows 10 or Windows 11 on an x64 computer.
- Reserve at least 52 GiB on a writable NTFS drive for the isolated runtime.
- Create a DroneDream account so drafts and account settings remain associated with the correct user.
- Configure a model only when you want Tuning Chat or an LLM-guided optimization strategy.
- Keep the application open while an experiment is running unless the run detail explicitly shows a safe terminal state.

## 2. Install and prepare

### 2.1 Download and install

Download the current installer from [getdronedream.com](https://getdronedream.com). Run the installer, choose an eligible local drive, and keep the recommended application directory unless the computer has a specific storage policy.

### 2.2 Prepare the local runtime

On first launch, DroneDream prepares a dedicated WSL2 distribution containing PX4, Gazebo, workers, and experiment artifacts. It does not reuse or modify a personal Ubuntu distribution.

The preparation screen passes through four visible states:

1. **Checking** — host capabilities and disk requirements are being verified.
2. **Preparing** — the isolated runtime is being imported and configured.
3. **Verifying** — required services and manifests are checked.
4. **Checked** — the status light is green and the workspace button becomes available.

> Do not open the tuning workspace while the status still reads **Checking**. The progress indicator reaches 100% only after the environment state becomes **Checked**.

### 2.3 Recheck only when requested

Opening the workspace does not start another environment check. To run the check again, open **Settings**, find **Local runtime**, and select **Check environment**.

## 3. Create with Tuning Chat

Tuning Chat turns an ordinary description into a structured experiment draft. It is designed for users who know the behavior they want but do not want to fill every field before receiving useful guidance.

![Tuning Chat](https://getdronedream.com/docs/en/tuning-chat.png)

### 3.1 Describe the experiment

Include as many of these details as you already know:

- aircraft and PX4 version;
- route shape, dimensions, altitude, and start position;
- target behavior and the relative importance of tracking, speed, smoothness, and robustness;
- wind, sensor noise, payload, battery, or holdout conditions;
- preferred optimization strategy, trial budget, and acceptance thresholds.

**Example**

> Tune an x500 quadrotor on a 5 m circular track at 3 m altitude. Prioritize tracking accuracy, include moderate sensor noise, and keep the experiment within 180 trials.

### 3.2 Review the extracted intent

The assistant responds with:

- a concise experiment summary;
- fields it can fill directly from the request;
- missing or ambiguous decisions that still need confirmation;
- a button that opens the reviewable experiment draft.

The assistant may update a draft, but it cannot create a running job or start simulation by itself. The user must review the five-step configuration and explicitly create the experiment.

### 3.3 Voice and attachments

Use the microphone button to dictate a request. The plus menu can open the manual workflow or attach supporting JSON, text, CSV, log, and image files. Attachments provide context to the assistant; they do not bypass field validation.

## 4. Complete the five-step experiment

The manual workflow gives direct control over every field. Each stage validates its own inputs and records the current position, so reopening a draft returns to the same experiment and stage.

![Flight Setup](https://getdronedream.com/docs/en/flight-setup.png)

### 4.1 Flight Setup

Choose the experience level, PX4 version, airframe, Gazebo model, world, rendering mode, objective profile, objective weights, and flight track. Use a predefined route for common studies or choose custom waypoints when exact coordinates are required.

### 4.2 Parameters

Select only the controller parameters that should change. Every selected row contains:

- the PX4 parameter name and readable full name;
- the baseline value;
- the search minimum;
- the search maximum;
- any related or coupled parameter.

Keep the search interval physically meaningful and narrow enough to support the available trial budget. Selecting more parameters expands the search space and usually requires more evidence.

### 4.3 Scenarios

Define nominal search, stressed search, nominal holdout, and combined-stress holdout cases. Configure wind, sensor noise, random seeds, payload, battery, signal dropout, gusts, and obstacle settings as required.

Use search cases to guide optimization and holdout cases to evaluate whether a candidate generalizes beyond the conditions that produced it.

### 4.4 Constraints and budget

Select the simulator backend and optimization strategy, then set:

- maximum iterations;
- trials per candidate;
- maximum total trials;
- target RMSE and target maximum error;
- minimum pass rate.

The strategy card explains the selected algorithm as a vertical process. The model provider and API key are configured once in **Settings**, not inside the experiment.

### 4.5 Review

The review page summarizes the preceding four stages. Inspect the vehicle, search objective, scenarios, budget, and selected PX4 parameter ranges before choosing **Create Experiment**.

Click **Selected PX4 parameters** to inspect the complete list when more parameters are selected than can fit on one line.

## 5. Edit a custom flight track

The custom track editor combines a plot with an editable coordinate table. The plot and table remain aligned at equal height, while each table row exposes the full X, Y, and Z values.

### 5.1 Change the view

Use the control in the plot’s upper-right corner to switch among XY, XZ, YZ, and 3D views. The 3D ground grid preserves equal real-world units on both axes; expanding a route adds square cells rather than stretching the existing grid.

### 5.2 Edit points precisely

- Select a row to highlight the corresponding waypoint.
- Edit X, Y, or Z directly in the table.
- Add a waypoint with the plus button.
- Undo the latest supported change with the undo button.
- Delete the selected point or use the row action for a specific point.

### 5.3 Import or export JSON

Use the import/export button above the table to exchange the current coordinate list with an external path-generation tool. Validate imported values before leaving the editor.

## 6. Review history and evidence

Dashboard and Run History summarize experiments without hiding failed or cancelled runs. Filters can narrow the list by status, track type, objective, optimization strategy, and date.

![Dashboard](https://getdronedream.com/docs/en/dashboard.png)

For each completed experiment, keep three evidence layers together:

- **Configuration** — vehicle, firmware, route, parameter ranges, constraints, strategy, and budget.
- **Execution** — scenario identity, random seeds, runtime manifest, process logs, and simulation artifacts.
- **Decision** — feasibility, tracking error, overshoot, settling time, robustness, and Pareto trade-offs.

Compare only experiments whose scenario and metric contracts are compatible. A lower score is not meaningful when the underlying validation conditions differ.

## 7. Accounts, data, and safety

### 7.1 Account isolation

DroneDream uses Supabase identity and row-level security policies for cloud account isolation. Public community topics are intentionally shared, while account settings and user-owned cloud records remain scoped to their owner.

### 7.2 Local drafts

Experiment drafts are preserved while the application remains open and can be reopened from the sidebar. If a user closes the application with an unfinished draft, DroneDream warns that the draft will be discarded after exit.

### 7.3 Model credentials

The provider, model name, and compatible base URL may be stored on the device. The API key remains only in the current application session and is not written into local storage or experiment drafts.

### 7.4 Before hardware flight

Treat a successful optimization run as evidence for further validation, not as deployment approval. Reproduce the winning configuration in an independent SITL run, inspect the full logs and failure cases, confirm hardware-specific limits, and follow the aircraft operator’s safety process.

---

**Website:** [getdronedream.com](https://getdronedream.com)<br>
**Version:** 1.0.0<br>
**Author:** Chi Zhang
