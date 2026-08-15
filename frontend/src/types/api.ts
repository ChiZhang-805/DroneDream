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

export type TrackType = "hover" | "circle" | "u_turn" | "lemniscate" | "custom";
export const TRACK_TYPES: readonly TrackType[] = [
  "hover",
  "circle",
  "u_turn",
  "lemniscate",
  "custom",
];

export type StarterExperienceTemplateKey =
  | "hover-basics@1"
  | "first-circle@1"
  | "light-wind-circle@1"
  | "wind-sensor-circle@1";
export type UserDefaultTrackType =
  | "hover"
  | "circle"
  | "u_turn"
  | "lemniscate";

export interface UserExperiencePreferences {
  schema_version: "1.0";
  saved: boolean;
  memory_enabled: boolean;
  locale: "en" | "zh-CN" | null;
  default_template_key: StarterExperienceTemplateKey | null;
  default_track_type: UserDefaultTrackType | null;
  default_altitude_m: number | null;
  retention_days: number;
  stored_content:
    "allowlisted_preferences_and_verified_structured_job_outcomes_only";
  updated_at: string | null;
}

export interface UserExperiencePreferencesUpdate {
  memory_enabled?: boolean;
  locale?: "en" | "zh-CN" | null;
  default_template_key?: StarterExperienceTemplateKey | null;
  default_track_type?: UserDefaultTrackType | null;
  default_altitude_m?: number | null;
}

export interface UserExperiencePreferencesMutation
  extends UserExperiencePreferences {
  deleted_memory_count: number;
}

export interface DeleteUserExperiencePreferencesResponse {
  deleted_preferences: boolean;
  deleted_memory_count: number;
  memory_enabled: false;
}

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
  | "actuator_failure"
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
  completion_policy?: CompletionPolicy;
  provider_turn_cap?: number;
  continue_exploration_after_qualified?: boolean;
  exploration_budget?: ContinueExplorationBudget | null;
}

export interface JobUpdateRequest {
  display_name?: string | null;
}

export interface JobRerunRequest {
  openai?: OpenAIConfig | null;
  llm?: LLMProviderConfig | null;
}

export type CompletionPolicy =
  | "first_qualified_stop"
  | "exploration_budget_stop";

export type JobKind = "primary" | "continue_exploration";

export interface ContinueExplorationBudget {
  additional_generation_cap: number;
  additional_trial_cap: number;
  additional_provider_turn_cap: number;
  additional_time_budget_seconds: number;
}

export interface ContinueExplorationRequest {
  budget: ContinueExplorationBudget;
  openai?: OpenAIConfig | null;
  llm?: LLMProviderConfig | null;
}
export interface DeleteJobResponse {
  id: string;
  deleted: boolean;
}

export interface Job {
  id: string;
  control_version: number;
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
  llm_access_mode?: "platform" | "byok" | null;
  llm_provider?: string | null;
  llm_base_url?: string | null;
  vehicle_profile?: VehicleProfileConfig;
  parameter_catalog_version?: string;
  parameter_space?: ParameterSpaceSelection[];
  objective_config?: ObjectiveConfig;
  scenario_suite?: ScenarioSuiteConfig;
  max_total_trials?: number;
  completion_policy?: CompletionPolicy;
  job_kind?: JobKind;
  cognitive_policy_version?: string;
  provider_turn_cap?: number;
  provider_turns_attempted?: number;
  provider_turns_succeeded?: number;
  first_qualified_candidate_id?: string | null;
  first_qualified_freeze_receipt_id?: string | null;
  first_qualified_at?: string | null;
  continue_exploration_requested?: boolean;
  exploration_budget?: ContinueExplorationBudget | null;
  continuation_parent_job_id?: string | null;
  continuation_root_job_id?: string | null;
  holdout_policy_version?: string;
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
  | "llm_failed"
  | "exploration_improved"
  | "exploration_no_improvement"
  | "exploration_budget_exhausted";

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
  access_mode?: "platform" | "byok";
  provider: string;
  api_key?: string | null;
  platform_grant?: string | null;
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

export interface ExperimentAssistantDocumentChunk {
  schema_version: "1.0";
  document_id: string;
  chunk_id: string;
  display_name: string;
  content: string;
  content_sha256: string;
  retention: "request_only";
}

export interface ExperimentAssistantDocumentContext {
  schema_version: "1.0";
  purpose: "experiment_draft_reference";
  chunks: ExperimentAssistantDocumentChunk[];
}

export interface ExperimentAssistantDocumentContextReceipt {
  schema_version: "1.0";
  retention: "request_only";
  persisted: false;
  chunk_count: number;
  content_bytes: number;
  context_sha256: string;
}

export interface ExperimentAssistantTurnRequest {
  message_id: string;
  message: string;
  locale: "en" | "zh-CN";
  conversation_summary: string;
  current_values: Record<string, ExperimentAssistantFieldValue>;
  explicit_field_ids: string[];
  current_parameters: ExperimentAssistantCurrentParameter[];
  document_context?: ExperimentAssistantDocumentContext | null;
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
  document_context_receipt?: ExperimentAssistantDocumentContextReceipt | null;
  usage: ExperimentAssistantUsage;
  provider: string;
  model: string;
  assistant_message?: string;
  orchestration?: {
    run_id: string;
    conversation_id: string;
    tenant_id: string;
    organization_id: string | null;
    workspace_id: string;
    edition: "universal" | "sim" | "lab" | "field";
    artifact_id: string;
    artifact_version: number;
    product_link: string;
    artifact_kind:
        | "autonomy_mission_plan"
        | "universal_vehicle_model"
        | "universal_simulation_experiment"
        | "universal_cross_edition_workflow"
        | "simulation_experiment"
        | "lab_simulation_experiment"
        | "lab_hardware_validation"
        | "lab_calibration_workflow"
        | "lab_sim_to_real_workflow"
        | "lab_real_to_sim_workflow"
        | "field_task_plan";
    artifact_payload?: Record<string, unknown>;
    sequence: number;
    intent: string | null;
    workflow: Array<{
      step: string;
      label: string;
      status: "completed" | "needs_input";
    }>;
    generated_files?: Array<{
      file_id: string;
      display_name: string;
      content_type: string;
      byte_size: number;
      content_sha256: string;
      version: number;
    }>;
  };
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

export interface AuthenticatedSessionResponse {
  status: "ready";
  user_id: string;
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
  failure_code: string | null;
  failure_reason: string | null;
}

export interface Trial extends TrialSummary {
  job_id: string;
  attempt_count: number;
  worker_id: string | null;
  simulator_backend: string | null;
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
  winner_evidence_id?: string | null;
  winner_freeze_receipt_id?: string | null;
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
  control_version: number;
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

export type AutonomyEdition = "universal" | "sim" | "lab" | "field";
export type AutonomyExecutionTarget = "simulation" | "hitl" | "hardware";
export type AutonomyPerceptionMode = "map" | "vision" | "fusion";

export interface AutonomyVehicleEnvelope {
  dry_mass_kg: number;
  launch_payload_kg: number;
  pickup_payload_kg: number;
  max_takeoff_mass_kg: number;
  max_total_thrust_n: number;
  radius_m: number;
  max_speed_mps: number;
  max_acceleration_mps2: number;
  reserve_battery_percent: number;
}

export interface AutonomyRuntimeEvidence {
  simulation_qualified: boolean;
  signed_vehicle_pack_id: string | null;
  operator_confirmed: boolean;
  localization_ready: boolean;
  link_ready: boolean;
  geofence_ready: boolean;
  battery_ready: boolean;
}

export interface AutonomyHarnessAsset {
  kind: "aircraft" | "map";
  asset_id: string;
  name: string;
  version: number;
  status: string;
  content_hash: string | null;
  qualification_receipt_id: string | null;
  capabilities: Record<string, string | number | boolean | string[] | null>;
}

export interface AutonomyHarnessInspectRequest {
  schema_version: "dronedream.autonomy.harness-inspect.v1";
  edition: AutonomyEdition;
  natural_language: string;
  aircraft: AutonomyHarnessAsset;
  map_pack: AutonomyHarnessAsset;
}

export interface AutonomyHarnessToolReceipt {
  tool_id: string;
  tool_version: string;
  outcome: "accepted" | "blocked";
  evidence: Record<string, string | number | boolean | string[] | null>;
  issue_codes: string[];
}

export interface AutonomyHarnessInspectResponse {
  schema_version: "dronedream.autonomy.harness-context.v1";
  prompt_version: "dronedream.autonomy.system.v1";
  tool_registry_version: "dronedream.autonomy.tools.v1";
  context_sha256: string;
  status: "needs_assets" | "needs_input" | "draft" | "blocked";
  planning_ready: boolean;
  blockers: string[];
  required_next_actions: string[];
  eligible_tool_ids: string[];
  tool_receipts: AutonomyHarnessToolReceipt[];
  repair_policy: {
    schema_version: "dronedream.autonomy.repair-policy.v1";
    semantic_attempt_limit: number;
    trajectory_attempt_limit: number;
    repeated_plan_hash_limit: number;
    may_relax_safety_constraints: false;
  };
}

export interface AutonomyCompileAssetContext {
  schema_version: "dronedream.autonomy.compile-assets.v1";
  harness_context_sha256: string;
  aircraft: AutonomyHarnessAsset;
  map_pack: AutonomyHarnessAsset;
}

export interface AutonomyCompileRequest {
  edition: AutonomyEdition;
  execution_target: AutonomyExecutionTarget;
  natural_language: string;
  scene_id: string;
  perception_mode: AutonomyPerceptionMode;
  vehicle: AutonomyVehicleEnvelope;
  evidence: AutonomyRuntimeEvidence;
  asset_context: AutonomyCompileAssetContext | null;
}

export interface AutonomyRoutePoint {
  x: number;
  y: number;
  z: number;
  phase: "launch" | "transit" | "stairs" | "gate" | "pickup" | "return" | "land";
  speed_limit_mps: number;
}

export type AutonomyTaskStatus =
  | "pending"
  | "ready"
  | "active"
  | "blocked"
  | "completed"
  | "failed"
  | "skipped";

export interface AutonomyTaskNode {
  task_id: string;
  label: string;
  status: AutonomyTaskStatus;
  depends_on: string[];
  executor:
    | "language_model"
    | "mission_executive"
    | "perception"
    | "global_planner"
    | "local_planner"
    | "payload_controller"
    | "px4_bridge"
    | "operator";
  risk: "low" | "medium" | "high" | "critical";
  max_retries: number;
  timeout_s: number;
  fallback: "continue" | "hold" | "land" | "abort";
  expected_output: string;
  completion_evidence: string[];
  inserted_by: "compiler" | "runtime" | "operator";
}

export interface AutonomyTaskGraph {
  schema_version: "dronedream.autonomy.task-graph.v1";
  revision: number;
  nodes: AutonomyTaskNode[];
  active_node_ids: string[];
  change_reason: string;
}

export interface AutonomyPerceivedEntity {
  track_id: string;
  kind: "person" | "vehicle" | "animal" | "obstacle" | "unknown";
  position_m: { x: number; y: number; z: number };
  velocity_mps: { x: number; y: number; z: number };
  confidence: number;
  safety_radius_m: number;
  age_ms: number;
  source_stream: string;
}

export interface AutonomyPerceptionStreamHealth {
  stream_id: string;
  kind: "rgb" | "depth" | "stereo" | "thermal" | "lidar" | "vio" | "slam" | "map";
  source: "simulator" | "onboard" | "cloud" | "external";
  status: "healthy" | "degraded" | "stale" | "offline";
  rate_hz: number;
  latency_ms: number;
  dropped_percent: number;
}

export interface AutonomyCompileResponse {
  scene: {
    id: string;
    name: string;
    summary: string;
    bounds_m: { x: number; y: number; z: number };
    floors: number;
    minimum_clearance_m: number;
    objects: Array<{
      id: string;
      kind: string;
      center: { x: number; y: number; z: number };
      size: { x: number; y: number; z: number };
      traversable: boolean;
      required_clearance_m: number;
    }>;
    reference_path: AutonomyRoutePoint[];
    tags: string[];
  };
  contract: {
    schema_version: "dronedream.autonomy.mission.v2";
    contract_id: string;
    edition: AutonomyEdition;
    execution_target: AutonomyExecutionTarget;
    scene_id: string;
    perception_mode: AutonomyPerceptionMode;
    intent: string;
    steps: Array<{
      order: number;
      action: string;
      label: string;
      payload_delta_kg: number;
    }>;
    task_graph: AutonomyTaskGraph;
    immutable_safety_rules: string[];
  };
  trajectory: AutonomyRoutePoint[];
  feasible: boolean;
  issues: Array<{ code: string; severity: "info" | "warning" | "error"; message: string }>;
  metrics: {
    route_length_m: number;
    vertical_travel_m: number;
    estimated_duration_s: number;
    minimum_clearance_m: number;
    launch_mass_kg: number;
    post_pickup_mass_kg: number;
    post_pickup_thrust_to_weight: number;
    braking_distance_m: number;
  };
  execution_policy: {
    readiness: "simulation_ready" | "preview_only" | "denied";
    adapter: "px4_gazebo_contract" | "hitl_contract" | "hardware_contract";
    can_execute: boolean;
    validated_signed_pack_count: number;
    blockers: string[];
    required_next_steps: string[];
  };
  planner: Record<string, string>;
  runtime_profile: {
    schema_version: "dronedream.autonomy.runtime-profile.v1";
    mode: "simulation_contract" | "hitl_shadow" | "hardware_locked";
    bridge: "px4_gazebo" | "px4_hitl_shadow" | "px4_hardware_locked";
    command_authority: boolean;
    persistence: "process_local_bounded";
    observation_contract: "dronedream.autonomy.observation.v1";
    components: Array<{
      id:
        | "mission_executive"
        | "perception_vio_slam"
        | "world_model"
        | "global_planner"
        | "local_planner"
        | "trajectory_tracker"
        | "px4_bridge"
        | "safety_supervisor"
        | "evidence_recorder";
      status: "available" | "shadow" | "locked";
      role: string;
      rate_hz: number | null;
      actuator_authority: boolean;
    }>;
    fail_safe_actions: Array<"continue" | "hold" | "land" | "abort">;
  };
}

export interface AutonomyRuntimeObservation {
  schema_version?: "dronedream.autonomy.observation.v1";
  sequence: number;
  monotonic_ms: number;
  armed: boolean;
  landed: boolean;
  position_m: { x: number; y: number; z: number };
  velocity_mps: { x: number; y: number; z: number };
  localization_covariance_m2: number;
  perception_age_ms: number;
  minimum_clearance_m: number;
  battery_percent: number;
  link_ok: boolean;
  geofence_ok: boolean;
  payload_mass_kg: number;
  mission_progress: number;
  pickup_confirmed?: boolean;
  local_replan_active?: boolean;
  emergency_stop?: boolean;
  perceived_entities?: AutonomyPerceivedEntity[];
  stream_health?: AutonomyPerceptionStreamHealth[];
}

export interface AutonomyRuntimeSession {
  schema_version: "dronedream.autonomy.runtime-session.v1";
  session_id: string;
  contract_id: string;
  execution_target: AutonomyExecutionTarget;
  phase:
    | "ready"
    | "takeoff"
    | "navigating"
    | "pickup"
    | "replanning"
    | "returning"
    | "landing"
    | "holding"
    | "completed"
    | "aborted";
  bridge: string;
  command_authority: boolean;
  created_at: string;
  updated_at: string;
  latest_sequence: number;
  latest_monotonic_ms: number;
  observation_count: number;
  decision: {
    action: "continue" | "hold" | "land" | "abort";
    accepted: boolean;
    codes: string[];
  };
  task_graph: AutonomyTaskGraph;
  perceived_entities: AutonomyPerceivedEntity[];
  stream_health: AutonomyPerceptionStreamHealth[];
  decision_events: Array<{
    revision: number;
    created_at: string;
    kind: "session" | "task_transition" | "dynamic_entity" | "safety" | "operator";
    code: string;
    summary: string;
    task_ids: string[];
    entity_ids: string[];
  }>;
  evidence_chain_head: string;
  terminal: boolean;
}

export interface AutonomyVehiclePackQualificationRequest {
  pack_id: string;
  version: number;
  autopilot: "px4" | "ardupilot" | "custom";
  firmware: string;
  flight_controller: string;
  control_interface: "px4-ros2" | "mavsdk" | "mavlink" | "simulation-only";
  dry_mass_kg: number;
  max_takeoff_mass_kg: number;
  max_total_thrust_n: number;
  body_size_m: { x: number; y: number; z: number };
  rotor_radius_m: number;
  center_of_gravity_m: { x: number; y: number; z: number };
  inertia_kg_m2: { x: number; y: number; z: number };
  battery_energy_wh: number;
  reserve_battery_percent: number;
  maximum_pickup_payload_kg: number;
  maximum_speed_mps: number;
  maximum_acceleration_mps2: number;
  maximum_climb_mps: number;
  maximum_descent_mps: number;
  command_link_latency_ms: number;
  command_link_bandwidth_mbps: number;
  sensors: Array<{
    sensor_id: string;
    kind: "rgb" | "depth" | "stereo" | "thermal" | "lidar" | "gps" | "vio";
    calibrated: boolean;
    calibration_status: "unverified" | "verified" | "expired" | "failed";
    position_m: { x: number; y: number; z: number };
    roll_pitch_yaw_deg: { x: number; y: number; z: number };
    rate_hz: number;
    calibration_age_days: number;
  }>;
}

export interface AutonomyQualificationIssue {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
}

export interface AutonomyVehiclePackQualificationReceipt {
  schema_version: "dronedream.autonomy.vehicle-pack-receipt.v1";
  receipt_id: string;
  pack_id: string;
  version: number;
  status: "blocked" | "validated_unsigned";
  content_sha256: string;
  planning_radius_m: number;
  maximum_loaded_mass_kg: number;
  loaded_thrust_to_weight: number;
  issues: AutonomyQualificationIssue[];
  created_at: string;
  hardware_authority: false;
}

export interface AutonomyMapAssetAdmissionReceipt {
  schema_version: "dronedream.autonomy.map-asset-receipt.v1";
  receipt_id: string;
  filename: string;
  format: string;
  byte_size: number;
  content_sha256: string;
  parser: string;
  status: "admitted" | "rejected";
  layers: Array<"mesh" | "point-cloud" | "semantic" | "georeference">;
  issues: AutonomyQualificationIssue[];
  created_at: string;
  planning_qualified: false;
}

export interface AutonomyMapPackQualificationRequest {
  schema_version: "dronedream.autonomy.map-pack-qualification.v1";
  name: string;
  pack_id: string;
  version: number;
  compiler_scene_id: string;
  representation: "hybrid-3d" | "mesh" | "point-cloud" | "occupancy" | "terrain";
  coordinate_frame: "ENU" | "NED" | "WGS84" | "building-local";
  resolution_m: number;
  floor_count: number;
  bounds_m: { x: number; y: number; z: number };
  origin: { latitude: number | null; longitude: number | null; altitude_m: number | null };
  live_updates: "vision-slam" | "depth-fusion" | "lidar-fusion" | "fixed";
  calibrated: boolean;
  confidence_percent: number;
  semantic_layers: Array<
    | "free-space"
    | "stairs"
    | "doors"
    | "gates"
    | "people"
    | "pickup-zones"
    | "launch-zones"
    | "rooms"
    | "corridors"
    | "roads"
    | "vegetation"
    | "street-furniture"
  >;
  planning_layers: Array<"collision-geometry" | "occupancy" | "esdf" | "dynamic-overlay" | "confidence">;
  source_asset_receipt_ids: string[];
}

export interface AutonomyMapPackQualificationReceipt {
  schema_version: "dronedream.autonomy.map-pack-receipt.v1";
  receipt_id: string;
  pack_id: string;
  version: number;
  status: "blocked" | "qualified";
  content_sha256: string;
  manifest_sha256: string;
  compiler_scene_id: string;
  coordinate_frame: "ENU" | "NED" | "WGS84" | "building-local";
  resolution_m: number;
  semantic_layers: AutonomyMapPackQualificationRequest["semantic_layers"];
  planning_layers: AutonomyMapPackQualificationRequest["planning_layers"];
  issues: AutonomyQualificationIssue[];
  created_at: string;
  hardware_authority: false;
}

export interface AutonomyBundledMapManifest {
  schema_version: "dronedream.autonomy.bundled-map-manifest.v1";
  compiler_scene_id: string;
  name: string;
  representation: AutonomyMapPackQualificationRequest["representation"];
  coordinate_frame: AutonomyMapPackQualificationRequest["coordinate_frame"];
  resolution_m: number;
  floor_count: number;
  bounds_m: { x: number; y: number; z: number };
  confidence_percent: number;
  semantic_layers: AutonomyMapPackQualificationRequest["semantic_layers"];
  planning_layers: AutonomyMapPackQualificationRequest["planning_layers"];
  manifest_sha256: string;
}

export interface AutonomySceneCatalogResponse {
  schema_version: "dronedream.autonomy.scene-catalog.v1";
  items: Array<{
    id: string;
    name: string;
    map_pack_manifest: AutonomyBundledMapManifest;
  }>;
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
