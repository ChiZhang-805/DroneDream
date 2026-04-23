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
}

const DEFAULTS: FormState = {
  track_type: "circle",
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
  optimizer_strategy: "heuristic",
  max_iterations: "5",
  trials_per_candidate: "3",
  target_rmse: "0.5",
  target_max_error: "",
  min_pass_rate: "0.8",
  openai_api_key: "",
  openai_model: "",
};

type FieldErrors = Partial<Record<keyof FormState, string>>;

function parseNumber(raw: string): number | null {
  if (raw.trim() === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

function validate(form: FormState): FieldErrors {
  const errors: FieldErrors = {};

  if (!TRACK_TYPES.includes(form.track_type)) {
    errors.track_type = "Select a valid track type";
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

  return errors;
}

function formToRequest(form: FormState): JobCreateRequest {
  const req: JobCreateRequest = {
    track_type: form.track_type,
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
  return req;
}

export function NewJob() {
  const navigate = useNavigate();
  const [form, setForm] = useState<FormState>(DEFAULTS);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
                onChange={(e) =>
                  update("track_type", e.target.value as TrackType)
                }
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
          </div>
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
              hint="heuristic uses the deterministic optimizer. gpt asks OpenAI to propose the next candidates."
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
              hint="Fraction of trials that must complete for a candidate to be accepted."
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
