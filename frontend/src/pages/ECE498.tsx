import { useMemo, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";
import { Link } from "react-router-dom";

import { apiClient } from "../api/client";
import { Alert } from "../components/Alert";
import { SectionCard } from "../components/SectionCard";
import { DEFAULT_TRACK_GEOMETRY, generateReferenceTrack } from "../utils/referenceTrack";
import type {
  CandidateSourceType,
  Job,
  JobCreateRequest,
  JobStatus,
  OptimizationOutcome,
  SimulatorBackend,
  TrackType,
  Trial,
} from "../types/api";

export type Ece498Mode = "baseline_no_tool" | "tool_augmented" | "tool_refinement";
export type Ece498CandidateRole =
  | "baseline"
  | "tool_turn_1"
  | "refinement_turn_2"
  | "refinement_turn_3"
  | "other";

export interface Ece498CandidateTurn {
  mode: Ece498Mode;
  candidateId: string;
  label: string | null;
  sourceType: CandidateSourceType | null;
  generationIndex: number;
  role: Ece498CandidateRole;
  trialCount: number;
  completedTrialCount: number;
  failedTrialCount: number;
  passingTrialCount: number;
  passRate: number;
  meanRmse: number | null;
  meanMaxError: number | null;
  meanScore: number | null;
  pass: boolean;
}

export interface Ece498RunResult {
  mode: Ece498Mode;
  jobId: string;
  jobName: string | null;
  jobStatus: JobStatus;
  pass: boolean;
  reason: string;
  optimizationOutcome: OptimizationOutcome | null;
  bestCandidateId: string | null;
  rmse: number | null;
  maxError: number | null;
  passRate: number | null;
  score: number | null;
  completedTrials: number;
  failedTrials: number;
  totalTrials: number;
  candidateTurns: Ece498CandidateTurn[];
}

export interface Ece498FormState {
  display_name: string;
  track_type: TrackType;
  reference_track_json: string;
  baseline_kp_xy: string;
  baseline_kd_xy: string;
  baseline_ki_xy: string;
  baseline_vel_limit: string;
  baseline_accel_limit: string;
  baseline_disturbance_rejection: string;
  circle_radius_m: string;
  u_turn_straight_length_m: string;
  u_turn_turn_radius_m: string;
  lemniscate_scale_m: string;
  start_x: string;
  start_y: string;
  altitude_m: string;
  wind_north: string;
  wind_east: string;
  wind_south: string;
  wind_west: string;
  sensor_noise_level: "low" | "medium" | "high";
  objective_profile: "stable" | "fast" | "smooth" | "robust" | "custom";
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
  target_rmse: string;
  target_max_error: string;
  min_pass_rate: string;
  simulator_backend: SimulatorBackend;
}

const DEFAULT_FORM: Ece498FormState = {
  display_name: "",
  track_type: "circle",
  reference_track_json: "",
  baseline_kp_xy: "1",
  baseline_kd_xy: "0.2",
  baseline_ki_xy: "0.05",
  baseline_vel_limit: "5",
  baseline_accel_limit: "4",
  baseline_disturbance_rejection: "0.5",
  circle_radius_m: "5",
  u_turn_straight_length_m: "10",
  u_turn_turn_radius_m: "3",
  lemniscate_scale_m: "4",
  start_x: "0",
  start_y: "0",
  altitude_m: "3",
  wind_north: "0",
  wind_east: "0",
  wind_south: "0",
  wind_west: "0",
  sensor_noise_level: "medium",
  objective_profile: "robust",
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
  target_rmse: "0.5",
  target_max_error: "",
  min_pass_rate: "0.8",
  simulator_backend: "mock",
};

function n(v: string | undefined | null): number | null {
  if (!v || v.trim() === "") return null;
  const x = Number(v);
  return Number.isFinite(x) ? x : null;
}
const OBSTACLES_JSON_EXAMPLE = `[
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
]`;

function boolToYesNo(value: boolean): "yes" | "no" {
  return value ? "yes" : "no";
}

function yesNoToBool(value: string): boolean {
  return value === "yes";
}


export type Ece498FieldErrors = Partial<Record<keyof Ece498FormState, string>>;

function formatMode(mode: Ece498Mode): string {
  switch (mode) {
    case "baseline_no_tool":
      return "Baseline (No Tool)";
    case "tool_augmented":
      return "Tool-Augmented (CMA-ES)";
    case "tool_refinement":
      return "Tool + Refinement (CMA-ES Loop)";
  }
}

function formatCandidateRole(role: Ece498CandidateRole): string {
  switch (role) {
    case "baseline":
      return "Baseline";
    case "tool_turn_1":
      return "Tool Turn 1";
    case "refinement_turn_2":
      return "Refinement Turn 2";
    case "refinement_turn_3":
      return "Refinement Turn 3";
    default:
      return "Other";
  }
}

function validateEce498Form(form: Ece498FormState): Ece498FieldErrors {
  const errors: Ece498FieldErrors = {};
  const inRange = (k: keyof Ece498FormState, min: number, max: number, label: string) => {
    const val = Number(form[k]);
    if (!Number.isFinite(val) || val < min || val > max) {
      errors[k] = `${label} must be between ${min} and ${max}.`;
    }
  };
  inRange("baseline_kp_xy", 0.3, 2.5, "kp_xy");
  inRange("baseline_kd_xy", 0.05, 0.8, "kd_xy");
  inRange("baseline_ki_xy", 0, 0.25, "ki_xy");
  inRange("baseline_vel_limit", 2, 10, "vel_limit");
  inRange("baseline_accel_limit", 2, 8, "accel_limit");
  inRange("baseline_disturbance_rejection", 0, 1, "disturbance_rejection");
  if (form.track_type === "circle") inRange("circle_radius_m", 0.000001, 100, "Circle radius");
  if (form.track_type === "u_turn") {
    inRange("u_turn_straight_length_m", 0.000001, 200, "U-turn straight length");
    inRange("u_turn_turn_radius_m", 0.000001, 100, "U-turn radius");
  }
  if (form.track_type === "lemniscate") inRange("lemniscate_scale_m", 0.000001, 100, "Figure-eight scale");
  inRange("wind_north", -10, 10, "Wind north");
  inRange("wind_east", -10, 10, "Wind east");
  inRange("wind_south", -10, 10, "Wind south");
  inRange("wind_west", -10, 10, "Wind west");
  if (!["low", "medium", "high"].includes(form.sensor_noise_level)) {
    errors.sensor_noise_level = "Sensor noise level must be low, medium, or high.";
  }
  if (form.target_rmse.trim() !== "") inRange("target_rmse", 0, 100, "Target RMSE");
  if (form.target_max_error.trim() !== "") inRange("target_max_error", 0, 100, "Target max error");
  inRange("min_pass_rate", 0, 1, "Min pass rate");
  if (form.track_type === "custom") {
    const parsed = parseTrack(form.reference_track_json);
    if (!parsed || parsed.length < 2) errors.reference_track_json = "Custom track JSON must be an array with at least 2 points.";
  }
  if (form.advanced_enabled) {
    inRange("gps_noise_m", 0, 100, "GPS noise");
    inRange("baro_noise_m", 0, 100, "Baro noise");
    inRange("imu_noise_scale", 0, 100, "IMU noise scale");
    inRange("dropout_rate", 0, 1, "Dropout rate");
    inRange("battery_initial_percent", 0, 100, "Battery initial percent");
    if (form.mass_payload_kg.trim() !== "") inRange("mass_payload_kg", 0, 20, "Payload mass");
    try {
      const obstacles = JSON.parse(form.obstacles_json);
      if (!Array.isArray(obstacles)) errors.obstacles_json = "Obstacles JSON must be a JSON array.";
    } catch {
      errors.obstacles_json = "Obstacles JSON must be valid JSON.";
    }
    if (form.gust_enabled) {
      inRange("gust_magnitude_mps", 0, 30, "Gust magnitude");
      const direction = Number(form.gust_direction_deg);
      if (!Number.isFinite(direction) || direction < 0 || direction >= 360) errors.gust_direction_deg = "Gust direction must be between 0 (inclusive) and 360 (exclusive).";
      const period = Number(form.gust_period_s);
      if (!Number.isFinite(period) || period <= 0 || period > 300) errors.gust_period_s = "Gust period must be > 0 and <= 300.";
    }
  }
  return errors;
}

function parseTrack(raw: string) {
  if (!raw.trim()) return null;
  try {
    const data = JSON.parse(raw) as Array<{ x: number; y: number; z?: number }>;
    return Array.isArray(data) ? data : null;
  } catch {
    return null;
  }
}

export function mean(values: number[]): number | null {
  return values.length
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : null;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function roleOfTrial(trial: Trial): Ece498CandidateRole {
  if (trial.candidate_is_baseline || trial.candidate_source_type === "baseline") {
    return "baseline";
  }
  if (trial.candidate_generation_index === 1) return "tool_turn_1";
  if (trial.candidate_generation_index === 2) return "refinement_turn_2";
  if (trial.candidate_generation_index === 3) return "refinement_turn_3";
  return "other";
}

function roleOrder(role: Ece498CandidateRole): number {
  switch (role) {
    case "baseline":
      return 0;
    case "tool_turn_1":
      return 1;
    case "refinement_turn_2":
      return 2;
    case "refinement_turn_3":
      return 3;
    default:
      return 4;
  }
}

export function formatNullableNumber(value: number | null | undefined, digits = 3): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "—";
}

export function formatPercent(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(1)}%`
    : "—";
}

export function passFailLabel(pass: boolean): string {
  return pass ? "Pass" : "Fail";
}

export function buildEce498JobRequest(form: Ece498FormState, mode: Ece498Mode): JobCreateRequest {
  const startX = n(form.start_x) ?? 0;
  const startY = n(form.start_y) ?? 0;
  const altitudeM = n(form.altitude_m) ?? 3;

  return {
    display_name: form.display_name.trim() || null,
    track_type: form.track_type,
    reference_track:
      form.track_type === "custom"
        ? parseTrack(form.reference_track_json)
        : generateReferenceTrack(form.track_type, startX, startY, altitudeM, {
            circle_radius_m: n(form.circle_radius_m) ?? DEFAULT_TRACK_GEOMETRY.circle_radius_m,
            u_turn_straight_length_m:
              n(form.u_turn_straight_length_m) ?? DEFAULT_TRACK_GEOMETRY.u_turn_straight_length_m,
            u_turn_turn_radius_m:
              n(form.u_turn_turn_radius_m) ?? DEFAULT_TRACK_GEOMETRY.u_turn_turn_radius_m,
            lemniscate_scale_m: n(form.lemniscate_scale_m) ?? DEFAULT_TRACK_GEOMETRY.lemniscate_scale_m,
          }),
    baseline_parameters: {
      kp_xy: n(form.baseline_kp_xy) ?? 1,
      kd_xy: n(form.baseline_kd_xy) ?? 0.2,
      ki_xy: n(form.baseline_ki_xy) ?? 0.05,
      vel_limit: n(form.baseline_vel_limit) ?? 5,
      accel_limit: n(form.baseline_accel_limit) ?? 4,
      disturbance_rejection: n(form.baseline_disturbance_rejection) ?? 0.5,
    },
    start_point: { x: startX, y: startY },
    altitude_m: altitudeM,
    wind: {
      north: n(form.wind_north) ?? 0,
      east: n(form.wind_east) ?? 0,
      south: n(form.wind_south) ?? 0,
      west: n(form.wind_west) ?? 0,
    },
    sensor_noise_level: form.sensor_noise_level,
    objective_profile: form.objective_profile,
    advanced_scenario_config: form.advanced_enabled
      ? {
          wind_gusts: {
            enabled: form.gust_enabled,
            magnitude_mps: Number(form.gust_magnitude_mps),
            direction_deg: Number(form.gust_direction_deg),
            period_s: Number(form.gust_period_s),
          },
          obstacles: JSON.parse(form.obstacles_json),
          sensor_degradation: {
            gps_noise_m: Number(form.gps_noise_m),
            baro_noise_m: Number(form.baro_noise_m),
            imu_noise_scale: Number(form.imu_noise_scale),
            dropout_rate: Number(form.dropout_rate),
          },
          battery: {
            initial_percent: Number(form.battery_initial_percent),
            voltage_sag: form.battery_voltage_sag,
            mass_payload_kg: form.mass_payload_kg.trim() === "" ? null : Number(form.mass_payload_kg),
          },
        }
      : null,
    simulator_backend: form.simulator_backend,
    optimizer_strategy: mode === "baseline_no_tool" ? "none" : "cma_es",
    max_iterations: mode === "tool_refinement" ? 3 : 1,
    trials_per_candidate: 3,
    acceptance_criteria: {
      target_rmse: n(form.target_rmse),
      target_max_error: n(form.target_max_error),
      min_pass_rate: n(form.min_pass_rate) ?? 0.8,
    },
  };
}

async function waitForTerminalJob(jobId: string): Promise<Job> {
  const maxPolls = 300;
  for (let i = 0; i < maxPolls; i += 1) {
    const job = await apiClient.getJob(jobId);
    if (["COMPLETED", "FAILED", "CANCELLED"].includes(job.status)) {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  throw new Error(`Timed out waiting for job ${jobId} to finish.`);
}

export function summarizeCandidateTurns(
  mode: Ece498Mode,
  trials: Trial[],
  form: Ece498FormState,
): Ece498CandidateTurn[] {
  const targetRmse = n(form.target_rmse);
  const targetMaxError = n(form.target_max_error);
  const minPassRate = n(form.min_pass_rate) ?? 0.8;
  const byCandidate = new Map<string, Trial[]>();

  for (const trial of trials) {
    const arr = byCandidate.get(trial.candidate_id) ?? [];
    arr.push(trial);
    byCandidate.set(trial.candidate_id, arr);
  }

  const turns = Array.from(byCandidate.entries()).map(([candidateId, candidateTrials]) => {
    const completed = candidateTrials.filter((trial) => trial.status === "COMPLETED");
    const failed = candidateTrials.filter((trial) => trial.status === "FAILED");
    const passing = completed.filter((trial) => trial.metrics?.pass_flag);

    const meanRmse = mean(completed.map((trial) => trial.metrics?.rmse).filter(isFiniteNumber));
    const meanMaxError = mean(completed.map((trial) => trial.metrics?.max_error).filter(isFiniteNumber));
    const meanScore = mean(completed.map((trial) => trial.metrics?.score).filter(isFiniteNumber));
    const passRate = completed.length > 0 ? passing.length / completed.length : 0;

    const first = candidateTrials[0];
    const pass =
      completed.length > 0 &&
      passRate >= minPassRate &&
      (targetRmse == null || (meanRmse != null && meanRmse <= targetRmse)) &&
      (targetMaxError == null || (meanMaxError != null && meanMaxError <= targetMaxError));

    return {
      mode,
      candidateId,
      label: first?.candidate_label ?? null,
      sourceType: first?.candidate_source_type ?? null,
      generationIndex: first?.candidate_generation_index ?? 0,
      role: first ? roleOfTrial(first) : "other",
      trialCount: candidateTrials.length,
      completedTrialCount: completed.length,
      failedTrialCount: failed.length,
      passingTrialCount: passing.length,
      passRate,
      meanRmse,
      meanMaxError,
      meanScore,
      pass,
    };
  });

  return turns.sort((a, b) => {
    const roleDiff = roleOrder(a.role) - roleOrder(b.role);
    if (roleDiff !== 0) return roleDiff;
    const generationDiff = a.generationIndex - b.generationIndex;
    if (generationDiff !== 0) return generationDiff;
    return a.candidateId.localeCompare(b.candidateId);
  });
}

export function summarizeRunResult(
  mode: Ece498Mode,
  job: Job,
  candidateTurns: Ece498CandidateTurn[],
): Ece498RunResult {
  const selectedByBestId =
    job.best_candidate_id != null
      ? candidateTurns.find((candidate) => candidate.candidateId === job.best_candidate_id) ?? null
      : null;
  const baselineCandidate = candidateTurns.find((candidate) => candidate.role === "baseline") ?? null;
  const passingByBestScore = [...candidateTurns]
    .filter((candidate) => candidate.pass && candidate.meanScore != null)
    .sort((a, b) => (a.meanScore ?? Number.POSITIVE_INFINITY) - (b.meanScore ?? Number.POSITIVE_INFINITY))[0] ?? null;
  const lowestScore = [...candidateTurns]
    .filter((candidate) => candidate.meanScore != null)
    .sort((a, b) => (a.meanScore ?? Number.POSITIVE_INFINITY) - (b.meanScore ?? Number.POSITIVE_INFINITY))[0] ?? null;

  const selectedCandidate =
    selectedByBestId ??
    (mode === "baseline_no_tool" ? baselineCandidate : null) ??
    passingByBestScore ??
    lowestScore ??
    null;

  const completedTrials = candidateTurns.reduce((sum, turn) => sum + turn.completedTrialCount, 0);
  const failedTrials = candidateTurns.reduce((sum, turn) => sum + turn.failedTrialCount, 0);
  const totalTrials = candidateTurns.reduce((sum, turn) => sum + turn.trialCount, 0);

  const pass =
    mode === "baseline_no_tool"
      ? selectedCandidate?.pass === true
      : job.status === "COMPLETED" &&
        (job.optimization_outcome === "success" || selectedCandidate?.pass === true);

  let reason = "No candidate satisfied RMSE / max error / pass-rate thresholds.";
  if (job.status === "FAILED" && job.latest_error) {
    reason = `${job.latest_error.code}: ${job.latest_error.message}`;
  } else if (selectedCandidate?.pass) {
    reason = "Selected candidate satisfied verifier thresholds.";
  } else if (completedTrials === 0) {
    reason = "No completed trials were available for scoring.";
  }

  return {
    mode,
    jobId: job.id,
    jobName: job.display_name ?? null,
    jobStatus: job.status,
    pass,
    reason,
    optimizationOutcome: job.optimization_outcome,
    bestCandidateId: job.best_candidate_id,
    rmse: selectedCandidate?.meanRmse ?? null,
    maxError: selectedCandidate?.meanMaxError ?? null,
    passRate: selectedCandidate?.passRate ?? null,
    score: selectedCandidate?.meanScore ?? null,
    completedTrials,
    failedTrials,
    totalTrials,
    candidateTurns,
  };
}

function Ece498RunResultsTable({ results }: { results: Ece498RunResult[] }) {
  return (
    <SectionCard title="Run Results">
      <div className="data-table-wrapper">
        <table className="data-table">
        <thead>
          <tr>
            <th>Mode</th>
            <th>Job Name</th>
            <th>Job ID</th>
            <th>Status</th>
            <th>Pass / Fail</th>
            <th>RMSE</th>
            <th>Max Error</th>
            <th>Pass Rate</th>
            <th>Score</th>
            <th>Optimization Outcome</th>
            <th>Best Candidate ID</th>
            <th>Completed Trials</th>
            <th>Failed Trials</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {results.map((result) => (
            <tr key={result.jobId}>
              <td>{formatMode(result.mode)}</td>
              <td>{result.jobName || "Unnamed"}</td>
              <td>
                <Link to={`/jobs/${result.jobId}`}><code>{result.jobId}</code></Link>
              </td>
              <td>{result.jobStatus}</td>
              <td>{passFailLabel(result.pass)}</td>
              <td>{formatNullableNumber(result.rmse)}</td>
              <td>{formatNullableNumber(result.maxError)}</td>
              <td>{formatPercent(result.passRate)}</td>
              <td>{formatNullableNumber(result.score)}</td>
              <td>{result.optimizationOutcome ?? "—"}</td>
              <td>{result.bestCandidateId ? <code>{result.bestCandidateId}</code> : "—"}</td>
              <td>{result.completedTrials}</td>
              <td>{result.failedTrials}</td>
              <td className="ece498-result-reason">{result.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </SectionCard>
  );
}

function Ece498CandidateTurnsTable({ turns }: { turns: Ece498CandidateTurn[] }) {
  return (
    <SectionCard title="Candidate / Refinement Turns">
      <div className="data-table-wrapper">
        <table className="data-table">
        <thead>
          <tr>
            <th>Mode</th>
            <th>Role</th>
            <th>Candidate Label</th>
            <th>Generation</th>
            <th>Candidate ID</th>
            <th>Source</th>
            <th>Trial Count</th>
            <th>Completed</th>
            <th>Failed</th>
            <th>Passing</th>
            <th>Pass Rate</th>
            <th>Mean RMSE</th>
            <th>Mean Max Error</th>
            <th>Mean Score</th>
            <th>Pass / Fail</th>
          </tr>
        </thead>
        <tbody>
          {turns.map((turn) => (
            <tr key={`${turn.mode}-${turn.candidateId}`}>
              <td>{formatMode(turn.mode)}</td>
              <td>{formatCandidateRole(turn.role)}</td>
              <td>{turn.label ?? "—"}</td>
              <td>{turn.generationIndex}</td>
              <td><code>{turn.candidateId}</code></td>
              <td>{turn.sourceType ?? "—"}</td>
              <td>{turn.trialCount}</td>
              <td>{turn.completedTrialCount}</td>
              <td>{turn.failedTrialCount}</td>
              <td>{turn.passingTrialCount}</td>
              <td>{formatPercent(turn.passRate)}</td>
              <td>{formatNullableNumber(turn.meanRmse)}</td>
              <td>{formatNullableNumber(turn.meanMaxError)}</td>
              <td>{formatNullableNumber(turn.meanScore)}</td>
              <td>{passFailLabel(turn.pass)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </SectionCard>
  );
}

export function ECE498() {
  const [form, setForm] = useState<Ece498FormState>(DEFAULT_FORM);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [results, setResults] = useState<Ece498RunResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runningMode, setRunningMode] = useState<Ece498Mode | null>(null);
  const [errors, setErrors] = useState<Ece498FieldErrors>({});

  const update =
    (k: keyof Ece498FormState) =>
    (e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm((p) => ({ ...p, [k]: e.target.value }));

  async function runMode(mode: Ece498Mode) {
    setError(null);
    const nextErrors = validateEce498Form(form);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;
    setRunningMode(mode);
    setRunning(true);
    try {
      const created = await apiClient.createJob(buildEce498JobRequest(form, mode));
      const job = await waitForTerminalJob(created.id);
      const trialSummaries = await apiClient.listJobTrials(created.id);
      const trials = await Promise.all(trialSummaries.map((trial) => apiClient.getTrial(trial.id)));
      const candidateTurns = summarizeCandidateTurns(mode, trials, form);
      const result = summarizeRunResult(mode, job, candidateTurns);
      setResults((p) => [...p, result]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setRunning(false);
      setRunningMode(null);
    }
  }

  const allTurns = useMemo(
    () => results.flatMap((result) => result.candidateTurns),
    [results],
  );

  return (
    <div>
      <h1>ECE498</h1>
      {error && (
        <Alert tone="danger" title="Error">
          {error}
        </Alert>
      )}

      <SectionCard title="Assignment Modes">
        <p className="muted">Baseline runs without tooling (optimizer_strategy="none"). Tool-Augmented runs CMA-ES once. Tool + Refinement runs CMA-ES for generations 1, 2, and 3. Verifier pass/fail uses RMSE, max error, and pass rate.</p>
      </SectionCard>
      <SectionCard title="Job & Track Configuration"><div className="form-grid">
      <Field label="Job Name" htmlFor="display_name" hint="Optional label for your own reference. Job ID remains the canonical identifier." error={errors.display_name}><input id="display_name" value={form.display_name} onChange={update("display_name")} /></Field>
      <Field label="Track Type" htmlFor="track_type"><select id="track_type" value={form.track_type} onChange={update("track_type")}><option value="circle">circle</option><option value="u_turn">u_turn</option><option value="lemniscate">lemniscate</option><option value="custom">custom</option></select></Field>
      <Field label="Start X" htmlFor="start_x"><input id="start_x" type="number" value={form.start_x} onChange={update("start_x")} /></Field><Field label="Start Y" htmlFor="start_y"><input id="start_y" type="number" value={form.start_y} onChange={update("start_y")} /></Field><Field label="Altitude (m)" htmlFor="altitude_m"><input id="altitude_m" type="number" value={form.altitude_m} onChange={update("altitude_m")} /></Field>
      {form.track_type === "circle" && <Field label="Circle Radius (m)" htmlFor="circle_radius_m" error={errors.circle_radius_m}><input id="circle_radius_m" type="number" value={form.circle_radius_m} onChange={update("circle_radius_m")} /></Field>}
      {form.track_type === "u_turn" && <><Field label="U-turn Straight Length (m)" htmlFor="u_turn_straight_length_m" error={errors.u_turn_straight_length_m}><input id="u_turn_straight_length_m" type="number" value={form.u_turn_straight_length_m} onChange={update("u_turn_straight_length_m")} /></Field><Field label="U-turn Radius (m)" htmlFor="u_turn_turn_radius_m" error={errors.u_turn_turn_radius_m}><input id="u_turn_turn_radius_m" type="number" value={form.u_turn_turn_radius_m} onChange={update("u_turn_turn_radius_m")} /></Field></>}
      {form.track_type === "lemniscate" && <Field label="Figure-eight Scale (m)" htmlFor="lemniscate_scale_m" error={errors.lemniscate_scale_m}><input id="lemniscate_scale_m" type="number" value={form.lemniscate_scale_m} onChange={update("lemniscate_scale_m")} /></Field>}
      {form.track_type === "custom" && <Field label="Custom Reference Track JSON" htmlFor="reference_track_json" error={errors.reference_track_json}><textarea id="reference_track_json" value={form.reference_track_json} onChange={update("reference_track_json")} /></Field>}
      </div></SectionCard>
      <SectionCard title="Baseline Controller Parameters"><div className="form-grid">
      {[["baseline_kp_xy","kp_xy"],["baseline_kd_xy","kd_xy"],["baseline_ki_xy","ki_xy"],["baseline_vel_limit","vel_limit"],["baseline_accel_limit","accel_limit"],["baseline_disturbance_rejection","disturbance_rejection"]].map(([k,label]) => <Field key={k} label={label} htmlFor={k} error={errors[k as keyof Ece498FormState]}><input id={k} type="number" value={form[k as keyof Ece498FormState] as string} onChange={update(k as keyof Ece498FormState)} /></Field>)}
      </div><button type="button" className="btn" onClick={() => setForm((p)=>({...p,baseline_kp_xy:"1",baseline_kd_xy:"0.2",baseline_ki_xy:"0.05",baseline_vel_limit:"5",baseline_accel_limit:"4",baseline_disturbance_rejection:"0.5"}))}>Reset Baseline Defaults</button></SectionCard>
      <SectionCard title="Environment"><div className="form-grid"><Field label="Wind North" htmlFor="wind_north" error={errors.wind_north}><input id="wind_north" type="number" value={form.wind_north} onChange={update("wind_north")} /></Field><Field label="Wind East" htmlFor="wind_east" error={errors.wind_east}><input id="wind_east" type="number" value={form.wind_east} onChange={update("wind_east")} /></Field><Field label="Wind South" htmlFor="wind_south" error={errors.wind_south}><input id="wind_south" type="number" value={form.wind_south} onChange={update("wind_south")} /></Field><Field label="Wind West" htmlFor="wind_west" error={errors.wind_west}><input id="wind_west" type="number" value={form.wind_west} onChange={update("wind_west")} /></Field><Field label="Sensor Noise Level" htmlFor="sensor_noise_level" error={errors.sensor_noise_level}><select id="sensor_noise_level" value={form.sensor_noise_level} onChange={update("sensor_noise_level")}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select></Field></div></SectionCard>
      <SectionCard title="Verifier / Acceptance Criteria"><div className="form-grid"><Field label="Objective Profile" htmlFor="objective_profile"><select id="objective_profile" value={form.objective_profile} onChange={update("objective_profile")}><option value="stable">stable</option><option value="fast">fast</option><option value="smooth">smooth</option><option value="robust">robust</option><option value="custom">custom</option></select></Field><Field label="Target RMSE" htmlFor="target_rmse" error={errors.target_rmse}><input id="target_rmse" type="number" value={form.target_rmse} onChange={update("target_rmse")} /></Field><Field label="Target Max Error" htmlFor="target_max_error" error={errors.target_max_error}><input id="target_max_error" type="number" value={form.target_max_error} onChange={update("target_max_error")} /></Field><Field label="Min Pass Rate" htmlFor="min_pass_rate" error={errors.min_pass_rate}><input id="min_pass_rate" type="number" value={form.min_pass_rate} onChange={update("min_pass_rate")} /></Field></div></SectionCard>
      <SectionCard title="Execution Backend"><div className="form-grid"><Field label="Simulator Backend" htmlFor="simulator_backend"><select id="simulator_backend" value={form.simulator_backend} onChange={update("simulator_backend")}><option value="mock">mock</option><option value="real_cli">real_cli</option></select></Field></div>{form.simulator_backend==="real_cli" && <p className="form-error">real_cli requires REAL_SIMULATOR_COMMAND and the PX4/Gazebo runner environment to be configured.</p>}</SectionCard>
      <SectionCard title="Advanced Scenario" description="Optional extended PX4/Gazebo scenario parameters.">
        <button type="button" className="btn btn-ghost" onClick={() => setAdvancedOpen((p) => !p)}>
          {advancedOpen ? "Hide Advanced scenario" : "Show Advanced scenario"}
        </button>
        {advancedOpen ? (
          <div className="stack-sm">
            <div className="form-grid">
              <Field label="Enable advanced scenario" htmlFor="advanced_enabled">
                <select id="advanced_enabled" value={boolToYesNo(form.advanced_enabled)} onChange={(e) => setForm((p) => ({ ...p, advanced_enabled: yesNoToBool(e.target.value) }))}><option value="no">no</option><option value="yes">yes</option></select>
              </Field>
              <Field label="Enable gust" htmlFor="gust_enabled">
                <select id="gust_enabled" value={boolToYesNo(form.gust_enabled)} onChange={(e) => setForm((p) => ({ ...p, gust_enabled: yesNoToBool(e.target.value) }))}><option value="no">no</option><option value="yes">yes</option></select>
              </Field>
              <Field label="Gust magnitude (m/s)" htmlFor="gust_magnitude_mps" error={errors.gust_magnitude_mps}><input id="gust_magnitude_mps" type="number" value={form.gust_magnitude_mps} onChange={update("gust_magnitude_mps")} /></Field>
              <Field label="Gust direction (deg)" htmlFor="gust_direction_deg" error={errors.gust_direction_deg}><input id="gust_direction_deg" type="number" value={form.gust_direction_deg} onChange={update("gust_direction_deg")} /></Field>
              <Field label="Gust period (s)" htmlFor="gust_period_s" error={errors.gust_period_s}><input id="gust_period_s" type="number" value={form.gust_period_s} onChange={update("gust_period_s")} /></Field>
              <Field label="GPS noise (m)" htmlFor="gps_noise_m" error={errors.gps_noise_m}><input id="gps_noise_m" type="number" value={form.gps_noise_m} onChange={update("gps_noise_m")} /></Field>
              <Field label="Baro noise (m)" htmlFor="baro_noise_m" error={errors.baro_noise_m}><input id="baro_noise_m" type="number" value={form.baro_noise_m} onChange={update("baro_noise_m")} /></Field>
              <Field label="IMU noise scale" htmlFor="imu_noise_scale" error={errors.imu_noise_scale}><input id="imu_noise_scale" type="number" value={form.imu_noise_scale} onChange={update("imu_noise_scale")} /></Field>
              <Field label="Dropout rate" htmlFor="dropout_rate" error={errors.dropout_rate}><input id="dropout_rate" type="number" value={form.dropout_rate} onChange={update("dropout_rate")} /></Field>
              <Field label="Battery initial percent" htmlFor="battery_initial_percent" error={errors.battery_initial_percent}><input id="battery_initial_percent" type="number" value={form.battery_initial_percent} onChange={update("battery_initial_percent")} /></Field>
              <Field label="Battery voltage sag" htmlFor="battery_voltage_sag"><select id="battery_voltage_sag" value={boolToYesNo(form.battery_voltage_sag)} onChange={(e) => setForm((p) => ({ ...p, battery_voltage_sag: yesNoToBool(e.target.value) }))}><option value="no">no</option><option value="yes">yes</option></select></Field>
              <Field label="Payload mass (kg)" htmlFor="mass_payload_kg" error={errors.mass_payload_kg}><input id="mass_payload_kg" type="number" value={form.mass_payload_kg} onChange={update("mass_payload_kg")} /></Field>
              <Field label="Obstacles JSON" htmlFor="obstacles_json" error={errors.obstacles_json}><textarea id="obstacles_json" value={form.obstacles_json} onChange={update("obstacles_json")} /></Field>
            </div>
            <details><summary>Example obstacles JSON</summary><pre>{OBSTACLES_JSON_EXAMPLE}</pre><button type="button" className="btn btn-ghost" onClick={() => setForm((p) => ({ ...p, obstacles_json: OBSTACLES_JSON_EXAMPLE }))}>Use example</button></details>
          </div>
        ) : null}
      </SectionCard>

      <div className="ece498-run-actions">
        <button disabled={running} onClick={() => void runMode("baseline_no_tool")}>
          Run Baseline (No Tool)
        </button>
        <button disabled={running} onClick={() => void runMode("tool_augmented")}>
          Run Tool-Augmented (CMA-ES)
        </button>
        <button disabled={running} onClick={() => void runMode("tool_refinement")}>
          Run Tool + Refinement (CMA-ES Loop)
        </button>
      </div>
      {running && <p className="muted">Running selected ECE498 mode. This may take time, especially with real_cli.</p>}
      {runningMode && <p className="muted">Current mode: {formatMode(runningMode)}</p>}

      {results.length === 0 ? (
        <SectionCard title="Results">
          <p className="muted">Run one of the three modes to see results.</p>
        </SectionCard>
      ) : (
        <>
          <Ece498RunResultsTable results={results} />
          <Ece498CandidateTurnsTable turns={allTurns} />
        </>
      )}
    </div>
  );
}

interface FieldProps {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
  error?: string;
}

function Field({ label, htmlFor, hint, children, error }: FieldProps) {
  return (
    <div className="form-field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint ? <span className="form-hint">{hint}</span> : null}
      {error ? <span className="form-error">{error}</span> : null}
    </div>
  );
}
