import type { ExperimentFormState } from "./formState";

export const STARTER_EXPERIENCE_CATALOG_VERSION = 1;

export type StarterExperienceId =
  | "hover-basics"
  | "first-circle"
  | "light-wind-circle"
  | "wind-sensor-circle";

export type FixedScenarioId =
  | StarterExperienceId
  | "wide-circle"
  | "tight-circle"
  | "figure-eight"
  | "u-turn"
  | "steady-crosswind"
  | "gust-circle"
  | "windy-figure-eight"
  | "recovery-u-turn"
  | "gps-noise-circle"
  | "baro-noise-hover"
  | "imu-noise-figure-eight"
  | "dropout-circle"
  | "payload-hover"
  | "payload-circle"
  | "voltage-sag-circle"
  | "low-battery-u-turn"
  | "holdout-circle"
  | "robust-figure-eight"
  | "qualification-u-turn"
  | "combined-qualification";

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

type TemplatePatch = Pick<ExperimentFormState, TemplateField>;

interface ExperienceTemplate<TId extends FixedScenarioId> {
  id: TId;
  version: number;
  key: `${TId}@${number}`;
  patch: Readonly<Pick<ExperimentFormState, TemplateField>>;
}

export type StarterExperienceTemplate = ExperienceTemplate<StarterExperienceId>;
export type FixedScenarioTemplate = ExperienceTemplate<FixedScenarioId>;

function freezeTemplate<TId extends FixedScenarioId>(
  id: TId,
  patch: TemplatePatch,
): ExperienceTemplate<TId> {
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
  simulator_backend: "real_cli",
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
    freezeTemplate("wind-sensor-circle", {
      ...COMMON_BEGINNER_FIELDS,
      ...ROBUST_OBJECTIVE,
      track_type: "circle",
      circle_radius_m: "5",
      sensor_noise_level: "medium",
      wind_north: "0",
      wind_east: "3",
      wind_south: "0",
      wind_west: "0",
      wind_search_enabled: true,
      noise_search_enabled: true,
      combined_holdout_enabled: true,
      scenario_preset: "stress",
    }),
  ]);

const FIXED_SCENARIO_BASE = {
  ...COMMON_BEGINNER_FIELDS,
  ...ROBUST_OBJECTIVE,
  track_type: "circle",
  circle_radius_m: "5",
  wind_north: "0",
  wind_east: "0",
  wind_south: "0",
  wind_west: "0",
  wind_search_enabled: false,
  scenario_preset: "nominal",
} as const satisfies TemplatePatch;

function freezeFixedScenario(
  id: FixedScenarioId,
  patch: Partial<TemplatePatch>,
): FixedScenarioTemplate {
  return freezeTemplate(id, { ...FIXED_SCENARIO_BASE, ...patch } as TemplatePatch);
}

/**
 * The fixed-scenario catalog is intentionally broader than the four starter
 * experiences shown in the experiment wizard. Every entry remains a pure,
 * versioned draft patch and cannot create or run a Job by itself.
 */
export const FIXED_SCENARIO_TEMPLATES: readonly FixedScenarioTemplate[] =
  Object.freeze([
    ...STARTER_EXPERIENCE_TEMPLATES,
    freezeFixedScenario("wide-circle", {
      circle_radius_m: "8",
      objective_weight_tracking: "0.85",
      objective_weight_speed: "0.4",
    }),
    freezeFixedScenario("tight-circle", {
      circle_radius_m: "3",
      objective_weight_tracking: "1.15",
      objective_weight_smoothness: "0.5",
    }),
    freezeFixedScenario("figure-eight", {
      track_type: "lemniscate",
      objective_weight_tracking: "1.1",
      objective_weight_smoothness: "0.55",
    }),
    freezeFixedScenario("u-turn", {
      track_type: "u_turn",
      objective_weight_tracking: "1.05",
      objective_weight_speed: "0.35",
    }),
    freezeFixedScenario("steady-crosswind", {
      wind_east: "2.5",
      wind_search_enabled: true,
      scenario_preset: "wind",
    }),
    freezeFixedScenario("gust-circle", {
      wind_north: "1.5",
      wind_search_enabled: true,
      gust_enabled: true,
      gust_magnitude_mps: "3",
      gust_direction_deg: "45",
      gust_period_s: "8",
      scenario_preset: "wind",
    }),
    freezeFixedScenario("windy-figure-eight", {
      track_type: "lemniscate",
      wind_west: "3",
      wind_search_enabled: true,
      combined_holdout_enabled: true,
      scenario_preset: "wind",
    }),
    freezeFixedScenario("recovery-u-turn", {
      track_type: "u_turn",
      wind_south: "3.5",
      wind_search_enabled: true,
      gust_enabled: true,
      gust_magnitude_mps: "2.5",
      gust_direction_deg: "180",
      gust_period_s: "9",
      combined_holdout_enabled: true,
      scenario_preset: "stress",
    }),
    freezeFixedScenario("gps-noise-circle", {
      sensor_noise_level: "medium",
      gps_noise_m: "0.8",
      noise_search_enabled: true,
      scenario_preset: "sensor",
    }),
    freezeFixedScenario("baro-noise-hover", {
      track_type: "hover",
      sensor_noise_level: "medium",
      baro_noise_m: "0.6",
      noise_search_enabled: true,
      scenario_preset: "sensor",
    }),
    freezeFixedScenario("imu-noise-figure-eight", {
      track_type: "lemniscate",
      sensor_noise_level: "high",
      imu_noise_scale: "1.8",
      noise_search_enabled: true,
      combined_holdout_enabled: true,
      scenario_preset: "sensor",
    }),
    freezeFixedScenario("dropout-circle", {
      sensor_noise_level: "high",
      dropout_rate: "0.08",
      noise_search_enabled: true,
      combined_holdout_enabled: true,
      scenario_preset: "stress",
    }),
    freezeFixedScenario("payload-hover", {
      track_type: "hover",
      mass_payload_kg: "0.5",
      objective_weight_smoothness: "0.8",
    }),
    freezeFixedScenario("payload-circle", {
      mass_payload_kg: "0.8",
      objective_weight_tracking: "1.2",
      combined_holdout_enabled: true,
    }),
    freezeFixedScenario("voltage-sag-circle", {
      battery_initial_percent: "65",
      battery_voltage_sag: true,
      combined_holdout_enabled: true,
      scenario_preset: "stress",
    }),
    freezeFixedScenario("low-battery-u-turn", {
      track_type: "u_turn",
      battery_initial_percent: "35",
      battery_voltage_sag: true,
      objective_weight_smoothness: "0.7",
      combined_holdout_enabled: true,
      scenario_preset: "stress",
    }),
    freezeFixedScenario("holdout-circle", {
      search_seeds: "111, 222, 333",
      holdout_seeds: "911, 922, 933",
      combined_holdout_enabled: true,
      max_total_trials: "260",
    }),
    freezeFixedScenario("robust-figure-eight", {
      track_type: "lemniscate",
      wind_north: "2",
      wind_search_enabled: true,
      noise_search_enabled: true,
      sensor_noise_level: "medium",
      combined_holdout_enabled: true,
      scenario_preset: "stress",
      max_total_trials: "280",
    }),
    freezeFixedScenario("qualification-u-turn", {
      track_type: "u_turn",
      wind_east: "2",
      wind_search_enabled: true,
      holdout_seeds: "941, 942, 943",
      combined_holdout_enabled: true,
      max_total_trials: "300",
    }),
    freezeFixedScenario("combined-qualification", {
      track_type: "lemniscate",
      wind_west: "3",
      wind_search_enabled: true,
      gust_enabled: true,
      gust_magnitude_mps: "2",
      sensor_noise_level: "high",
      gps_noise_m: "0.6",
      baro_noise_m: "0.4",
      imu_noise_scale: "1.5",
      noise_search_enabled: true,
      combined_holdout_enabled: true,
      scenario_preset: "stress",
      max_iterations: "16",
      max_total_trials: "320",
    }),
  ]);

export function findStarterExperienceTemplate(
  key: string | null,
): FixedScenarioTemplate | null {
  if (!key) return null;
  return FIXED_SCENARIO_TEMPLATES.find((template) => template.key === key) ?? null;
}

/**
 * Applying a starter experience is deliberately a pure draft transformation.
 * It has no API client dependency and therefore cannot create or start a Job.
 */
export function applyStarterExperienceTemplate(
  current: ExperimentFormState,
  template: FixedScenarioTemplate,
): ExperimentFormState {
  return {
    ...current,
    ...template.patch,
  };
}
