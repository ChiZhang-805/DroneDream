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
  advanced_scenario_config_json: string;
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
  advanced_scenario_config_json: "",
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
    advanced_scenario_config: form.advanced_scenario_config_json.trim()
      ? (JSON.parse(form.advanced_scenario_config_json) as JobCreateRequest["advanced_scenario_config"])
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
      <table>
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
              <td>{result.mode}</td>
              <td>{result.jobName || "Unnamed"}</td>
              <td>
                <Link to={`/jobs/${result.jobId}`}>{result.jobId}</Link>
              </td>
              <td>{result.jobStatus}</td>
              <td>{passFailLabel(result.pass)}</td>
              <td>{formatNullableNumber(result.rmse)}</td>
              <td>{formatNullableNumber(result.maxError)}</td>
              <td>{formatPercent(result.passRate)}</td>
              <td>{formatNullableNumber(result.score)}</td>
              <td>{result.optimizationOutcome ?? "—"}</td>
              <td>{result.bestCandidateId ?? "—"}</td>
              <td>{result.completedTrials}</td>
              <td>{result.failedTrials}</td>
              <td>{result.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </SectionCard>
  );
}

function Ece498CandidateTurnsTable({ turns }: { turns: Ece498CandidateTurn[] }) {
  return (
    <SectionCard title="Candidate / Refinement Turns">
      <table>
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
              <td>{turn.mode}</td>
              <td>{turn.role}</td>
              <td>{turn.label ?? "—"}</td>
              <td>{turn.generationIndex}</td>
              <td>{turn.candidateId}</td>
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
    </SectionCard>
  );
}

export function ECE498() {
  const [form, setForm] = useState<Ece498FormState>(DEFAULT_FORM);
  const [results, setResults] = useState<Ece498RunResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const update =
    (k: keyof Ece498FormState) =>
    (e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setForm((p) => ({ ...p, [k]: e.target.value }));

  async function runMode(mode: Ece498Mode) {
    setError(null);
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

      <SectionCard title="Config">
        <div className="form-grid">
          <Field label="Job Name" htmlFor="display_name">
            <input id="display_name" value={form.display_name} onChange={update("display_name")} />
          </Field>
          <Field label="Track Type" htmlFor="track_type">
            <select id="track_type" value={form.track_type} onChange={update("track_type")}>
              <option value="circle">circle</option>
              <option value="u_turn">u_turn</option>
              <option value="lemniscate">lemniscate</option>
              <option value="custom">custom</option>
            </select>
          </Field>
          <Field label="Start X" htmlFor="start_x">
            <input id="start_x" type="number" value={form.start_x} onChange={update("start_x")} />
          </Field>
          <Field label="Start Y" htmlFor="start_y">
            <input id="start_y" type="number" value={form.start_y} onChange={update("start_y")} />
          </Field>
          <Field label="Altitude" htmlFor="altitude_m">
            <input id="altitude_m" type="number" value={form.altitude_m} onChange={update("altitude_m")} />
          </Field>

          {form.track_type === "circle" && (
            <Field label="Circle Radius (m)" htmlFor="circle_radius_m">
              <input
                id="circle_radius_m"
                type="number"
                value={form.circle_radius_m}
                onChange={update("circle_radius_m")}
              />
            </Field>
          )}

          {form.track_type === "u_turn" && (
            <>
              <Field label="U-turn Straight Length (m)" htmlFor="u_turn_straight_length_m">
                <input
                  id="u_turn_straight_length_m"
                  type="number"
                  value={form.u_turn_straight_length_m}
                  onChange={update("u_turn_straight_length_m")}
                />
              </Field>
              <Field label="U-turn Radius (m)" htmlFor="u_turn_turn_radius_m">
                <input
                  id="u_turn_turn_radius_m"
                  type="number"
                  value={form.u_turn_turn_radius_m}
                  onChange={update("u_turn_turn_radius_m")}
                />
              </Field>
            </>
          )}

          {form.track_type === "lemniscate" && (
            <Field label="Figure-eight Scale (m)" htmlFor="lemniscate_scale_m">
              <input
                id="lemniscate_scale_m"
                type="number"
                value={form.lemniscate_scale_m}
                onChange={update("lemniscate_scale_m")}
              />
            </Field>
          )}

          {form.track_type === "custom" && (
            <Field label="Custom Reference Track JSON" htmlFor="reference_track_json">
              <textarea
                id="reference_track_json"
                value={form.reference_track_json}
                onChange={update("reference_track_json")}
              />
            </Field>
          )}

          {[
            "kp_xy",
            "kd_xy",
            "ki_xy",
            "vel_limit",
            "accel_limit",
            "disturbance_rejection",
          ].map((k) => (
            <Field key={k} label={`Baseline ${k}`} htmlFor={`baseline_${k}`}>
              <input
                id={`baseline_${k}`}
                type="number"
                value={form[`baseline_${k}` as keyof Ece498FormState] as string}
                onChange={update(`baseline_${k}` as keyof Ece498FormState)}
              />
            </Field>
          ))}

          <Field label="Target RMSE" htmlFor="target_rmse">
            <input id="target_rmse" type="number" value={form.target_rmse} onChange={update("target_rmse")} />
          </Field>
        </div>
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
}

function Field({ label, htmlFor, hint, children }: FieldProps) {
  return (
    <div className="form-field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint ? <span className="form-hint">{hint}</span> : null}
    </div>
  );
}
