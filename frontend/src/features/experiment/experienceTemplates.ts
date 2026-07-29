import type { ExperimentFormState } from "./formState";

export const STARTER_EXPERIENCE_CATALOG_VERSION = 1;

export type StarterExperienceId =
  | "hover-basics"
  | "first-circle"
  | "light-wind-circle";

type TemplateField =
  | "tuning_mode"
  | "track_type"
  | "start_x"
  | "start_y"
  | "altitude_m"
  | "circle_radius_m"
  | "objective_profile"
  | "objective_weight_tracking"
  | "objective_weight_speed"
  | "objective_weight_smoothness"
  | "objective_weight_robustness"
  | "robust_aggregation"
  | "cvar_alpha"
  | "percentile"
  | "sensor_noise_level"
  | "wind_north"
  | "wind_east"
  | "wind_south"
  | "wind_west"
  | "nominal_search_enabled"
  | "wind_search_enabled"
  | "noise_search_enabled"
  | "nominal_holdout_enabled"
  | "combined_holdout_enabled"
  | "advanced_enabled"
  | "gust_enabled"
  | "gust_magnitude_mps"
  | "gust_direction_deg"
  | "gust_period_s"
  | "gps_noise_m"
  | "baro_noise_m"
  | "imu_noise_scale"
  | "dropout_rate"
  | "battery_initial_percent"
  | "battery_voltage_sag"
  | "mass_payload_kg"
  | "obstacles_json"
  | "search_seeds"
  | "holdout_seeds"
  | "common_random_numbers"
  | "scenario_preset"
  | "simulator_backend"
  | "optimizer_strategy"
  | "max_iterations"
  | "trials_per_candidate"
  | "max_total_trials";

export interface StarterExperienceTemplate {
  id: StarterExperienceId;
  version: number;
  key: `${StarterExperienceId}@${number}`;
  patch: Readonly<Pick<ExperimentFormState, TemplateField>>;
}

function freezeTemplate(
  id: StarterExperienceId,
  patch: Pick<ExperimentFormState, TemplateField>,
): StarterExperienceTemplate {
  return Object.freeze({
    id,
    version: STARTER_EXPERIENCE_CATALOG_VERSION,
    key: `${id}@${STARTER_EXPERIENCE_CATALOG_VERSION}` as const,
    patch: Object.freeze(patch),
  });
}

const STABLE_OBJECTIVE = {
  objective_profile: "stable",
  objective_weight_tracking: "1",
  objective_weight_speed: "0.15",
  objective_weight_smoothness: "0.75",
  objective_weight_robustness: "0.8",
  robust_aggregation: "mean",
  cvar_alpha: "0.2",
  percentile: "95",
} as const;

const ROBUST_OBJECTIVE = {
  objective_profile: "robust",
  objective_weight_tracking: "1",
  objective_weight_speed: "0.25",
  objective_weight_smoothness: "0.35",
  objective_weight_robustness: "1",
  robust_aggregation: "cvar",
  cvar_alpha: "0.2",
  percentile: "95",
} as const;

const COMMON_BEGINNER_FIELDS = {
  tuning_mode: "basic",
  start_x: "0",
  start_y: "0",
  altitude_m: "3",
  sensor_noise_level: "low",
  nominal_search_enabled: true,
  noise_search_enabled: false,
  nominal_holdout_enabled: true,
  combined_holdout_enabled: false,
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
  common_random_numbers: true,
  simulator_backend: "mock",
  optimizer_strategy: "optimizer_portfolio",
  max_iterations: "12",
  trials_per_candidate: "3",
  max_total_trials: "220",
} as const;

export const STARTER_EXPERIENCE_TEMPLATES: readonly StarterExperienceTemplate[] =
  Object.freeze([
    freezeTemplate("hover-basics", {
      ...COMMON_BEGINNER_FIELDS,
      ...STABLE_OBJECTIVE,
      track_type: "hover",
      circle_radius_m: "5",
      wind_north: "0",
      wind_east: "0",
      wind_south: "0",
      wind_west: "0",
      wind_search_enabled: false,
      scenario_preset: "nominal",
    }),
    freezeTemplate("first-circle", {
      ...COMMON_BEGINNER_FIELDS,
      ...STABLE_OBJECTIVE,
      track_type: "circle",
      circle_radius_m: "5",
      wind_north: "0",
      wind_east: "0",
      wind_south: "0",
      wind_west: "0",
      wind_search_enabled: false,
      scenario_preset: "nominal",
    }),
    freezeTemplate("light-wind-circle", {
      ...COMMON_BEGINNER_FIELDS,
      ...ROBUST_OBJECTIVE,
      track_type: "circle",
      circle_radius_m: "5",
      wind_north: "2",
      wind_east: "0",
      wind_south: "0",
      wind_west: "0",
      wind_search_enabled: true,
      scenario_preset: "wind",
    }),
  ]);

/**
 * Applying a starter experience is deliberately a pure draft transformation.
 * It has no API client dependency and therefore cannot create or start a Job.
 */
export function applyStarterExperienceTemplate(
  current: ExperimentFormState,
  template: StarterExperienceTemplate,
): ExperimentFormState {
  return {
    ...current,
    ...template.patch,
  };
}
