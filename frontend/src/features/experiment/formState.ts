import {
  OBJECTIVE_PROFILES,
  OPTIMIZER_STRATEGIES,
  SENSOR_NOISE_LEVELS,
  SIMULATOR_BACKENDS,
  TRACK_TYPES,
} from "../../types/api";
import type {
  ObjectiveProfile,
  OptimizerStrategy,
  RobustAggregation,
  SensorNoiseLevel,
  SimulatorBackend,
  TrackType,
  TuningMode,
} from "../../types/api";
import type { ExperimentDraftSchema } from "./draftStorage";
import type { ParameterSelectionMap } from "./parameterCatalog";

export type ScenarioPreset = "nominal" | "wind" | "sensor" | "stress";

/**
 * The single editable state shared by conversational drafting and the manual
 * five-step builder. Values stay string-backed where the form needs to
 * preserve an unfinished numeric edit; the final request compiler remains the
 * authority that converts them to domain values.
 */
export interface ExperimentFormState {
  tuning_mode: TuningMode;
  display_name: string;
  px4_version: string;
  firmware_commit: string;
  vehicle_type: string;
  airframe: string;
  simulator_model: string;
  simulator_world: string;
  simulator_headless: boolean;
  simulation_speed_factor: string;
  instance_id: string;
  track_type: TrackType;
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
  objective_weight_tracking: string;
  objective_weight_speed: string;
  objective_weight_smoothness: string;
  objective_weight_robustness: string;
  robust_aggregation: RobustAggregation;
  cvar_alpha: string;
  percentile: string;
  simulator_backend: SimulatorBackend;
  optimizer_strategy: OptimizerStrategy;
  max_iterations: string;
  trials_per_candidate: string;
  max_total_trials: string;
  continue_exploration_after_qualified: boolean;
  exploration_additional_generations: string;
  exploration_additional_trials: string;
  exploration_additional_provider_turns: string;
  exploration_additional_time_minutes: string;
  target_rmse: string;
  target_max_error: string;
  min_pass_rate: string;
  llm_access_mode: "platform" | "byok";
  llm_provider: string;
  llm_api_key: string;
  llm_model: string;
  llm_base_url: string;
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
  search_seeds: string;
  holdout_seeds: string;
  nominal_search_enabled: boolean;
  wind_search_enabled: boolean;
  noise_search_enabled: boolean;
  nominal_holdout_enabled: boolean;
  combined_holdout_enabled: boolean;
  common_random_numbers: boolean;
  scenario_preset: ScenarioPreset;
}

export const EXPERIMENT_FORM_DEFAULTS: ExperimentFormState = {
  tuning_mode: "basic",
  display_name: "",
  px4_version: "v1.16",
  firmware_commit: "",
  vehicle_type: "multicopter",
  airframe: "x500",
  simulator_model: "gz_x500",
  simulator_world: "default",
  simulator_headless: true,
  simulation_speed_factor: "1",
  instance_id: "0",
  track_type: "circle",
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
  objective_weight_tracking: "1",
  objective_weight_speed: "0.25",
  objective_weight_smoothness: "0.35",
  objective_weight_robustness: "1",
  robust_aggregation: "cvar",
  cvar_alpha: "0.2",
  percentile: "95",
  simulator_backend: "mock",
  optimizer_strategy: "optimizer_portfolio",
  max_iterations: "12",
  trials_per_candidate: "3",
  max_total_trials: "220",
  continue_exploration_after_qualified: false,
  exploration_additional_generations: "4",
  exploration_additional_trials: "80",
  exploration_additional_provider_turns: "16",
  exploration_additional_time_minutes: "60",
  target_rmse: "0.5",
  target_max_error: "",
  min_pass_rate: "0.8",
  llm_access_mode: "platform",
  llm_provider: "openai",
  llm_api_key: "",
  llm_model: "",
  llm_base_url: "",
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
  search_seeds: "101, 202, 303",
  holdout_seeds: "901, 902",
  nominal_search_enabled: true,
  wind_search_enabled: false,
  noise_search_enabled: false,
  nominal_holdout_enabled: true,
  combined_holdout_enabled: false,
  common_random_numbers: true,
  scenario_preset: "nominal",
};

const DRAFT_ENUM_VALUES: Partial<
  Record<keyof ExperimentFormState, readonly string[]>
> = {
  tuning_mode: ["basic", "advanced", "expert"],
  track_type: TRACK_TYPES,
  sensor_noise_level: SENSOR_NOISE_LEVELS,
  objective_profile: OBJECTIVE_PROFILES,
  robust_aggregation: ["mean", "worst", "cvar", "percentile"],
  simulator_backend: SIMULATOR_BACKENDS,
  optimizer_strategy: OPTIMIZER_STRATEGIES,
  llm_access_mode: ["platform", "byok"],
  llm_provider: ["openai", "qwen", "deepseek", "custom"],
  scenario_preset: ["nominal", "wind", "sensor", "stress"],
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function normalizeExperimentDraftForm(
  value: unknown,
): ExperimentFormState | null {
  if (!isRecord(value)) return null;
  const normalized: Record<string, unknown> = { ...EXPERIMENT_FORM_DEFAULTS };
  for (
    const key of Object.keys(EXPERIMENT_FORM_DEFAULTS) as Array<
      keyof ExperimentFormState
    >
  ) {
    const candidate = value[key];
    if (typeof candidate === typeof EXPERIMENT_FORM_DEFAULTS[key]) {
      normalized[key] = candidate;
    }
  }
  for (const [key, allowedValues] of Object.entries(DRAFT_ENUM_VALUES)) {
    const candidate = value[key];
    if (typeof candidate !== "string" || !allowedValues?.includes(candidate)) {
      normalized[key] =
        EXPERIMENT_FORM_DEFAULTS[key as keyof ExperimentFormState];
    }
  }
  if (
    typeof value.optimizer_strategy !== "string" ||
    !OPTIMIZER_STRATEGIES.includes(
      value.optimizer_strategy as OptimizerStrategy,
    )
  ) {
    // Drafts created before optimizer_strategy existed retain the old,
    // inexpensive default. New forms use the portfolio default above.
    normalized.optimizer_strategy = "heuristic";
  }
  // Never restore a secret from a draft, including a manually edited one.
  normalized.llm_api_key = "";
  return normalized as unknown as ExperimentFormState;
}

export function normalizeExperimentDraftSelections(
  value: unknown,
): ParameterSelectionMap | null {
  if (!isRecord(value)) return null;
  const normalized: ParameterSelectionMap =
    Object.create(null) as ParameterSelectionMap;
  for (const [name, candidate] of Object.entries(value)) {
    if (
      !/^[A-Z][A-Z0-9_]{0,63}$/u.test(name) ||
      !isRecord(candidate)
    ) {
      continue;
    }
    if (
      typeof candidate.baseline !== "number" ||
      !Number.isFinite(candidate.baseline) ||
      typeof candidate.search_min !== "number" ||
      !Number.isFinite(candidate.search_min) ||
      typeof candidate.search_max !== "number" ||
      !Number.isFinite(candidate.search_max) ||
      (candidate.scale !== "linear" && candidate.scale !== "log") ||
      typeof candidate.selected !== "boolean"
    ) {
      continue;
    }
    normalized[name] = {
      name,
      baseline: candidate.baseline,
      search_min: candidate.search_min,
      search_max: candidate.search_max,
      scale: candidate.scale,
      selected: candidate.selected,
    };
  }
  return normalized;
}

export const EXPERIMENT_DRAFT_SCHEMA: ExperimentDraftSchema<
  ExperimentFormState,
  ParameterSelectionMap
> = {
  maxActiveStep: 4,
  normalizeForm: normalizeExperimentDraftForm,
  normalizeSelections: normalizeExperimentDraftSelections,
};
