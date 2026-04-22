import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { SectionCard } from "../components/SectionCard";
import { Alert } from "../components/Alert";
import { apiClient, ApiClientError } from "../api/client";
import {
  OBJECTIVE_PROFILES,
  SENSOR_NOISE_LEVELS,
  TRACK_TYPES,
} from "../types/api";
import type {
  JobCreateRequest,
  ObjectiveProfile,
  SensorNoiseLevel,
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

  return errors;
}

function formToRequest(form: FormState): JobCreateRequest {
  return {
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
  };
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
            new run. Submission goes through the mock API in Phase 1.
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
            Phase 1: submission uses the mock client and routes to a mock job
            detail page.
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
