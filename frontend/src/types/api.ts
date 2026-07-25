// Type definitions for the live /api/v1 contract. Backend schemas and the
// generated runtime evidence must remain compatible with these wire shapes.

export type JobStatus =
  | "CREATED"
  | "QUEUED"
  | "RUNNING"
  | "AGGREGATING"
  | "FINALIZING"
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
  "FINALIZING",
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
  | "combined_perturbed"
  | "turbulence"
  | "gps_dropout"
  | "payload_changed"
  | "battery_degraded"
  | "actuator_delay"
  | "custom";

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

// Artifact metadata returned by `GET /api/v1/jobs/{job_id}/artifacts`.
// Runtime-backed artifacts can be downloaded through the artifact endpoint;
// deterministic mock simulations may still expose metadata-only `mock://` rows.
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
  llm?: LLMProviderConfig | null;
  vehicle_profile?: VehicleProfileConfig;
  parameter_catalog_version?: string;
  parameter_space?: ParameterSpaceSelection[];
  objective_config?: ObjectiveConfig;
  scenario_suite?: ScenarioSuiteConfig;
  max_total_trials?: number;
}

export interface JobUpdateRequest {
  display_name?: string | null;
}

export interface JobRerunRequest {
  openai?: OpenAIConfig | null;
  llm?: LLMProviderConfig | null;
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
  llm_provider?: string | null;
  llm_base_url?: string | null;
  vehicle_profile?: VehicleProfileConfig;
  parameter_catalog_version?: string;
  parameter_space?: ParameterSpaceSelection[];
  objective_config?: ObjectiveConfig;
  scenario_suite?: ScenarioSuiteConfig;
  max_total_trials?: number;
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

export type OptimizerStrategy =
  | "none"
  | "heuristic"
  | "gpt"
  | "llm_harness"
  | "cma_es"
  | "constrained_mobo"
  | "multi_fidelity_mobo"
  | "turbo"
  | "saasbo"
  | "surrogate_cma_es"
  | "bipop_cma_es"
  | "optimizer_portfolio";

export const EXPERIMENTAL_OPTIMIZER_STRATEGIES = [
  "constrained_mobo",
  "multi_fidelity_mobo",
  "turbo",
  "saasbo",
  "surrogate_cma_es",
  "bipop_cma_es",
  "optimizer_portfolio",
] as const satisfies readonly OptimizerStrategy[];

export const HARNESS_OPTIMIZER_STRATEGIES = [
  "llm_harness",
] as const satisfies readonly OptimizerStrategy[];

export const LEGACY_OPTIMIZER_STRATEGIES = [
  "none",
  "heuristic",
  "gpt",
  "cma_es",
] as const satisfies readonly OptimizerStrategy[];

export const OPTIMIZER_STRATEGIES: readonly OptimizerStrategy[] = [
  ...HARNESS_OPTIMIZER_STRATEGIES,
  ...EXPERIMENTAL_OPTIMIZER_STRATEGIES,
  ...LEGACY_OPTIMIZER_STRATEGIES,
];

export function optimizerUsesModelAccess(strategy: OptimizerStrategy): boolean {
  return strategy === "gpt" || strategy === "llm_harness";
}

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
  api_key: string;
  model?: string | null;
}

export interface LLMProviderConfig {
  provider: string;
  api_key: string;
  model?: string | null;
  base_url?: string | null;
}

export type ExperimentAssistantFieldValue = string | number | boolean;
export type ExperimentAssistantPatchSource =
  | "explicit"
  | "derived"
  | "proposed_default";

export interface ExperimentAssistantPatch {
  field_id: string;
  value: ExperimentAssistantFieldValue;
  provenance: ExperimentAssistantPatchSource;
  source_message_id: string | null;
}

export interface ExperimentAssistantParameterPatch {
  name: string;
  selected: boolean;
  baseline: number | null;
  search_min: number | null;
  search_max: number | null;
  scale: ParameterScale | null;
  provenance: ExperimentAssistantPatchSource;
  source_message_id: string | null;
}

export interface ExperimentAssistantRejectedPatch {
  field_id: string;
  code: string;
  message: string;
}

export interface ExperimentAssistantQuestion {
  field_ids: string[];
  question: string;
}

export interface ExperimentAssistantUsage {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  estimated: boolean;
}

export interface ExperimentAssistantCurrentParameter {
  name: string;
  selected: boolean;
  baseline: number;
  search_min: number;
  search_max: number;
  scale: ParameterScale;
}

export interface ExperimentAssistantTurnRequest {
  message_id: string;
  message: string;
  locale: "en" | "zh-CN";
  conversation_summary: string;
  current_values: Record<string, ExperimentAssistantFieldValue>;
  explicit_field_ids: string[];
  current_parameters: ExperimentAssistantCurrentParameter[];
  llm: LLMProviderConfig;
}

export interface ExperimentAssistantTurnResponse {
  schema_version: "1.0";
  experiment_summary: string;
  accepted_patches: ExperimentAssistantPatch[];
  rejected_patches: ExperimentAssistantRejectedPatch[];
  accepted_parameter_patches: ExperimentAssistantParameterPatch[];
  rejected_parameter_patches: ExperimentAssistantRejectedPatch[];
  missing_field_ids: string[];
  review_field_ids: string[];
  questions: ExperimentAssistantQuestion[];
  usage: ExperimentAssistantUsage;
  provider: string;
  model: string;
}

export interface VehicleProfileConfig {
  px4_version: string;
  firmware_commit?: string | null;
  vehicle_type: string;
  airframe: string;
  simulator_model: string;
  world: string;
  headless: boolean;
  simulation_speed_factor: number;
  instance_id: number;
}

export type ParameterValueType = "float" | "integer" | "boolean" | "enum";

export interface ParameterSpaceSelection {
  name: string;
  baseline: number;
  minimum: number;
  maximum: number;
  step?: number | null;
  scale: ParameterScale;
  value_type: ParameterValueType;
  choices?: number[] | null;
  enabled: boolean;
  locked: boolean;
}

export type ObjectiveDirection = "minimize" | "maximize";
export type ConstraintOperator = "lt" | "lte" | "gt" | "gte" | "eq";
export type RobustAggregation = "mean" | "worst" | "cvar" | "percentile";

export interface ObjectiveSpec {
  metric: string;
  direction: ObjectiveDirection;
  weight: number;
  normalization: number;
  target?: number | null;
}

export interface ConstraintSpec {
  metric: string;
  operator: ConstraintOperator;
  threshold: number;
  hard: boolean;
  penalty: number;
}

export interface ObjectiveConfig {
  objectives: ObjectiveSpec[];
  constraints: ConstraintSpec[];
  robust_aggregation: RobustAggregation;
  cvar_alpha: number;
  percentile: number;
}

export interface ScenarioCaseConfig {
  id: string;
  scenario_type: ScenarioType;
  seeds: number[];
  weight: number;
  enabled: boolean;
  holdout: boolean;
  config: Record<string, unknown>;
}

export interface ScenarioSuiteConfig {
  cases: ScenarioCaseConfig[];
  common_random_numbers: boolean;
}

// Progressive Study configuration used by the Phase 2 experiment wizard.
// The current Job API does not require these fields. The frontend persists the
// configuration alongside the created job and can opt into sending it once a
// backend advertises Study support.
export type TuningMode = "basic" | "advanced" | "expert";
export type ParameterRisk = "low" | "medium" | "high";
export type ParameterScale = "linear" | "log";
export type ParameterExpertise = "guided" | "advanced" | "expert";
export type ParameterApplyPolicy = "live" | "disarmed" | "reboot";

export interface LocalizedParameterText {
  en: string;
  "zh-CN": string;
}

export interface ParameterChoiceDefinition {
  value: number;
  label: LocalizedParameterText;
}

export interface ParameterCompatibilityDefinition {
  px4_versions: string[];
  vehicle_types: string[];
  airframe_families: string[];
}

export interface PX4ParameterDefinition {
  name: string;
  label: string;
  localized_label?: Partial<Record<"en" | "zh-CN", string>>;
  group: string;
  description: string;
  localized_description?: Partial<Record<"en" | "zh-CN", string>>;
  unit: string | null;
  value_type: "float" | "integer";
  default_value: number;
  absolute_min: number;
  absolute_max: number;
  safe_min: number;
  safe_max: number;
  step: number;
  scale: ParameterScale;
  risk: ParameterRisk;
  requires_reboot: boolean;
  dependencies: string[];
  supported_airframes: string[];
  control_loop?: string;
  axes?: string[];
  tuning_stage?: number;
  expertise?: ParameterExpertise;
  apply_policy?: ParameterApplyPolicy;
  compatibility?: ParameterCompatibilityDefinition;
  application_interfaces?: string[];
  recommended_metrics?: string[];
  evidence_signals?: string[];
  flight_modes?: string[];
  preconditions?: string[];
  risk_note?: LocalizedParameterText | null;
  source_url?: string | null;
  bounds_source?: "px4" | "px4_and_dronedream_guardrail";
  choices?: ParameterChoiceDefinition[];
  legacy_key?: keyof BaselineParameters | null;
}

export interface ParameterCatalogResponse {
  catalog_version?: string;
  px4_version: string;
  source: "backend" | "builtin";
  parameters: PX4ParameterDefinition[];
}

export interface ParameterCatalogApiItem {
  name: string;
  type: "float" | "int" | "integer";
  unit: string;
  hard_bounds: { min: number; max: number };
  safe_bounds: { min: number; max: number };
  step: number;
  default: number;
  group: string;
  risk: ParameterRisk;
  requires_reboot: boolean;
  label: { en: string; "zh-CN": string };
  description: { en: string; "zh-CN": string };
  dependencies: Array<{
    kind: string;
    parameter: string;
    description: { en: string; "zh-CN": string };
  }>;
  control_loop?: string;
  axes?: string[];
  tuning_stage?: number;
  expertise?: ParameterExpertise;
  apply_policy?: ParameterApplyPolicy;
  compatibility?: ParameterCompatibilityDefinition;
  application_interfaces?: string[];
  recommended_metrics?: string[];
  evidence_signals?: string[];
  flight_modes?: string[];
  preconditions?: string[];
  risk_note?: LocalizedParameterText | null;
  source_url?: string | null;
  bounds_source?: "px4" | "px4_and_dronedream_guardrail";
  choices?: ParameterChoiceDefinition[];
}

export interface ParameterCatalogApiResponse {
  catalog_version: string;
  source: string;
  px4_version: string;
  supported_px4_versions: string[];
  vehicle_type: string;
  parameter_count: number;
  parameters: ParameterCatalogApiItem[];
}

export interface BackendCapabilityItem {
  ready: boolean;
  status: string;
  reason?: string | null;
  selectable?: boolean;
  configured?: boolean;
  requires_external_runtime?: boolean;
  requires_user_api_key?: boolean;
  result_protocol?: string;
  custom_base_url_allowlist_configured?: boolean;
  max_concurrency_per_host_without_instance_allocator?: number;
  instance_allocation?: string;
  physical_fidelity?: boolean;
  purpose?: string;
  catalog_parameter_effects?: string;
  supported_scenarios?: string[];
  bundled_runner_advanced_effects?: string[];
  scenario_effect_contract?: {
    schema_version: string;
    physically_applied: string[];
    obstacles?: {
      status: string;
      mechanism: string;
      requires: string[];
      evidence: string;
    };
    requires_runtime_extension: string[];
  };
  unverified_effect_passthrough_opt_in?: boolean;
  experimental?: boolean;
  selection_profile?: string;
}

export interface BackendCapabilitiesResponse {
  service_version: string;
  features?: Record<
    string,
    {
      available: boolean;
      schema_version?: string;
      decision_schema_version?: string;
      draft_only?: boolean;
      tool_registry?: string;
    }
  >;
  simulators: {
    configuration_scope: "api_process" | string;
    authoritative: boolean;
    worker_override: string | null;
    worker_override_supported: boolean;
    items: Record<string, BackendCapabilityItem>;
  };
  optimizers: {
    configuration_scope?: "api_process" | string;
    authoritative: boolean;
    selection_profile?: string;
    recommended_strategy?: OptimizerStrategy;
    experimental_strategy_ids?: OptimizerStrategy[];
    items: Record<string, BackendCapabilityItem>;
  };
  parameter_catalog: {
    catalog_version: string;
    supported_px4_versions: string[];
  };
}

export interface StudyParameterSelection {
  name: string;
  baseline: number;
  search_min: number;
  search_max: number;
  scale: ParameterScale;
}

export interface ExperimentStudyConfig {
  schema_version: 1;
  tuning_mode: TuningMode;
  vehicle: {
    px4_version: string;
    airframe: string;
    gazebo_model: string;
    gazebo_world: string;
  };
  parameters: StudyParameterSelection[];
  objectives: {
    profile: ObjectiveProfile;
    weights: {
      tracking: number;
      speed: number;
      smoothness: number;
      robustness: number;
    };
    hard_constraints: AcceptanceCriteria;
  };
  scenario_plan: {
    search_seeds: number[];
    holdout_seeds: number[];
    advanced_enabled: boolean;
  };
  budget: {
    max_iterations: number;
    trials_per_candidate: number;
    estimated_trials: number;
  };
  compatibility: {
    legacy_job_api: boolean;
    unmapped_parameters: string[];
  };
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
  candidate_optimizer_strategy?: OptimizerStrategy | null;
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
  max_error_mean?: number | null;
  max_error_worst?: number | null;
  overshoot_count: number;
  completion_time: number;
  score: number;
  completion_rate?: number | null;
  failure_rate?: number | null;
  pass_rate?: number | null;
  holdout?: HoldoutValidationMetrics | null;
}

export interface HoldoutValidationMetrics {
  validation_status: "passed" | "failed" | "incomplete" | "error";
  feasible: boolean;
  objective_feasible: boolean | null;
  trial_count: number;
  completed_trial_count: number;
  failed_trial_count: number;
  passing_trial_count: number;
  completion_rate: number;
  failure_rate: number;
  pass_rate: number;
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

export interface Candidate {
  id: string;
  generation_index: number;
  source_type: string;
  label: string | null;
  parameters: Record<string, unknown>;
  proposal_reason: string | null;
  optimizer_metadata?: Record<string, unknown> | null;
  parent_candidate_id: string | null;
  aggregated_score: number | null;
  aggregated_metrics: Record<string, unknown> | null;
  objective_values: Record<string, number> | null;
  feasible: boolean | null;
  total_constraint_violation: number | null;
  trial_count: number;
  completed_trial_count: number;
  failed_trial_count: number;
  rank_in_job: number | null;
  is_best: boolean;
  is_baseline: boolean;
  created_at: string;
  updated_at: string;
}

export interface OptimizationHistory {
  items: Candidate[];
  pareto_candidate_ids: string[];
  recommendations: Record<string, string>;
  objective_directions: Record<string, ObjectiveDirection>;
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
  page: number;
  page_size: number;
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
