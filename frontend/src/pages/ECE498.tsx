import { useMemo, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";
import { Link } from "react-router-dom";

import { apiClient } from "../api/client";
import { Alert } from "../components/Alert";
import { SectionCard } from "../components/SectionCard";
import type { CandidateSourceType, Job, JobCreateRequest, JobStatus, OptimizationOutcome, SimulatorBackend, TrackType, Trial } from "../types/api";

export type Ece498Mode = "baseline_no_tool" | "tool_augmented" | "tool_refinement";

type Role = "baseline" | "tool_turn_1" | "refinement_turn_2" | "refinement_turn_3" | "other";

export interface Ece498CandidateTurn { candidateId: string; label: string | null; sourceType: CandidateSourceType | null; generationIndex: number; role: Role; trialCount: number; completedTrialCount: number; passingTrialCount: number; passRate: number; meanRmse: number | null; meanMaxError: number | null; meanScore: number | null; pass: boolean; }
export interface Ece498RunResult { mode: Ece498Mode; jobId: string; jobStatus: JobStatus; pass: boolean; reason: string; optimizationOutcome: OptimizationOutcome | null; bestCandidateId: string | null; rmse: number | null; maxError: number | null; passRate: number | null; completedTrials: number; failedTrials: number; candidateTurns: Ece498CandidateTurn[]; }

export interface Ece498FormState { display_name?: string; track_type: TrackType; reference_track_json: string; baseline_kp_xy?: string; baseline_kd_xy?: string; baseline_ki_xy?: string; baseline_vel_limit?: string; baseline_accel_limit?: string; baseline_disturbance_rejection?: string; circle_radius_m?: string; u_turn_straight_m?: string; u_turn_radius_m?: string; lemniscate_width_m?: string; lemniscate_height_m?: string; start_x: string; start_y: string; altitude_m: string; wind_north: string; wind_east: string; wind_south: string; wind_west: string; sensor_noise_level: "low"|"medium"|"high"; objective_profile: "stable"|"fast"|"smooth"|"robust"|"custom"; advanced_scenario_config_json: string; target_rmse: string; target_max_error: string; min_pass_rate: string; simulator_backend: SimulatorBackend; }

const DEFAULT_FORM: Ece498FormState = { display_name: "", track_type: "circle", reference_track_json: "", baseline_kp_xy: "1", baseline_kd_xy: "0.2", baseline_ki_xy: "0.05", baseline_vel_limit: "5", baseline_accel_limit: "2", baseline_disturbance_rejection: "0.8", circle_radius_m: "5", u_turn_straight_m: "8", u_turn_radius_m: "3", lemniscate_width_m: "8", lemniscate_height_m: "4", start_x: "0", start_y: "0", altitude_m: "3", wind_north: "0", wind_east: "0", wind_south: "0", wind_west: "0", sensor_noise_level: "medium", objective_profile: "robust", advanced_scenario_config_json: "", target_rmse: "0.5", target_max_error: "", min_pass_rate: "0.8", simulator_backend: "mock" };

function n(v: string | undefined | null): number | null { if (!v || v.trim()==="") return null; const x=Number(v); return Number.isFinite(x)?x:null; }
function parseTrack(raw: string) { if (!raw.trim()) return null; try { const data = JSON.parse(raw) as Array<{x:number;y:number;z?:number}>; return Array.isArray(data)?data:null;} catch { return null; } }

export function buildEce498JobRequest(form: Ece498FormState, mode: Ece498Mode): JobCreateRequest {
  const optimizer_strategy = mode === "baseline_no_tool" ? "none" : "cma_es";
  const max_iterations = mode === "tool_refinement" ? 3 : 1;
  return {
    display_name: form.display_name?.trim?.() || null,
    track_type: form.track_type,
    reference_track: form.track_type === "custom" ? parseTrack(form.reference_track_json) : [{x:0,y:0,z:n(form.altitude_m) ?? 3},{x: n(form.circle_radius_m) ?? 5, y:0, z:n(form.altitude_m) ?? 3}],
    baseline_parameters: { kp_xy: n(form.baseline_kp_xy ?? "1") ?? 1, kd_xy: n(form.baseline_kd_xy ?? "0.2") ?? 0.2, ki_xy: n(form.baseline_ki_xy ?? "0.05") ?? 0.05, vel_limit: n(form.baseline_vel_limit ?? "5") ?? 5, accel_limit: n(form.baseline_accel_limit ?? "2") ?? 2, disturbance_rejection: n(form.baseline_disturbance_rejection ?? "0.8") ?? 0.8 },
    start_point: { x: n(form.start_x) ?? 0, y: n(form.start_y) ?? 0 },
    altitude_m: n(form.altitude_m) ?? 3,
    wind: { north: n(form.wind_north) ?? 0, east: n(form.wind_east) ?? 0, south: n(form.wind_south) ?? 0, west: n(form.wind_west) ?? 0 },
    sensor_noise_level: form.sensor_noise_level,
    objective_profile: form.objective_profile,
    advanced_scenario_config: form.advanced_scenario_config_json.trim() ? JSON.parse(form.advanced_scenario_config_json) as JobCreateRequest["advanced_scenario_config"] : null,
    simulator_backend: form.simulator_backend,
    optimizer_strategy,
    max_iterations,
    trials_per_candidate: 3,
    acceptance_criteria: { target_rmse: n(form.target_rmse), target_max_error: n(form.target_max_error), min_pass_rate: n(form.min_pass_rate) ?? 0.8 },
  };
}

function roleOf(t: Trial): Role { if (t.candidate_is_baseline || t.candidate_source_type === "baseline") return "baseline"; if (t.candidate_generation_index===1) return "tool_turn_1"; if (t.candidate_generation_index===2) return "refinement_turn_2"; if (t.candidate_generation_index===3) return "refinement_turn_3"; return "other"; }

export function ECE498() {
  const [form, setForm] = useState<Ece498FormState>(DEFAULT_FORM);
  const [results, setResults] = useState<Ece498RunResult[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const update = (k: keyof Ece498FormState) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setForm((p) => ({ ...p, [k]: e.target.value }));

  async function runMode(mode: Ece498Mode) {
    setError(null);
    if (mode !== "baseline_no_tool" && !form.target_rmse.trim() && !form.target_max_error.trim()) { setError("For CMA-ES refinement, set target_rmse or target_max_error."); return; }
    setRunning(true);
    try {
      const created = await apiClient.createJob(buildEce498JobRequest(form, mode));
      let job: Job = await apiClient.getJob(created.id);
      while (!["COMPLETED", "FAILED", "CANCELLED"].includes(job.status)) {
        await new Promise((r) => setTimeout(r, 3000));
        job = await apiClient.getJob(created.id);
      }
      const trialSummaries = await apiClient.listJobTrials(created.id);
      const trials = await Promise.all(trialSummaries.map((t) => apiClient.getTrial(t.id)));
      if (job.status === "COMPLETED") { await apiClient.getJobReport(created.id).catch(() => null); }
      const byCandidate = new Map<string, Trial[]>();
      trials.forEach((t) => { const arr = byCandidate.get(t.candidate_id) ?? []; arr.push(t); byCandidate.set(t.candidate_id, arr); });
      const minPass = n(form.min_pass_rate) ?? 0.8;
      const targetRmse = n(form.target_rmse);
      const targetMax = n(form.target_max_error);
      const candidateTurns: Ece498CandidateTurn[] = [...byCandidate.entries()].map(([cid, ts]) => {
        const completed = ts.filter((t) => t.status === "COMPLETED");
        const passing = completed.filter((t) => t.metrics?.pass_flag);
        const rm = completed.map((t) => t.metrics?.rmse).filter((x): x is number => typeof x === "number");
        const me = completed.map((t) => t.metrics?.max_error).filter((x): x is number => typeof x === "number");
        const sc = completed.map((t) => t.metrics?.score).filter((x): x is number => typeof x === "number");
        const passRate = completed.length ? passing.length/completed.length : 0;
        const mean = (a:number[]) => a.length ? a.reduce((s,v)=>s+v,0)/a.length : null;
        const meanRmse = mean(rm); const meanMaxError = mean(me);
        const pass = passRate >= minPass && (targetRmse==null || (meanRmse!=null && meanRmse<=targetRmse)) && (targetMax==null || (meanMaxError!=null && meanMaxError<=targetMax));
        return { candidateId: cid, label: ts[0].candidate_label, sourceType: ts[0].candidate_source_type, generationIndex: ts[0].candidate_generation_index, role: roleOf(ts[0]), trialCount: ts.length, completedTrialCount: completed.length, passingTrialCount: passing.length, passRate, meanRmse, meanMaxError, meanScore: mean(sc), pass };
      });
      const completedTrials = trials.filter((t) => t.status === "COMPLETED").length;
      const failedTrials = trials.filter((t) => t.status === "FAILED").length;
      setResults((p) => [...p, { mode, jobId: created.id, jobStatus: job.status, pass: job.status === "COMPLETED" && job.optimization_outcome === "success", reason: job.status === "COMPLETED" ? "completed" : "terminated", optimizationOutcome: job.optimization_outcome, bestCandidateId: job.best_candidate_id, rmse: null, maxError: null, passRate: null, completedTrials, failedTrials, candidateTurns }]);
    } catch (e) { setError(e instanceof Error ? e.message : "Run failed"); }
    finally { setRunning(false); }
  }

  const allTurns = useMemo(() => results.flatMap((r) => r.candidateTurns.map((t) => ({ ...t, mode: r.mode }))), [results]);
  return <div>
    <h1>ECE498</h1><p>Assignment 3 pipeline: baseline, tool-augmented, and tool + refinement evaluation.</p>
    <SectionCard title="Overview"><ul><li>Baseline: no external tool; evaluates fixed DroneDream baseline parameters.</li><li>Tool-Augmented: invokes the existing CMA-ES-style adaptive parameter tuning tool once.</li><li>Tool + Refinement: repeats CMA-ES proposal after verifier failure, up to two refinement turns.</li><li>Verifier: acceptance criteria based on RMSE, max error, and pass rate.</li></ul></SectionCard>
    {error && <Alert tone="danger" title="Error">{error}</Alert>}
    <SectionCard title="Config">
      <div className="form-grid">
                <Field label="Job Name" htmlFor="display_name"><input id="display_name" value={form.display_name} onChange={update("display_name")} /></Field>
        <Field label="Baseline kp_xy" htmlFor="baseline_kp_xy"><input id="baseline_kp_xy" type="number" step="any" value={form.baseline_kp_xy} onChange={update("baseline_kp_xy")} /></Field>
        <Field label="Track Type" htmlFor="track_type">
          <select id="track_type" value={form.track_type} onChange={update("track_type")}>
            <option value="circle">circle</option><option value="u_turn">u_turn</option><option value="lemniscate">lemniscate</option><option value="custom">custom</option>
          </select>
        </Field>
        <Field label="Start X" htmlFor="start_x">
          <input id="start_x" aria-label="start_x" type="number" step="any" value={form.start_x} onChange={update("start_x")} />
        </Field>
        <Field label="Start Y" htmlFor="start_y">
          <input id="start_y" type="number" step="any" value={form.start_y} onChange={update("start_y")} />
        </Field>
        <Field label="Altitude (m)" htmlFor="altitude_m">
          <input id="altitude_m" type="number" step="0.1" value={form.altitude_m} onChange={update("altitude_m")} />
        </Field>
        <Field label="Wind North" htmlFor="wind_north">
          <input id="wind_north" type="number" step="any" value={form.wind_north} onChange={update("wind_north")} />
        </Field>
        <Field label="Wind East" htmlFor="wind_east">
          <input id="wind_east" type="number" step="any" value={form.wind_east} onChange={update("wind_east")} />
        </Field>
        <Field label="Wind South" htmlFor="wind_south">
          <input id="wind_south" type="number" step="any" value={form.wind_south} onChange={update("wind_south")} />
        </Field>
        <Field label="Wind West" htmlFor="wind_west">
          <input id="wind_west" type="number" step="any" value={form.wind_west} onChange={update("wind_west")} />
        </Field>
        <Field label="Sensor Noise Level" htmlFor="sensor_noise_level">
          <select id="sensor_noise_level" value={form.sensor_noise_level} onChange={update("sensor_noise_level")}>
            <option value="low">low</option><option value="medium">medium</option><option value="high">high</option>
          </select>
        </Field>
        <Field label="Objective Profile" htmlFor="objective_profile">
          <select id="objective_profile" value={form.objective_profile} onChange={update("objective_profile")}>
            <option value="stable">stable</option><option value="fast">fast</option><option value="smooth">smooth</option><option value="robust">robust</option><option value="custom">custom</option>
          </select>
        </Field>
        <Field label="Simulator Backend" htmlFor="simulator_backend">
          <select id="simulator_backend" value={form.simulator_backend} onChange={update("simulator_backend")}>
            <option value="mock">mock</option><option value="real_cli">real_cli</option>
          </select>
        </Field>
        {form.simulator_backend === "real_cli" ? (
          <Alert tone="warning" title="real_cli environment requirement">
            real_cli requires REAL_SIMULATOR_COMMAND and PX4/Gazebo runner environment to be configured.
          </Alert>
        ) : null}
        <Field label="Target RMSE" htmlFor="target_rmse">
          <input id="target_rmse" type="number" step="any" value={form.target_rmse} onChange={update("target_rmse")} />
        </Field>
        <Field label="Target Max Error" htmlFor="target_max_error">
          <input id="target_max_error" type="number" step="any" value={form.target_max_error} onChange={update("target_max_error")} />
        </Field>
        <Field label="Min Pass Rate" htmlFor="min_pass_rate">
          <input id="min_pass_rate" type="number" min={0} max={1} step="0.01" value={form.min_pass_rate} onChange={update("min_pass_rate")} />
        </Field>
        {form.track_type === "custom" ? (
          <Field label="Custom Reference Track JSON" htmlFor="reference_track_json">
            <textarea id="reference_track_json" rows={5} value={form.reference_track_json} onChange={update("reference_track_json")} />
          </Field>
        ) : null}
        <Field label="Advanced Scenario JSON" htmlFor="advanced_scenario_config_json" hint="Optional. Leave empty to disable advanced scenario config.">
          <textarea id="advanced_scenario_config_json" rows={5} value={form.advanced_scenario_config_json} onChange={update("advanced_scenario_config_json")} />
        </Field>
      </div>
    </SectionCard>
    <div style={{ display: "flex", gap: 12 }}>
      <button disabled={running} onClick={() => void runMode("baseline_no_tool")}>Run Baseline (No Tool)</button>
      <button disabled={running} onClick={() => void runMode("tool_augmented")}>Run Tool-Augmented (CMA-ES)</button>
      <button disabled={running} onClick={() => void runMode("tool_refinement")}>Run Tool + Refinement (CMA-ES Loop)</button>
    </div>
    {results.length > 0 ? <table><thead><tr><th>Mode</th><th>Job ID</th><th>Status</th><th>Pass / Fail</th></tr></thead><tbody>{results.map((r)=><tr key={r.jobId}><td>{r.mode}</td><td><Link to={`/jobs/${r.jobId}`}>{r.jobId}</Link></td><td>{r.jobStatus}</td><td>{r.pass?"Pass":"Fail"}</td></tr>)}</tbody></table> : null}
    <table><thead><tr><th>Role</th><th>Candidate Label</th><th>Generation</th><th>Candidate ID</th><th>Pass / Fail</th></tr></thead><tbody>{allTurns.map((t)=><tr key={`${t.mode}-${t.candidateId}`}><td>{t.role}</td><td>{t.label}</td><td>{t.generationIndex}</td><td>{t.candidateId}</td><td>{t.pass?"Pass":"Fail"}</td></tr>)}</tbody></table>
  </div>;
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
