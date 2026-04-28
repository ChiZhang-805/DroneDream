import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { SectionCard } from "../components/SectionCard";
import { Alert } from "../components/Alert";
import { apiClient, ApiClientError } from "../api/client";
import {
  OBJECTIVE_PROFILES,
  OPTIMIZER_STRATEGIES,
  SENSOR_NOISE_LEVELS,
  SIMULATOR_BACKENDS,
  TRACK_TYPES,
} from "../types/api";
import type {
  JobCreateRequest,
  ObjectiveProfile,
  OptimizerStrategy,
  SensorNoiseLevel,
  SimulatorBackend,
  TrackType,
} from "../types/api";

interface FormState {
  track_type: TrackType;
  reference_track_json: string;
  start_x: string;
  start_y: string;
  altitude_m: string;
  wind_north: string;
  wind_east: string;
  wind_south: string;
  wind_west: string;
  sensor_noise_level: SensorNoiseLevel;
  objective_profile: ObjectiveProfile;
  // Phase 8 — execution backend & auto-tuning
  simulator_backend: SimulatorBackend;
  optimizer_strategy: OptimizerStrategy;
  max_iterations: string;
  trials_per_candidate: string;
  target_rmse: string;
  target_max_error: string;
  min_pass_rate: string;
  openai_api_key: string;
  openai_model: string;
  advanced_enabled: boolean;
  gust_enabled: boolean;
  gust_magnitude_mps: string;
  gust_direction_deg: string;
  gust_period_s: string;
  gps_noise_m: string;
  baro_noise_m: string;
  imu_noise_scale: string;
  dropout_rate: string;
  battery_initial_percent: string;
  battery_voltage_sag: boolean;
  mass_payload_kg: string;
  obstacles_json: string;
}

const DEFAULTS: FormState = {
  track_type: "circle",
  reference_track_json: "",
  start_x: "0",
  start_y: "0",
  altitude_m: "3.0",
  wind_north: "0",
  wind_east: "0",
  wind_south: "0",
  wind_west: "0",
  sensor_noise_level: "medium",
  objective_profile: "robust",
  simulator_backend: "mock",
  optimizer_strategy: "gpt",
  max_iterations: "20",
  trials_per_candidate: "3",
  target_rmse: "0.5",
  target_max_error: "",
  min_pass_rate: "0.8",
  openai_api_key: "",
  openai_model: "",
  advanced_enabled: false,
  gust_enabled: false,
  gust_magnitude_mps: "0",
  gust_direction_deg: "0",
  gust_period_s: "10",
  gps_noise_m: "0",
  baro_noise_m: "0",
  imu_noise_scale: "1",
  dropout_rate: "0",
  battery_initial_percent: "100",
  battery_voltage_sag: false,
  mass_payload_kg: "",
  obstacles_json: "[]",
};

type FieldErrors = Partial<Record<keyof FormState, string>>;

const CUSTOM_REFERENCE_TRACK_EXAMPLE = `[
  {"x": 0, "y": 0, "z": 3},
  {"x": 5, "y": 0, "z": 3},
  {"x": 5, "y": 5, "z": 3}
]`;

function parseNumber(raw: string): number | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function parseReferenceTrackInput(raw: string): {
  points: JobCreateRequest["reference_track"];
  error: string | null;
} {
  if (raw.trim() === "") {
    return { points: null, error: null };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { points: null, error: "Must be valid JSON array" };
  }
  if (!Array.isArray(parsed)) {
    return { points: null, error: "Must be JSON array" };
  }
  const points: NonNullable<JobCreateRequest["reference_track"]> = [];
  for (let i = 0; i < parsed.length; i += 1) {
    const point = parsed[i];
    if (!point || typeof point !== "object") {
      return { points: null, error: `Point #${i + 1} must be an object` };
    }
    const x = Number((point as { x?: unknown }).x);
    const y = Number((point as { y?: unknown }).y);
    const zRaw = (point as { z?: unknown }).z;
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return { points: null, error: `Point #${i + 1} requires numeric x/y` };
    }
    if (zRaw !== undefined && zRaw !== null && !Number.isFinite(Number(zRaw))) {
      return { points: null, error: `Point #${i + 1} z must be numeric when provided` };
    }
    points.push({
      x,
      y,
      z: zRaw === undefined ? null : (zRaw === null ? null : Number(zRaw)),
    });
  }
  return { points, error: null };
}

function validate(form: FormState): FieldErrors {
  const errors: FieldErrors = {};

  if (!TRACK_TYPES.includes(form.track_type)) {
    errors.track_type = "Select a valid track type";
  }
  const parsedTrack = parseReferenceTrackInput(form.reference_track_json);
  if (parsedTrack.error) {
    errors.reference_track_json = parsedTrack.error;
  } else if (form.track_type === "custom") {
    if (!parsedTrack.points || parsedTrack.points.length < 2) {
      errors.reference_track_json = "Custom track requires at least 2 points";
    }
  }
  if (!SENSOR_NOISE_LEVELS.includes(form.sensor_noise_level)) {
    errors.sensor_noise_level = "Select a valid sensor noise level";
  }
  if (!OBJECTIVE_PROFILES.includes(form.objective_profile)) {
    errors.objective_profile = "Select a valid objective profile";
  }

  const sx = parseNumber(form.start_x);
  if (sx === null) errors.start_x = "Required numeric value";
  const sy = parseNumber(form.start_y);
  if (sy === null) errors.start_y = "Required numeric value";

  const alt = parseNumber(form.altitude_m);
  if (alt === null) {
    errors.altitude_m = "Required numeric value";
  } else if (alt < 1.0 || alt > 20.0) {
    errors.altitude_m = "Must be between 1.0 and 20.0";
  }

  (["wind_north", "wind_east", "wind_south", "wind_west"] as const).forEach(
    (k) => {
      const v = parseNumber(form[k]);
      if (v === null) {
        errors[k] = "Required numeric value";
      } else if (v < -10 || v > 10) {
        errors[k] = "Must be between -10 and 10";
      }
    },
  );

  if (!SIMULATOR_BACKENDS.includes(form.simulator_backend)) {
    errors.simulator_backend = "Select a valid simulator backend";
  }
  if (!OPTIMIZER_STRATEGIES.includes(form.optimizer_strategy)) {
    errors.optimizer_strategy = "Select a valid optimizer strategy";
  }
  const maxIter = parseNumber(form.max_iterations);
  if (
    maxIter === null ||
    !Number.isInteger(maxIter) ||
    maxIter < 1 ||
    maxIter > 20
  ) {
    errors.max_iterations = "Integer between 1 and 20";
  }
  const trials = parseNumber(form.trials_per_candidate);
  if (
    trials === null ||
    !Number.isInteger(trials) ||
    trials < 1 ||
    trials > 10
  ) {
    errors.trials_per_candidate = "Integer between 1 and 10";
  }
  if (form.target_rmse.trim() !== "") {
    const v = parseNumber(form.target_rmse);
    if (v === null || v < 0 || v > 100) {
      errors.target_rmse = "Must be between 0 and 100";
    }
  }
  if (form.target_max_error.trim() !== "") {
    const v = parseNumber(form.target_max_error);
    if (v === null || v < 0 || v > 100) {
      errors.target_max_error = "Must be between 0 and 100";
    }
  }
  const pr = parseNumber(form.min_pass_rate);
  if (pr === null || pr < 0 || pr > 1) {
    errors.min_pass_rate = "Must be between 0 and 1";
  }
  if (
    form.optimizer_strategy === "gpt" &&
    form.openai_api_key.trim() === ""
  ) {
    errors.openai_api_key = "API key required when strategy is gpt";
  }
  if (form.advanced_enabled) {
    const gps = parseNumber(form.gps_noise_m);
    if (gps === null || gps < 0 || gps > 100) {
      errors.gps_noise_m = "Must be between 0 and 100";
    }
    const baro = parseNumber(form.baro_noise_m);
    if (baro === null || baro < 0 || baro > 100) {
      errors.baro_noise_m = "Must be between 0 and 100";
    }
    const imu = parseNumber(form.imu_noise_scale);
    if (imu === null || imu < 0 || imu > 100) {
      errors.imu_noise_scale = "Must be between 0 and 100";
    }
    const dropout = parseNumber(form.dropout_rate);
    if (dropout === null || dropout < 0 || dropout > 1) {
      errors.dropout_rate = "Must be between 0 and 1";
    }
    const battery = parseNumber(form.battery_initial_percent);
    if (battery === null || battery < 0 || battery > 100) {
      errors.battery_initial_percent = "Must be between 0 and 100";
    }
    if (form.mass_payload_kg.trim() !== "") {
      const payloadMass = parseNumber(form.mass_payload_kg);
      if (payloadMass === null || payloadMass < 0 || payloadMass > 20) {
        errors.mass_payload_kg = "Must be between 0 and 20";
      }
    }
    if (form.gust_enabled) {
      const magnitude = parseNumber(form.gust_magnitude_mps);
      const direction = parseNumber(form.gust_direction_deg);
      const period = parseNumber(form.gust_period_s);
      if (magnitude === null || magnitude < 0 || magnitude > 30) errors.gust_magnitude_mps = "Must be 0-30";
      if (direction === null || direction < 0 || direction >= 360) errors.gust_direction_deg = "Must be 0-<360";
      if (period === null || period <= 0 || period > 300) errors.gust_period_s = "Must be >0 and <=300";
    }
    try {
      const parsed = JSON.parse(form.obstacles_json);
      if (!Array.isArray(parsed)) errors.obstacles_json = "Must be JSON array";
    } catch {
      errors.obstacles_json = "Must be valid JSON array";
    }
  }

  return errors;
}

function formToRequest(form: FormState): JobCreateRequest {
  const parsedTrack = parseReferenceTrackInput(form.reference_track_json);
  const req: JobCreateRequest = {
    track_type: form.track_type,
    reference_track: parsedTrack.points ?? null,
    start_point: {
      x: Number(form.start_x),
      y: Number(form.start_y),
    },
    altitude_m: Number(form.altitude_m),
    wind: {
      north: Number(form.wind_north),
      east: Number(form.wind_east),
      south: Number(form.wind_south),
      west: Number(form.wind_west),
    },
    sensor_noise_level: form.sensor_noise_level,
    objective_profile: form.objective_profile,
    simulator_backend: form.simulator_backend,
    optimizer_strategy: form.optimizer_strategy,
    max_iterations: Number(form.max_iterations),
    trials_per_candidate: Number(form.trials_per_candidate),
    acceptance_criteria: {
      target_rmse:
        form.target_rmse.trim() === "" ? null : Number(form.target_rmse),
      target_max_error:
        form.target_max_error.trim() === ""
          ? null
          : Number(form.target_max_error),
      min_pass_rate: Number(form.min_pass_rate),
    },
  };
  if (form.optimizer_strategy === "gpt") {
    req.openai = {
      api_key: form.openai_api_key.trim(),
      model: form.openai_model.trim() === "" ? null : form.openai_model.trim(),
    };
  }
  if (form.advanced_enabled) {
    const obstacles = JSON.parse(form.obstacles_json) as unknown[];
    req.advanced_scenario_config = {
      wind_gusts: {
        enabled: form.gust_enabled,
        magnitude_mps: Number(form.gust_magnitude_mps),
        direction_deg: Number(form.gust_direction_deg),
        period_s: Number(form.gust_period_s),
      },
      obstacles: obstacles as [],
      sensor_degradation: {
        gps_noise_m: Number(form.gps_noise_m),
        baro_noise_m: Number(form.baro_noise_m),
        imu_noise_scale: Number(form.imu_noise_scale),
        dropout_rate: Number(form.dropout_rate),
      },
      battery: {
        initial_percent: Number(form.battery_initial_percent),
        voltage_sag: form.battery_voltage_sag,
        mass_payload_kg:
          form.mass_payload_kg.trim() === "" ? null : Number(form.mass_payload_kg),
      },
    };
  }
  return req;
}

export function NewJob() {
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(DEFAULTS);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showAdvancedScenario, setShowAdvancedScenario] = useState(false);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleTextChange(key: keyof FormState) {
    return (e: ChangeEvent<HTMLInputElement>) => update(key, e.target.value);
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitError(null);
    const nextErrors = validate(form);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      return;
    }
    setSubmitting(true);
    try {
      const created = await apiClient.createJob(formToRequest(form));
      navigate(`/jobs/${created.id}`, { replace: false });
    } catch (err) {
      if (err instanceof ApiClientError) {
        setSubmitError(err.message);
      } else {
        setSubmitError("Failed to submit job. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleReset() {
    setForm(DEFAULTS);
    setErrors({});
    setSubmitError(null);
  }

  return (
    <section className="stack-md">
      <header className="page-header">
        <div>
          <h1>New Job</h1>
          <p className="page-header-subtitle">
            Configure the track, environment, and optimization objective for a
            new run. The job is persisted by the backend and picked up by the
            worker.
          </p>
        </div>
      </header>

      <form onSubmit={handleSubmit} noValidate>
        {submitError ? (
          <Alert tone="danger" title="Submission failed">
            {submitError}
          </Alert>
        ) : null}

        <SectionCard
          title="Track configuration"
          description="Select the flight track and start position."
        >
          <div className="form-grid">
            <Field
              label="Track Type"
              required
              error={errors.track_type}
              htmlFor="track_type"
            >
              <select
                id="track_type"
                value={form.track_type}
                onChange={(e) => {
                  const nextTrack = e.target.value as TrackType;
                  update("track_type", nextTrack);
                  if (
                    nextTrack === "custom" &&
                    form.reference_track_json.trim() === ""
                  ) {
                    update("reference_track_json", CUSTOM_REFERENCE_TRACK_EXAMPLE);
                  }
                }}
              >
                {TRACK_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Start X"
              required
              error={errors.start_x}
              htmlFor="start_x"
            >
              <input
                id="start_x"
                type="number"
                step="any"
                value={form.start_x}
                onChange={handleTextChange("start_x")}
              />
            </Field>
            <Field
              label="Start Y"
              required
              error={errors.start_y}
              htmlFor="start_y"
            >
              <input
                id="start_y"
                type="number"
                step="any"
                value={form.start_y}
                onChange={handleTextChange("start_y")}
              />
            </Field>
            <Field
              label="Altitude (m)"
              required
              error={errors.altitude_m}
              htmlFor="altitude_m"
              hint="Allowed range: 1.0 – 20.0"
            >
              <input
                id="altitude_m"
                type="number"
                step="0.1"
                min={1}
                max={20}
                value={form.altitude_m}
                onChange={handleTextChange("altitude_m")}
              />
            </Field>
            {form.track_type === "custom" ? (
              <Field
                label="Reference track (JSON)"
                required
                error={errors.reference_track_json}
                htmlFor="reference_track_json"
                hint="Provide a JSON array of waypoint objects."
              >
                <textarea
                  id="reference_track_json"
                  rows={6}
                  value={form.reference_track_json}
                  onChange={(e) => update("reference_track_json", e.target.value)}
                />
              </Field>
            ) : null}
          </div>
        </SectionCard>
        <SectionCard
          title="Advanced scenario"
          description="Optional extended PX4/Gazebo scenario parameters."
        >
          <button type="button" className="btn btn-ghost" onClick={() => setShowAdvancedScenario((v) => !v)}>
            {showAdvancedScenario ? "Hide" : "Show"} Advanced scenario
          </button>
          {showAdvancedScenario ? (
            <div className="form-grid">
              <Field label="Enable advanced scenario" htmlFor="advanced_enabled">
                <input id="advanced_enabled" type="checkbox" checked={form.advanced_enabled} onChange={(e) => update("advanced_enabled", e.target.checked)} />
              </Field>
              <Field label="Enable gust" htmlFor="gust_enabled">
                <input id="gust_enabled" type="checkbox" checked={form.gust_enabled} onChange={(e) => update("gust_enabled", e.target.checked)} />
              </Field>
              <Field label="Gust magnitude (m/s)" htmlFor="gust_magnitude_mps" error={errors.gust_magnitude_mps}>
                <input id="gust_magnitude_mps" type="number" step="0.1" value={form.gust_magnitude_mps} onChange={handleTextChange("gust_magnitude_mps")} />
              </Field>
              <Field label="Gust direction (deg)" htmlFor="gust_direction_deg" error={errors.gust_direction_deg}>
                <input id="gust_direction_deg" type="number" step="0.1" value={form.gust_direction_deg} onChange={handleTextChange("gust_direction_deg")} />
              </Field>
              <Field label="Gust period (s)" htmlFor="gust_period_s" error={errors.gust_period_s}>
                <input id="gust_period_s" type="number" step="0.1" value={form.gust_period_s} onChange={handleTextChange("gust_period_s")} />
              </Field>
              <Field label="GPS noise (m)" htmlFor="gps_noise_m">
                <input id="gps_noise_m" type="number" step="0.1" value={form.gps_noise_m} onChange={handleTextChange("gps_noise_m")} />
              </Field>
              <Field label="Baro noise (m)" htmlFor="baro_noise_m" error={errors.baro_noise_m}>
                <input id="baro_noise_m" type="number" step="0.1" value={form.baro_noise_m} onChange={handleTextChange("baro_noise_m")} />
              </Field>
              <Field label="IMU noise scale" htmlFor="imu_noise_scale" error={errors.imu_noise_scale}>
                <input id="imu_noise_scale" type="number" step="0.1" value={form.imu_noise_scale} onChange={handleTextChange("imu_noise_scale")} />
              </Field>
              <Field label="Dropout rate" htmlFor="dropout_rate" error={errors.dropout_rate}>
                <input id="dropout_rate" type="number" step="0.01" value={form.dropout_rate} onChange={handleTextChange("dropout_rate")} />
              </Field>
              <Field label="Battery initial percent" htmlFor="battery_initial_percent" error={errors.battery_initial_percent}>
                <input id="battery_initial_percent" type="number" step="0.1" value={form.battery_initial_percent} onChange={handleTextChange("battery_initial_percent")} />
              </Field>
              <Field label="Battery voltage sag" htmlFor="battery_voltage_sag">
                <input id="battery_voltage_sag" type="checkbox" checked={form.battery_voltage_sag} onChange={(e) => update("battery_voltage_sag", e.target.checked)} />
              </Field>
              <Field label="Payload mass (kg)" htmlFor="mass_payload_kg" error={errors.mass_payload_kg}>
                <input id="mass_payload_kg" type="number" step="0.1" value={form.mass_payload_kg} onChange={handleTextChange("mass_payload_kg")} />
              </Field>
              <Field label="Obstacles JSON" htmlFor="obstacles_json" error={errors.obstacles_json}>
                <textarea id="obstacles_json" rows={5} value={form.obstacles_json} onChange={(e) => update("obstacles_json", e.target.value)} />
              </Field>
            </div>
          ) : null}
        </SectionCard>

        <SectionCard
          title="Environment configuration"
          description="Wind components in m/s. Sensor noise level affects simulated telemetry."
        >
          <div className="form-grid">
            <Field
              label="Wind North"
              required
              error={errors.wind_north}
              htmlFor="wind_north"
              hint="Allowed range: -10 – 10"
            >
              <input
                id="wind_north"
                type="number"
                step="any"
                min={-10}
                max={10}
                value={form.wind_north}
                onChange={handleTextChange("wind_north")}
              />
            </Field>
            <Field
              label="Wind East"
              required
              error={errors.wind_east}
              htmlFor="wind_east"
              hint="Allowed range: -10 – 10"
            >
              <input
                id="wind_east"
                type="number"
                step="any"
                min={-10}
                max={10}
                value={form.wind_east}
                onChange={handleTextChange("wind_east")}
              />
            </Field>
            <Field
              label="Wind South"
              required
              error={errors.wind_south}
              htmlFor="wind_south"
              hint="Allowed range: -10 – 10"
            >
              <input
                id="wind_south"
                type="number"
                step="any"
                min={-10}
                max={10}
                value={form.wind_south}
                onChange={handleTextChange("wind_south")}
              />
            </Field>
            <Field
              label="Wind West"
              required
              error={errors.wind_west}
              htmlFor="wind_west"
              hint="Allowed range: -10 – 10"
            >
              <input
                id="wind_west"
                type="number"
                step="any"
                min={-10}
                max={10}
                value={form.wind_west}
                onChange={handleTextChange("wind_west")}
              />
            </Field>
            <Field
              label="Sensor Noise Level"
              required
              error={errors.sensor_noise_level}
              htmlFor="sensor_noise_level"
            >
              <select
                id="sensor_noise_level"
                value={form.sensor_noise_level}
                onChange={(e) =>
                  update(
                    "sensor_noise_level",
                    e.target.value as SensorNoiseLevel,
                  )
                }
              >
                {SENSOR_NOISE_LEVELS.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </SectionCard>

        <SectionCard
          title="Optimization objective"
          description="Select the objective profile that drives candidate scoring."
        >
          <div className="form-grid">
            <Field
              label="Objective Profile"
              required
              error={errors.objective_profile}
              htmlFor="objective_profile"
            >
              <select
                id="objective_profile"
                value={form.objective_profile}
                onChange={(e) =>
                  update("objective_profile", e.target.value as ObjectiveProfile)
                }
              >
                {OBJECTIVE_PROFILES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </SectionCard>

        <SectionCard
          title="Execution Backend & Auto-Tuning"
          description="Pick the simulator backend and the parameter-tuning strategy. The OpenAI key is used server-side only and is never returned by the API."
        >
          <div className="form-grid">
            <Field
              label="Simulator Backend"
              required
              error={errors.simulator_backend}
              htmlFor="simulator_backend"
              hint="mock uses the built-in deterministic simulator. real_cli shells out to the external drone simulator configured on the worker."
            >
              <select
                id="simulator_backend"
                value={form.simulator_backend}
                onChange={(e) =>
                  update(
                    "simulator_backend",
                    e.target.value as SimulatorBackend,
                  )
                }
              >
                {SIMULATOR_BACKENDS.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Optimizer Strategy"
              required
              error={errors.optimizer_strategy}
              htmlFor="optimizer_strategy"
              hint="heuristic uses deterministic perturbations. cma_es runs a dependency-free adaptive search. gpt asks OpenAI to propose next candidates."
            >
              <select
                id="optimizer_strategy"
                value={form.optimizer_strategy}
                onChange={(e) =>
                  update(
                    "optimizer_strategy",
                    e.target.value as OptimizerStrategy,
                  )
                }
              >
                {OPTIMIZER_STRATEGIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Max Iterations"
              required
              error={errors.max_iterations}
              htmlFor="max_iterations"
              hint="Integer 1–20. Caps optimizer generations after baseline."
            >
              <input
                id="max_iterations"
                type="number"
                min={1}
                max={20}
                step={1}
                value={form.max_iterations}
                onChange={handleTextChange("max_iterations")}
              />
            </Field>
            <Field
              label="Trials per Candidate"
              required
              error={errors.trials_per_candidate}
              htmlFor="trials_per_candidate"
              hint="Integer 1–10. Each candidate is scored over this many scenarios."
            >
              <input
                id="trials_per_candidate"
                type="number"
                min={1}
                max={10}
                step={1}
                value={form.trials_per_candidate}
                onChange={handleTextChange("trials_per_candidate")}
              />
            </Field>
            <Field
              label="Target RMSE"
              error={errors.target_rmse}
              htmlFor="target_rmse"
              hint="Leave blank to skip this threshold."
            >
              <input
                id="target_rmse"
                type="number"
                step="any"
                value={form.target_rmse}
                onChange={handleTextChange("target_rmse")}
              />
            </Field>
            <Field
              label="Target Max Error"
              error={errors.target_max_error}
              htmlFor="target_max_error"
              hint="Leave blank to skip this threshold."
            >
              <input
                id="target_max_error"
                type="number"
                step="any"
                value={form.target_max_error}
                onChange={handleTextChange("target_max_error")}
              />
            </Field>
            <Field
              label="Min Pass Rate"
              required
              error={errors.min_pass_rate}
              htmlFor="min_pass_rate"
              hint="Fraction of trials that must pass (pass_flag=true) for a candidate to be accepted."
            >
              <input
                id="min_pass_rate"
                type="number"
                step="any"
                min={0}
                max={1}
                value={form.min_pass_rate}
                onChange={handleTextChange("min_pass_rate")}
              />
            </Field>
            {form.optimizer_strategy === "gpt" ? (
              <>
                <Field
                  label="OpenAI API Key"
                  required
                  error={errors.openai_api_key}
                  htmlFor="openai_api_key"
                  hint="Used server-side only. Stored encrypted for the duration of the job and wiped on completion."
                >
                  <input
                    id="openai_api_key"
                    type="password"
                    autoComplete="off"
                    value={form.openai_api_key}
                    onChange={handleTextChange("openai_api_key")}
                  />
                </Field>
                <Field
                  label="OpenAI Model"
                  error={errors.openai_model}
                  htmlFor="openai_model"
                  hint="Optional. Leave blank to use the backend default."
                >
                  <input
                    id="openai_model"
                    type="text"
                    value={form.openai_model}
                    onChange={handleTextChange("openai_model")}
                  />
                </Field>
              </>
            ) : null}
          </div>
        </SectionCard>

        <div className="form-actions">
          <button
            className="btn btn-primary"
            type="submit"
            disabled={submitting}
          >
            {submitting ? "Submitting…" : "Create Job"}
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            onClick={handleReset}
            disabled={submitting}
          >
            Reset to defaults
          </button>
          <span className="form-hint">
            Submission hits POST /api/v1/jobs and redirects to the live Job
            Detail page.
          </span>
        </div>
      </form>
    </section>
  );
}

interface FieldProps {
  label: string;
  htmlFor: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}

function Field({ label, htmlFor, required, error, hint, children }: FieldProps) {
  return (
    <div className={`form-field${error ? " form-field-error" : ""}`}>
      <label
        htmlFor={htmlFor}
        className={required ? "form-field-required" : undefined}
      >
        {label}
      </label>
      {children}
      {error ? (
        <span className="form-error" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span className="form-hint">{hint}</span>
      ) : null}
    </div>
  );
}
