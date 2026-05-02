// Type definitions aligned with docs/04_API_SPEC.md and docs/05_DATA_MODEL.md.
// These shapes are the source of truth for Phase 1 mock data and are intended
// to match the real /api/v1 contract introduced in later phases.

export type JobStatus =
  | "CREATED"
  | "QUEUED"
  | "RUNNING"
  | "AGGREGATING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";
export type BatchStatus =
  | "CREATED"
  | "QUEUED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export const JOB_STATUSES: readonly JobStatus[] = [
  "CREATED",
  "QUEUED",
  "RUNNING",
  "AGGREGATING",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
];

export type TrialStatus =
  | "PENDING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export type TrackType = "circle" | "u_turn" | "lemniscate" | "custom";
export const TRACK_TYPES: readonly TrackType[] = [
  "circle",
  "u_turn",
  "lemniscate",
  "custom",
];

export type SensorNoiseLevel = "low" | "medium" | "high";
export const SENSOR_NOISE_LEVELS: readonly SensorNoiseLevel[] = [
  "low",
  "medium",
  "high",
];

export type ObjectiveProfile =
  | "stable"
  | "fast"
  | "smooth"
  | "robust"
  | "custom";
export const OBJECTIVE_PROFILES: readonly ObjectiveProfile[] = [
  "stable",
  "fast",
  "smooth",
  "robust",
  "custom",
];

export type ScenarioType =
  | "nominal"
  | "noise_perturbed"
  | "wind_perturbed"
  | "combined_perturbed";

export interface StartPoint {
  x: number;
  y: number;
}

export interface WindVector {
  north: number;
  east: number;
  south: number;
  west: number;
}

export interface BaselineParameters {
  kp_xy: number;
  kd_xy: number;
  ki_xy: number;
  vel_limit: number;
  accel_limit: number;
  disturbance_rejection: number;
}

export interface TrackPoint {
  x: number;
  y: number;
  z?: number | null;
}

export interface ScenarioWindGusts {
  enabled: boolean;
  magnitude_mps: number;
  direction_deg: number;
  period_s: number;
}

export interface ScenarioObstacle {
  type: "cylinder" | "box";
  x: number;
  y: number;
  z: number;
  radius?: number | null;
  size_x?: number | null;
  size_y?: number | null;
  size_z?: number | null;
  height?: number | null;
}

export interface ScenarioSensorDegradation {
  gps_noise_m: number;
  baro_noise_m: number;
  imu_noise_scale: number;
  dropout_rate: number;
}

export interface ScenarioBattery {
  initial_percent: number;
  voltage_sag: boolean;
  mass_payload_kg?: number | null;
}

export interface ScenarioAdvancedConfig {
  wind_gusts?: ScenarioWindGusts | null;
  obstacles?: ScenarioObstacle[];
  sensor_degradation?: ScenarioSensorDegradation | null;
  battery?: ScenarioBattery | null;
}

export interface JobProgress {
  completed_trials: number;
  total_trials: number;
  current_phase: string | null;
}

export interface JobError {
  code: string;
  message: string;
}

// Phase 6: JobEvent rows embedded on job detail so the diagnostics panel
// can render without a second request. Payload shape varies by event_type
// and is treated as opaque JSON by the frontend.
export interface JobEventInfo {
  id: string;
  event_type: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

// Phase 6: mock artifact metadata returned by
// `GET /api/v1/jobs/{job_id}/artifacts`. No underlying files exist in the
// MVP — `storage_path` uses a `mock://` URI scheme.
export interface Artifact {
  id: string;
  owner_type: string;
  owner_id: string;
  artifact_type: string;
  display_name: string | null;
  storage_path: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  created_at: string;
}

export interface JobCreateRequest {
  track_type: TrackType;
  reference_track?: TrackPoint[] | null;
  start_point: StartPoint;
  altitude_m: number;
  wind: WindVector;
  sensor_noise_level: SensorNoiseLevel;
  objective_profile: ObjectiveProfile;
  advanced_scenario_config?: ScenarioAdvancedConfig | null;
  display_name?: string | null;
  baseline_parameters?: BaselineParameters;
  // Phase 8 optional execution-backend & auto-tuning fields. Omitting them
  // preserves the Phase 7 mock + heuristic behaviour.
  simulator_backend?: SimulatorBackend;
  optimizer_strategy?: OptimizerStrategy;
  max_iterations?: number;
  trials_per_candidate?: number;
  acceptance_criteria?: AcceptanceCriteria | null;
  openai?: OpenAIConfig | null;
}

export interface JobUpdateRequest {
  display_name?: string | null;
}

export interface JobRerunRequest {
  openai?: OpenAIConfig | null;
}
export interface DeleteJobResponse {
  id: string;
  deleted: boolean;
}

export interface Job {
  id: string;
  track_type: TrackType;
  reference_track: TrackPoint[] | null;
  start_point: StartPoint;
  altitude_m: number;
  wind: WindVector;
  sensor_noise_level: SensorNoiseLevel;
  objective_profile: ObjectiveProfile;
  advanced_scenario_config?: ScenarioAdvancedConfig | null;
  display_name?: string | null;
  baseline_parameters?: BaselineParameters;
  status: JobStatus;
  progress: JobProgress;
  baseline_candidate_id: string | null;
  best_candidate_id: string | null;
  source_job_id: string | null;
  batch_id?: string | null;
  latest_error: JobError | null;
  created_at: string;
  updated_at: string;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  failed_at: string | null;
  recent_events: JobEventInfo[];
  // Phase 8 — echoed back from the server so the UI can render the execution
  // backend and auto-tuning status. ``current_generation`` is 0 during the
  // baseline generation and increments as each LLM/heuristic generation
  // is dispatched.
  simulator_backend_requested: SimulatorBackend;
  optimizer_strategy: OptimizerStrategy;
  max_iterations: number;
  trials_per_candidate: number;
  acceptance_criteria: AcceptanceCriteria;
  current_generation: number;
  optimization_outcome: OptimizationOutcome | null;
  openai_model: string | null;
}

export interface TrialMetrics {
  rmse: number;
  max_error: number;
  overshoot_count: number;
  completion_time: number;
  crash_flag: boolean;
  timeout_flag: boolean;
  score: number;
  final_error: number;
  pass_flag: boolean;
  instability_flag: boolean;
}

export type CandidateSourceType = "baseline" | "optimizer" | "llm_optimizer";

// Phase 8: per-job execution backend and optimizer strategy selection.
export type SimulatorBackend = "mock" | "real_cli";
export const SIMULATOR_BACKENDS: readonly SimulatorBackend[] = ["mock", "real_cli"];

export type OptimizerStrategy = "none" | "heuristic" | "gpt" | "cma_es";
export const OPTIMIZER_STRATEGIES: readonly OptimizerStrategy[] = [
  "none",
  "heuristic",
  "gpt",
  "cma_es",
];

export type OptimizationOutcome =
  | "success"
  | "max_iterations_reached"
  | "no_usable_candidate"
  | "simulator_unavailable"
  | "llm_failed";

export interface AcceptanceCriteria {
  target_rmse: number | null;
  target_max_error: number | null;
  min_pass_rate: number;
}

export interface OpenAIConfig {
  // NEVER surfaced by API responses. Present only on create-job requests.
  api_key?: string;
  model?: string | null;
}

export interface TrialSummary {
  id: string;
  candidate_id: string;
  seed: number;
  scenario_type: ScenarioType;
  status: TrialStatus;
  score: number | null;
  // Phase 8 polish: per-trial pass/fail exposed so the Job Detail trial
  // table can render PASS / FAIL in addition to COMPLETED. ``null`` means
  // "no metric yet" (queued/running/failed-without-metrics).
  pass_flag: boolean | null;
  // Phase 5: candidate metadata exposed so the trial table can distinguish
  // baseline from optimizer rows and highlight the best candidate.
  candidate_label: string | null;
  candidate_source_type: CandidateSourceType | null;
  candidate_is_baseline: boolean;
  candidate_is_best: boolean;
  candidate_generation_index: number;
}

export interface Trial extends TrialSummary {
  job_id: string;
  attempt_count: number;
  worker_id: string | null;
  simulator_backend: string | null;
  failure_code: string | null;
  failure_reason: string | null;
  log_excerpt: string | null;
  metrics: TrialMetrics | null;
  queued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AggregatedMetrics {
  rmse: number;
  max_error: number;
  overshoot_count: number;
  completion_time: number;
  score: number;
}

export interface ComparisonPoint {
  metric: string;
  label: string;
  baseline: number;
  optimized: number;
  lower_is_better: boolean;
  unit: string | null;
}

export interface BestParameters {
  [key: string]: number | string | boolean;
}

export interface JobReport {
  job_id: string;
  best_candidate_id: string;
  summary_text: string;
  baseline_metrics: AggregatedMetrics;
  optimized_metrics: AggregatedMetrics;
  comparison: ComparisonPoint[];
  best_parameters: BestParameters;
  report_status: "PENDING" | "READY" | "FAILED";
  created_at: string;
  updated_at: string;
}

export interface PaginatedJobs {
  items: Job[];
  page: number;
  page_size: number;
  total: number;
}

export interface BatchCreateRequest {
  name: string;
  description?: string | null;
  jobs: JobCreateRequest[];
}

export interface BatchProgress {
  total_jobs: number;
  completed_jobs: number;
  failed_jobs: number;
  cancelled_jobs: number;
  running_jobs: number;
  queued_jobs: number;
  created_jobs: number;
  terminal_jobs: number;
}

export interface BatchJob {
  id: string;
  name: string;
  description: string | null;
  status: BatchStatus;
  progress: BatchProgress;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  cancelled_at: string | null;
}

export interface PaginatedBatchJobs {
  items: BatchJob[];
  total: number;
}

export interface JobCompareRequest {
  job_ids: string[];
}

export interface JobCompareItem {
  job_id: string;
  display_name?: string | null;
  baseline_parameters?: BaselineParameters;
  status: JobStatus;
  track_type: TrackType;
  simulator_backend: SimulatorBackend;
  optimizer_strategy: OptimizerStrategy;
  optimization_outcome: OptimizationOutcome | null;
  baseline_metrics: Record<string, unknown> | null;
  optimized_metrics: Record<string, unknown> | null;
  best_candidate_id: string | null;
  best_parameters: Record<string, unknown>;
  trial_count: number;
  completed_trial_count: number;
  failed_trial_count: number;
  created_at: string;
  completed_at: string | null;
}

export interface JobCompareResponse {
  items: JobCompareItem[];
}

export type JobsCompareRequest = JobCompareRequest;
export type JobsCompareResponse = JobCompareResponse;

// Standard API envelope (mirrors docs/04_API_SPEC.md §4). Exposed here so the
// mock client can mimic the wire format before unwrapping for callers.
export interface ApiError {
  code: string;
  message: string;
  details: unknown;
}

export type ApiEnvelope<T> =
  | { success: true; data: T; error: null }
  | { success: false; data: null; error: ApiError };

export const JOB_ACTIVE_STATUSES: readonly JobStatus[] = [
  "CREATED",
  "QUEUED",
  "RUNNING",
  "AGGREGATING",
];
