import { useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import { Link } from "react-router-dom";

import { apiClient } from "../api/client";
import { Alert } from "../components/Alert";
import { SectionCard } from "../components/SectionCard";
import type { CandidateSourceType, Job, JobCreateRequest, JobStatus, OptimizationOutcome, SimulatorBackend, TrackType, Trial } from "../types/api";

export type Ece498Mode = "baseline_no_tool" | "tool_augmented" | "tool_refinement";

type Role = "baseline" | "tool_turn_1" | "refinement_turn_2" | "refinement_turn_3" | "other";

export interface Ece498CandidateTurn { candidateId: string; label: string | null; sourceType: CandidateSourceType | null; generationIndex: number; role: Role; trialCount: number; completedTrialCount: number; passingTrialCount: number; passRate: number; meanRmse: number | null; meanMaxError: number | null; meanScore: number | null; pass: boolean; }
export interface Ece498RunResult { mode: Ece498Mode; jobId: string; jobStatus: JobStatus; pass: boolean; reason: string; optimizationOutcome: OptimizationOutcome | null; bestCandidateId: string | null; rmse: number | null; maxError: number | null; passRate: number | null; completedTrials: number; failedTrials: number; candidateTurns: Ece498CandidateTurn[]; }

export interface Ece498FormState { track_type: TrackType; reference_track_json: string; start_x: string; start_y: string; altitude_m: string; wind_north: string; wind_east: string; wind_south: string; wind_west: string; sensor_noise_level: "low"|"medium"|"high"; objective_profile: "stable"|"fast"|"smooth"|"robust"|"custom"; advanced_scenario_config_json: string; target_rmse: string; target_max_error: string; min_pass_rate: string; simulator_backend: SimulatorBackend; }

const DEFAULT_FORM: Ece498FormState = { track_type: "circle", reference_track_json: "", start_x: "0", start_y: "0", altitude_m: "3", wind_north: "0", wind_east: "0", wind_south: "0", wind_west: "0", sensor_noise_level: "medium", objective_profile: "robust", advanced_scenario_config_json: "", target_rmse: "0.5", target_max_error: "", min_pass_rate: "0.8", simulator_backend: "mock" };

function n(v: string): number | null { if (v.trim()==="") return null; const x=Number(v); return Number.isFinite(x)?x:null; }
function parseTrack(raw: string) { if (!raw.trim()) return null; try { const data = JSON.parse(raw) as Array<{x:number;y:number;z?:number}>; return Array.isArray(data)?data:null;} catch { return null; } }

export function buildEce498JobRequest(form: Ece498FormState, mode: Ece498Mode): JobCreateRequest {
  const optimizer_strategy = mode === "baseline_no_tool" ? "none" : "cma_es";
  const max_iterations = mode === "tool_refinement" ? 3 : 1;
  return {
    track_type: form.track_type,
    reference_track: form.track_type === "custom" ? parseTrack(form.reference_track_json) : null,
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
    <SectionCard title="Config"><input aria-label="start_x" value={form.start_x} onChange={update("start_x")} /><select aria-label="track_type" value={form.track_type} onChange={update("track_type")}><option value="circle">circle</option><option value="u_turn">u_turn</option><option value="lemniscate">lemniscate</option><option value="custom">custom</option></select></SectionCard>
    <button disabled={running} onClick={() => void runMode("baseline_no_tool")}>Run Baseline (No Tool)</button>
    <button disabled={running} onClick={() => void runMode("tool_augmented")}>Run Tool-Augmented (CMA-ES)</button>
    <button disabled={running} onClick={() => void runMode("tool_refinement")}>Run Tool + Refinement (CMA-ES Loop)</button>
    <table><thead><tr><th>Mode</th><th>Job ID</th><th>Status</th><th>Pass / Fail</th></tr></thead><tbody>{results.map((r)=><tr key={r.jobId}><td>{r.mode}</td><td><Link to={`/jobs/${r.jobId}`}>{r.jobId}</Link></td><td>{r.jobStatus}</td><td>{r.pass?"Pass":"Fail"}</td></tr>)}</tbody></table>
    <table><thead><tr><th>Role</th><th>Candidate Label</th><th>Generation</th><th>Candidate ID</th><th>Pass / Fail</th></tr></thead><tbody>{allTurns.map((t)=><tr key={`${t.mode}-${t.candidateId}`}><td>{t.role}</td><td>{t.label}</td><td>{t.generationIndex}</td><td>{t.candidateId}</td><td>{t.pass?"Pass":"Fail"}</td></tr>)}</tbody></table>
  </div>;
}
