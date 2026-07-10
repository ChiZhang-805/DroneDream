import { useEffect, useRef, useState } from "react";
import type { ChangeEvent, FormEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { Alert } from "../components/Alert";
import { ParameterSelector } from "../components/ParameterSelector";
import { SectionCard } from "../components/SectionCard";
import { TrackEditor2D } from "../components/TrackEditor2D";
import { apiClient, ApiClientError } from "../api/client";
import {
  OBJECTIVE_PROFILES,
  OPTIMIZER_STRATEGIES,
  SENSOR_NOISE_LEVELS,
  SIMULATOR_BACKENDS,
  TRACK_TYPES,
} from "../types/api";
import type {
  BaselineParameters,
  ExperimentStudyConfig,
  JobCreateRequest,
  ObjectiveConfig,
  ObjectiveProfile,
  OptimizerStrategy,
  ParameterCatalogResponse,
  ParameterSpaceSelection,
  RobustAggregation,
  ScenarioAdvancedConfig,
  ScenarioSuiteConfig,
  SensorNoiseLevel,
  SimulatorBackend,
  TrackPoint,
  TrackType,
  TuningMode,
} from "../types/api";
import {
  BUILTIN_PARAMETER_CATALOG,
  createParameterSelections,
  normalizeApiCatalog,
  selectedParameters,
  type ParameterSelectionMap,
} from "../features/experiment/parameterCatalog";
import {
  clearExperimentDraft,
  loadExperimentDraft,
  persistStudyForJob,
  saveExperimentDraft,
} from "../features/experiment/draftStorage";
import { generateReferenceTrack } from "../utils/referenceTrack";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";

interface FormState {
  tuning_mode: TuningMode;
  display_name: string;
  px4_version: string;
  firmware_commit: string;
  vehicle_type: string;
  airframe: string;
  simulator_model: string;
  simulator_world: string;
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
  target_rmse: string;
  target_max_error: string;
  min_pass_rate: string;
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
  common_random_numbers: boolean;
}

const DEFAULTS: FormState = {
  tuning_mode: "basic",
  display_name: "",
  px4_version: "v1.16",
  firmware_commit: "",
  vehicle_type: "multicopter",
  airframe: "x500",
  simulator_model: "gz_x500",
  simulator_world: "default",
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
  optimizer_strategy: "heuristic",
  max_iterations: "12",
  trials_per_candidate: "3",
  max_total_trials: "100",
  target_rmse: "0.5",
  target_max_error: "",
  min_pass_rate: "0.8",
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
  common_random_numbers: true,
};

type FieldErrors = Record<string, string>;

const CUSTOM_REFERENCE_TRACK_EXAMPLE = `[
  {"x": 0, "y": 0, "z": 3},
  {"x": 5, "y": 0, "z": 3},
  {"x": 5, "y": 5, "z": 3}
]`;

const OBSTACLES_JSON_EXAMPLE = `[
  {"type":"cylinder","x":3,"y":2,"z":0,"radius":0.5,"height":2},
  {"type":"box","x":-2,"y":4,"z":0,"size_x":1,"size_y":1.5,"size_z":2}
]`;

const WIZARD_STEPS: Array<{ key: TranslationKey; short: string }> = [
  { key: "wizard.step.vehicle", short: "Vehicle" },
  { key: "wizard.step.objective", short: "Objective" },
  { key: "wizard.step.parameters", short: "Parameters" },
  { key: "wizard.step.scenarios", short: "Scenarios" },
  { key: "wizard.step.track", short: "Track" },
  { key: "wizard.step.constraints", short: "Budget" },
  { key: "wizard.step.review", short: "Review" },
];

const FIELD_STEPS: Record<string, number> = {
  display_name: 0,
  px4_version: 0,
  firmware_commit: 0,
  vehicle_type: 0,
  airframe: 0,
  simulator_model: 0,
  simulator_world: 0,
  objective_profile: 1,
  objective_weights: 1,
  robust_aggregation: 1,
  cvar_alpha: 1,
  percentile: 1,
  parameters: 2,
  baseline_kp_xy: 2,
  baseline_kd_xy: 2,
  baseline_ki_xy: 2,
  baseline_vel_limit: 2,
  baseline_accel_limit: 2,
  baseline_disturbance_rejection: 2,
  wind_north: 3,
  wind_east: 3,
  wind_south: 3,
  wind_west: 3,
  sensor_noise_level: 3,
  search_seeds: 3,
  holdout_seeds: 3,
  seed_overlap: 3,
  advanced_enabled: 3,
  gps_noise_m: 3,
  baro_noise_m: 3,
  imu_noise_scale: 3,
  dropout_rate: 3,
  battery_initial_percent: 3,
  mass_payload_kg: 3,
  gust_magnitude_mps: 3,
  gust_direction_deg: 3,
  gust_period_s: 3,
  obstacles_json: 3,
  track_type: 4,
  reference_track_json: 4,
  circle_radius_m: 4,
  u_turn_straight_length_m: 4,
  u_turn_turn_radius_m: 4,
  lemniscate_scale_m: 4,
  start_x: 4,
  start_y: 4,
  altitude_m: 4,
  simulator_backend: 5,
  optimizer_strategy: 5,
  max_iterations: 5,
  trials_per_candidate: 5,
  max_total_trials: 5,
  target_rmse: 5,
  target_max_error: 5,
  min_pass_rate: 5,
  llm_api_key: 5,
  llm_model: 5,
  llm_base_url: 5,
};

function parseNumber(raw: string): number | null {
  if (raw.trim() === "") return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function isValidLlmBaseUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw);
    return (
      ["http:", "https:"].includes(parsed.protocol) &&
      Boolean(parsed.hostname) &&
      parsed.username === "" &&
      parsed.password === "" &&
      parsed.search === "" &&
      parsed.hash === ""
    );
  } catch {
    return false;
  }
}

function parseSeedList(raw: string): { values: number[]; error: string | null } {
  const tokens = raw.split(/[\s,]+/).filter(Boolean);
  const values = tokens.map(Number);
  if (values.length === 0) return { values: [], error: "Enter at least one integer seed" };
  if (values.length > 100) return { values: [], error: "A scenario case supports at most 100 seeds" };
  if (values.some((value) => !Number.isInteger(value) || value < 0)) {
    return { values: [], error: "Seeds must be non-negative integers separated by commas" };
  }
  if (new Set(values).size !== values.length) {
    return { values: [], error: "Seeds must be unique" };
  }
  return { values, error: null };
}

function parseReferenceTrackInput(raw: string): {
  points: TrackPoint[] | null;
  error: string | null;
} {
  if (raw.trim() === "") return { points: null, error: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { points: null, error: "Must be valid JSON array" };
  }
  if (!Array.isArray(parsed)) return { points: null, error: "Must be JSON array" };
  const points: TrackPoint[] = [];
  for (let index = 0; index < parsed.length; index += 1) {
    const value = parsed[index];
    if (!value || typeof value !== "object") {
      return { points: null, error: `Point #${index + 1} must be an object` };
    }
    const x = Number((value as { x?: unknown }).x);
    const y = Number((value as { y?: unknown }).y);
    const zValue = (value as { z?: unknown }).z;
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      return { points: null, error: `Point #${index + 1} requires numeric x/y` };
    }
    if (zValue !== undefined && zValue !== null && !Number.isFinite(Number(zValue))) {
      return { points: null, error: `Point #${index + 1} z must be numeric when provided` };
    }
    points.push({ x, y, z: zValue === undefined || zValue === null ? null : Number(zValue) });
  }
  return { points, error: null };
}

function parseObstacles(raw: string): { value: ScenarioAdvancedConfig["obstacles"]; error: string | null } {
  try {
    const value = JSON.parse(raw) as unknown;
    if (!Array.isArray(value)) return { value: [], error: "Must be JSON array" };
    return { value: value as ScenarioAdvancedConfig["obstacles"], error: null };
  } catch {
    return { value: [], error: "Must be valid JSON array" };
  }
}

function errorStep(key: string, catalog: ParameterCatalogResponse): number {
  if (FIELD_STEPS[key] !== undefined) return FIELD_STEPS[key];
  if (catalog.parameters.some((parameter) => parameter.name === key)) return 2;
  return 0;
}

function focusErrorField(key: string, catalog: ParameterCatalogResponse): void {
  const isParameter = catalog.parameters.some((parameter) => parameter.name === key);
  const aliases: Record<string, string> = {
    objective_weights: "objective_weight_tracking",
    seed_overlap: "holdout_seeds",
    parameters: "parameter-search",
  };
  const id = isParameter ? `parameter-${key}-min` : aliases[key] ?? key;
  window.setTimeout(() => document.getElementById(id)?.focus(), 0);
}

function validate(
  form: FormState,
  selections: ParameterSelectionMap,
  catalog: ParameterCatalogResponse,
): FieldErrors {
  const errors: FieldErrors = {};
  (["px4_version", "vehicle_type", "airframe", "simulator_model", "simulator_world"] as const).forEach((key) => {
    if (form[key].trim() === "") errors[key] = "Required";
  });
  if (!OBJECTIVE_PROFILES.includes(form.objective_profile)) {
    errors.objective_profile = "Select a valid objective profile";
  }
  const weights = [
    form.objective_weight_tracking,
    form.objective_weight_speed,
    form.objective_weight_smoothness,
    form.objective_weight_robustness,
  ].map(parseNumber);
  if (weights.some((weight) => weight === null || weight < 0 || weight > 100)) {
    errors.objective_weights = "Each objective weight must be between 0 and 100";
  } else if (weights.reduce<number>((sum, weight) => sum + Number(weight), 0) <= 0) {
    errors.objective_weights = "At least one objective must have a positive weight";
  }
  const cvarAlpha = parseNumber(form.cvar_alpha);
  if (cvarAlpha === null || cvarAlpha <= 0 || cvarAlpha >= 1) {
    errors.cvar_alpha = "Must be greater than 0 and less than 1";
  }
  const percentile = parseNumber(form.percentile);
  if (percentile === null || percentile <= 0 || percentile > 100) {
    errors.percentile = "Must be greater than 0 and at most 100";
  }

  const selected = Object.values(selections).filter((selection) => selection.selected);
  if (selected.length === 0) errors.parameters = "Select at least one parameter to tune";
  for (const parameter of catalog.parameters) {
    const selection = selections[parameter.name];
    if (!selection?.selected) continue;
    if (
      !Number.isFinite(selection.baseline) ||
      !Number.isFinite(selection.search_min) ||
      !Number.isFinite(selection.search_max)
    ) {
      errors[parameter.name] = "Baseline and search bounds must be finite numbers";
    } else if (
      parameter.value_type === "integer" &&
      ![
        selection.baseline,
        selection.search_min,
        selection.search_max,
      ].every(Number.isInteger)
    ) {
      errors[parameter.name] = "Integer parameters require whole-number baseline and bounds";
    } else if (selection.search_min >= selection.search_max) {
      errors[parameter.name] = "Search minimum must be less than maximum";
    } else if (
      selection.search_min < parameter.absolute_min ||
      selection.search_max > parameter.absolute_max
    ) {
      errors[parameter.name] = `Search range must stay inside ${parameter.absolute_min}–${parameter.absolute_max}`;
    } else if (
      selection.baseline < selection.search_min ||
      selection.baseline > selection.search_max
    ) {
      errors[parameter.name] = "Baseline must be inside the search range";
    } else if (selection.scale === "log" && selection.search_min <= 0) {
      errors[parameter.name] = "Log-scaled ranges must be positive";
    }
  }

  const baselineRanges: Array<[keyof FormState, number, number]> = [
    ["baseline_kp_xy", 0.3, 2.5],
    ["baseline_kd_xy", 0.05, 0.8],
    ["baseline_ki_xy", 0, 0.25],
    ["baseline_vel_limit", 2, 10],
    ["baseline_accel_limit", 2, 8],
    ["baseline_disturbance_rejection", 0, 1],
  ];
  for (const [key, minimum, maximum] of baselineRanges) {
    const value = parseNumber(form[key] as string);
    if (value === null || value < minimum || value > maximum) {
      errors[key] = `Must be between ${minimum} and ${maximum}`;
    }
  }

  if (!TRACK_TYPES.includes(form.track_type)) errors.track_type = "Select a valid track type";
  const parsedTrack = parseReferenceTrackInput(form.reference_track_json);
  if (parsedTrack.error) errors.reference_track_json = parsedTrack.error;
  if (form.track_type === "custom" && (!parsedTrack.points || parsedTrack.points.length < 2)) {
    errors.reference_track_json = parsedTrack.error ?? "Custom track requires at least 2 points";
  }
  if (form.track_type === "circle") {
    const value = parseNumber(form.circle_radius_m);
    if (value === null || value <= 0 || value > 100) errors.circle_radius_m = "Must be > 0 and <= 100";
  }
  if (form.track_type === "u_turn") {
    const straight = parseNumber(form.u_turn_straight_length_m);
    const radius = parseNumber(form.u_turn_turn_radius_m);
    if (straight === null || straight <= 0 || straight > 200) errors.u_turn_straight_length_m = "Must be > 0 and <= 200";
    if (radius === null || radius <= 0 || radius > 100) errors.u_turn_turn_radius_m = "Must be > 0 and <= 100";
  }
  if (form.track_type === "lemniscate") {
    const value = parseNumber(form.lemniscate_scale_m);
    if (value === null || value <= 0 || value > 100) errors.lemniscate_scale_m = "Must be > 0 and <= 100";
  }
  if (parseNumber(form.start_x) === null) errors.start_x = "Required numeric value";
  if (parseNumber(form.start_y) === null) errors.start_y = "Required numeric value";
  const altitude = parseNumber(form.altitude_m);
  if (altitude === null) errors.altitude_m = "Required numeric value";
  else if (altitude < 1 || altitude > 20) errors.altitude_m = "Must be between 1.0 and 20.0";

  (["wind_north", "wind_east", "wind_south", "wind_west"] as const).forEach((key) => {
    const value = parseNumber(form[key]);
    if (value === null) errors[key] = "Required numeric value";
    else if (value < -10 || value > 10) errors[key] = "Must be between -10 and 10";
  });
  if (!SENSOR_NOISE_LEVELS.includes(form.sensor_noise_level)) {
    errors.sensor_noise_level = "Select a valid sensor noise level";
  }
  const searchSeeds = parseSeedList(form.search_seeds);
  const holdoutSeeds = parseSeedList(form.holdout_seeds);
  if (searchSeeds.error) errors.search_seeds = searchSeeds.error;
  if (holdoutSeeds.error) errors.holdout_seeds = holdoutSeeds.error;
  if (
    !searchSeeds.error &&
    !holdoutSeeds.error &&
    holdoutSeeds.values.some((seed) => searchSeeds.values.includes(seed))
  ) {
    errors.seed_overlap = "Holdout seeds must not appear in the search seed set";
  }

  if (form.advanced_enabled) {
    const bounded: Array<[keyof FormState, number, number, string]> = [
      ["gps_noise_m", 0, 100, "Must be between 0 and 100"],
      ["baro_noise_m", 0, 100, "Must be between 0 and 100"],
      ["imu_noise_scale", 0, 10, "Must be between 0 and 10"],
      ["dropout_rate", 0, 1, "Must be between 0 and 1"],
      ["battery_initial_percent", 0, 100, "Must be between 0 and 100"],
    ];
    for (const [key, minimum, maximum, message] of bounded) {
      const value = parseNumber(form[key] as string);
      if (value === null || value < minimum || value > maximum) errors[key] = message;
    }
    if (form.mass_payload_kg.trim() !== "") {
      const value = parseNumber(form.mass_payload_kg);
      if (value === null || value < 0 || value > 20) errors.mass_payload_kg = "Must be between 0 and 20";
    }
    if (form.gust_enabled) {
      const magnitude = parseNumber(form.gust_magnitude_mps);
      const direction = parseNumber(form.gust_direction_deg);
      const period = parseNumber(form.gust_period_s);
      if (magnitude === null || magnitude < 0 || magnitude > 30) errors.gust_magnitude_mps = "Must be 0–30";
      if (direction === null || direction < 0 || direction >= 360) errors.gust_direction_deg = "Must be 0–<360";
      if (period === null || period <= 0 || period > 300) errors.gust_period_s = "Must be >0 and <=300";
    }
    const obstacleResult = parseObstacles(form.obstacles_json);
    if (obstacleResult.error) errors.obstacles_json = obstacleResult.error;
  }

  if (!SIMULATOR_BACKENDS.includes(form.simulator_backend)) errors.simulator_backend = "Select a valid simulator backend";
  if (!OPTIMIZER_STRATEGIES.includes(form.optimizer_strategy)) errors.optimizer_strategy = "Select a valid optimizer strategy";
  const maxIterations = parseNumber(form.max_iterations);
  if (maxIterations === null || !Number.isInteger(maxIterations) || maxIterations < 1 || maxIterations > 100) {
    errors.max_iterations = "Integer between 1 and 100";
  }
  const trials = parseNumber(form.trials_per_candidate);
  if (trials === null || !Number.isInteger(trials) || trials < 1 || trials > 10) {
    errors.trials_per_candidate = "Integer between 1 and 10";
  }
  const maxTotal = parseNumber(form.max_total_trials);
  if (maxTotal === null || !Number.isInteger(maxTotal) || maxTotal < 1 || maxTotal > 10000) {
    errors.max_total_trials = "Integer between 1 and 10000";
  }
  if (form.target_rmse.trim() !== "") {
    const value = parseNumber(form.target_rmse);
    if (value === null || value < 0 || value > 100) errors.target_rmse = "Must be between 0 and 100";
  }
  if (form.target_max_error.trim() !== "") {
    const value = parseNumber(form.target_max_error);
    if (value === null || value < 0 || value > 100) errors.target_max_error = "Must be between 0 and 100";
  }
  const passRate = parseNumber(form.min_pass_rate);
  if (passRate === null || passRate < 0 || passRate > 1) errors.min_pass_rate = "Must be between 0 and 1";
  if (form.optimizer_strategy === "gpt" && form.llm_api_key.trim() === "") {
    errors.llm_api_key = "API key required when strategy is gpt";
  }
  if (
    form.optimizer_strategy === "gpt" &&
    form.llm_provider !== "openai" &&
    form.llm_model.trim() === ""
  ) {
    errors.llm_model = "Model is required for non-OpenAI providers";
  }
  if (
    form.optimizer_strategy === "gpt" &&
    form.llm_provider !== "openai" &&
    form.llm_base_url.trim() === ""
  ) {
    errors.llm_base_url = "Base URL is required for non-OpenAI providers";
  } else if (
    form.optimizer_strategy === "gpt" &&
    form.llm_base_url.trim() !== "" &&
    !isValidLlmBaseUrl(form.llm_base_url.trim())
  ) {
    errors.llm_base_url = "Use an absolute HTTP(S) URL without credentials, query, or fragment";
  }
  return errors;
}

function buildAdvancedScenario(form: FormState): ScenarioAdvancedConfig | null {
  if (!form.advanced_enabled) return null;
  return {
    wind_gusts: {
      enabled: form.gust_enabled,
      magnitude_mps: Number(form.gust_magnitude_mps),
      direction_deg: Number(form.gust_direction_deg),
      period_s: Number(form.gust_period_s),
    },
    obstacles: parseObstacles(form.obstacles_json).value,
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
  };
}

function objectiveConfig(form: FormState): ObjectiveConfig {
  const objectiveEntries = [
    { metric: "rmse", direction: "minimize" as const, weight: Number(form.objective_weight_tracking), normalization: 1 },
    { metric: "completion_time", direction: "minimize" as const, weight: Number(form.objective_weight_speed), normalization: 10 },
    { metric: "overshoot_count", direction: "minimize" as const, weight: Number(form.objective_weight_smoothness), normalization: 5 },
    { metric: "pass_flag", direction: "maximize" as const, weight: Number(form.objective_weight_robustness), normalization: 1 },
  ].filter((objective) => objective.weight > 0);
  const constraints: ObjectiveConfig["constraints"] = [
    { metric: "crash_flag", operator: "lte", threshold: 0, hard: true, penalty: 100 },
    { metric: "timeout_flag", operator: "lte", threshold: 0, hard: true, penalty: 100 },
    { metric: "pass_rate", operator: "gte", threshold: Number(form.min_pass_rate), hard: true, penalty: 25 },
  ];
  if (form.target_rmse.trim() !== "") {
    constraints.push({ metric: "rmse", operator: "lte", threshold: Number(form.target_rmse), hard: true, penalty: 20 });
  }
  if (form.target_max_error.trim() !== "") {
    constraints.push({ metric: "max_error", operator: "lte", threshold: Number(form.target_max_error), hard: true, penalty: 20 });
  }
  return {
    objectives: objectiveEntries,
    constraints,
    robust_aggregation: form.robust_aggregation,
    cvar_alpha: Number(form.cvar_alpha),
    percentile: Number(form.percentile),
  };
}

function scenarioSuite(form: FormState): ScenarioSuiteConfig {
  const searchSeeds = parseSeedList(form.search_seeds).values;
  const holdoutSeeds = parseSeedList(form.holdout_seeds).values;
  const advanced = buildAdvancedScenario(form);
  const commonConfig: Record<string, unknown> = {
    wind: {
      north: Number(form.wind_north),
      east: Number(form.wind_east),
      south: Number(form.wind_south),
      west: Number(form.wind_west),
    },
    sensor_noise_level: form.sensor_noise_level,
    ...(advanced ? { advanced_scenario_config: advanced } : {}),
  };
  return {
    common_random_numbers: form.common_random_numbers,
    cases: [
      { id: "nominal-search", scenario_type: "nominal", seeds: searchSeeds, weight: 1, enabled: true, holdout: false, config: commonConfig },
      { id: "wind-search", scenario_type: "wind_perturbed", seeds: searchSeeds, weight: 1.2, enabled: true, holdout: false, config: commonConfig },
      { id: "noise-search", scenario_type: "noise_perturbed", seeds: searchSeeds, weight: 1, enabled: true, holdout: false, config: commonConfig },
      { id: "combined-holdout", scenario_type: "combined_perturbed", seeds: holdoutSeeds, weight: 1.5, enabled: true, holdout: true, config: commonConfig },
    ],
  };
}

function baselineParameters(
  form: FormState,
  selections: ParameterSelectionMap,
  catalog: ParameterCatalogResponse,
): BaselineParameters {
  const fallback: BaselineParameters = {
    kp_xy: Number(form.baseline_kp_xy),
    kd_xy: Number(form.baseline_kd_xy),
    ki_xy: Number(form.baseline_ki_xy),
    vel_limit: Number(form.baseline_vel_limit),
    accel_limit: Number(form.baseline_accel_limit),
    disturbance_rejection: Number(form.baseline_disturbance_rejection),
  };
  for (const parameter of catalog.parameters) {
    if (parameter.legacy_key && selections[parameter.name]) {
      fallback[parameter.legacy_key] = selections[parameter.name].baseline;
    }
  }
  // Real PX4 defaults can be wider than the legacy six-value compatibility
  // schema. Keep the legacy mirror valid without changing parameter_space.
  fallback.kp_xy = Math.min(2.5, Math.max(0.3, fallback.kp_xy));
  fallback.kd_xy = Math.min(0.8, Math.max(0.05, fallback.kd_xy));
  fallback.ki_xy = Math.min(0.25, Math.max(0, fallback.ki_xy));
  fallback.vel_limit = Math.min(10, Math.max(2, fallback.vel_limit));
  fallback.accel_limit = Math.min(8, Math.max(2, fallback.accel_limit));
  fallback.disturbance_rejection = Math.min(
    1,
    Math.max(0, fallback.disturbance_rejection),
  );
  return fallback;
}

function referenceTrack(form: FormState): TrackPoint[] | null {
  if (form.track_type === "custom") return parseReferenceTrackInput(form.reference_track_json).points;
  return generateReferenceTrack(
    form.track_type,
    Number(form.start_x),
    Number(form.start_y),
    Number(form.altitude_m),
    {
      circle_radius_m: Number(form.circle_radius_m),
      u_turn_straight_length_m: Number(form.u_turn_straight_length_m),
      u_turn_turn_radius_m: Number(form.u_turn_turn_radius_m),
      lemniscate_scale_m: Number(form.lemniscate_scale_m),
    },
  );
}

function formToRequest(
  form: FormState,
  selections: ParameterSelectionMap,
  catalog: ParameterCatalogResponse,
): JobCreateRequest {
  const parameterMap = new Map(catalog.parameters.map((parameter) => [parameter.name, parameter]));
  const parameterSpace: ParameterSpaceSelection[] = selectedParameters(selections).map((selection) => {
    const definition = parameterMap.get(selection.name);
    return {
      name: selection.name,
      baseline: selection.baseline,
      minimum: selection.search_min,
      maximum: selection.search_max,
      step: definition?.step ?? null,
      scale: selection.scale,
      value_type: definition?.value_type ?? "float",
      choices: null,
      enabled: true,
      locked: false,
    };
  });
  const request: JobCreateRequest = {
    display_name: form.display_name.trim() === "" ? null : form.display_name.trim(),
    track_type: form.track_type,
    reference_track: referenceTrack(form),
    baseline_parameters: baselineParameters(form, selections, catalog),
    start_point: { x: Number(form.start_x), y: Number(form.start_y) },
    altitude_m: Number(form.altitude_m),
    wind: {
      north: Number(form.wind_north),
      east: Number(form.wind_east),
      south: Number(form.wind_south),
      west: Number(form.wind_west),
    },
    sensor_noise_level: form.sensor_noise_level,
    objective_profile: form.objective_profile,
    advanced_scenario_config: buildAdvancedScenario(form),
    vehicle_profile: {
      px4_version: form.px4_version,
      firmware_commit: form.firmware_commit.trim() === "" ? null : form.firmware_commit.trim(),
      vehicle_type: form.vehicle_type,
      airframe: form.airframe,
      simulator_model: form.simulator_model,
      world: form.simulator_world,
    },
    parameter_catalog_version: catalog.catalog_version ?? `builtin-${catalog.px4_version}`,
    parameter_space: parameterSpace,
    objective_config: objectiveConfig(form),
    scenario_suite: scenarioSuite(form),
    simulator_backend: form.simulator_backend,
    optimizer_strategy: form.optimizer_strategy,
    max_iterations: Number(form.max_iterations),
    trials_per_candidate: Number(form.trials_per_candidate),
    max_total_trials: Number(form.max_total_trials),
    acceptance_criteria: {
      target_rmse: form.target_rmse.trim() === "" ? null : Number(form.target_rmse),
      target_max_error: form.target_max_error.trim() === "" ? null : Number(form.target_max_error),
      min_pass_rate: Number(form.min_pass_rate),
    },
  };
  if (form.optimizer_strategy === "gpt") {
    request.llm = {
      provider: form.llm_provider,
      api_key: form.llm_api_key.trim(),
      model: form.llm_model.trim() === "" ? null : form.llm_model.trim(),
      base_url: form.llm_base_url.trim() === "" ? null : form.llm_base_url.trim(),
    };
  }
  return request;
}

function legacyRequest(request: JobCreateRequest): JobCreateRequest {
  const legacy: JobCreateRequest = { ...request };
  const llm = legacy.llm;
  delete legacy.vehicle_profile;
  delete legacy.parameter_catalog_version;
  delete legacy.parameter_space;
  delete legacy.objective_config;
  delete legacy.scenario_suite;
  delete legacy.max_total_trials;
  delete legacy.llm;
  if (llm) {
    return {
      ...legacy,
      openai: { api_key: llm.api_key, model: llm.model ?? null },
    };
  }
  return legacy;
}

function buildStudyMetadata(
  form: FormState,
  selections: ParameterSelectionMap,
  estimatedTrials: number,
  usedLegacyApi: boolean,
): ExperimentStudyConfig {
  return {
    schema_version: 1,
    tuning_mode: form.tuning_mode,
    vehicle: {
      px4_version: form.px4_version,
      airframe: form.airframe,
      gazebo_model: form.simulator_model,
      gazebo_world: form.simulator_world,
    },
    parameters: selectedParameters(selections),
    objectives: {
      profile: form.objective_profile,
      weights: {
        tracking: Number(form.objective_weight_tracking),
        speed: Number(form.objective_weight_speed),
        smoothness: Number(form.objective_weight_smoothness),
        robustness: Number(form.objective_weight_robustness),
      },
      hard_constraints: {
        target_rmse: form.target_rmse.trim() === "" ? null : Number(form.target_rmse),
        target_max_error: form.target_max_error.trim() === "" ? null : Number(form.target_max_error),
        min_pass_rate: Number(form.min_pass_rate),
      },
    },
    scenario_plan: {
      search_seeds: parseSeedList(form.search_seeds).values,
      holdout_seeds: parseSeedList(form.holdout_seeds).values,
      advanced_enabled: form.advanced_enabled,
    },
    budget: {
      max_iterations: Number(form.max_iterations),
      trials_per_candidate: Number(form.trials_per_candidate),
      estimated_trials: estimatedTrials,
    },
    compatibility: {
      legacy_job_api: usedLegacyApi,
      unmapped_parameters: usedLegacyApi
        ? selectedParameters(selections).map((parameter) => parameter.name)
        : [],
    },
  };
}

function isLegacyContractRejection(
  error: unknown,
  request: JobCreateRequest,
): error is ApiClientError {
  if (!(error instanceof ApiClientError) || ![400, 422].includes(error.httpStatus)) {
    return false;
  }
  if (request.llm && request.llm.provider !== "openai") return false;
  const evidence = `${error.message} ${JSON.stringify(error.details ?? "")}`.toLowerCase();
  return [
    "unknown",
    "extra",
    "unexpected",
    "vehicle_profile",
    "parameter_space",
    "objective_config",
    "scenario_suite",
    "max_total_trials",
    "llm",
  ].some((token) => evidence.includes(token));
}

function mergeSelections(
  base: ParameterSelectionMap,
  restored: ParameterSelectionMap | null | undefined,
): ParameterSelectionMap {
  if (!restored) return base;
  const merged = { ...base };
  for (const [name, selection] of Object.entries(restored)) {
    if (merged[name] && selection && Number.isFinite(selection.baseline)) {
      merged[name] = { ...merged[name], ...selection, name };
    }
  }
  return merged;
}

export function NewJob() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const initialDraft = useRef(
    loadExperimentDraft<FormState, ParameterSelectionMap>(),
  ).current;
  const [form, setForm] = useState<FormState>(() => ({
    ...DEFAULTS,
    ...(initialDraft?.form ?? {}),
    llm_api_key: "",
  }));
  const [catalog, setCatalog] = useState<ParameterCatalogResponse>(BUILTIN_PARAMETER_CATALOG);
  const [selections, setSelections] = useState<ParameterSelectionMap>(() =>
    mergeSelections(
      createParameterSelections(BUILTIN_PARAMETER_CATALOG.parameters, initialDraft?.form.tuning_mode ?? "basic"),
      initialDraft?.selections,
    ),
  );
  const [step, setStep] = useState(() => Math.min(6, Math.max(0, initialDraft?.active_step ?? 0)));
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showAdvancedScenario, setShowAdvancedScenario] = useState(
    Boolean(initialDraft?.form.advanced_enabled),
  );
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(initialDraft?.saved_at ?? null);
  const [catalogMessage, setCatalogMessage] = useState<string | null>(null);

  const searchSeedCount = parseSeedList(form.search_seeds).values.length;
  const estimatedTrials = Math.min(
    Number(form.max_total_trials) || 0,
    (1 + (Number(form.max_iterations) || 0)) *
      Math.max(Number(form.trials_per_candidate) || 0, searchSeedCount * 3),
  );

  useEffect(() => {
    if (import.meta.env.MODE === "test" || import.meta.env.VITE_PARAMETER_CATALOG_API === "false") {
      return undefined;
    }
    let active = true;
    apiClient
      .getParameterCatalog(form.px4_version)
      .then((response) => {
        if (!active) return;
        const normalized = normalizeApiCatalog(response);
        setCatalog(normalized);
        setSelections((current) =>
          mergeSelections(createParameterSelections(normalized.parameters, form.tuning_mode), current),
        );
        setCatalogMessage(t("wizard.catalogBackend"));
      })
      .catch(() => {
        if (active) setCatalogMessage(t("wizard.catalogFallback"));
      });
    return () => {
      active = false;
    };
  }, [form.px4_version, form.tuning_mode, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const savedAt = saveExperimentDraft({
        active_step: step,
        form: { ...form, llm_api_key: "" },
        selections,
      });
      if (savedAt) setDraftSavedAt(savedAt);
    }, 700);
    return () => window.clearTimeout(timer);
  }, [form, selections, step]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((previous) => ({ ...previous, [key]: value }));
    setErrors((previous) => {
      if (!previous[key]) return previous;
      const next = { ...previous };
      delete next[key];
      return next;
    });
  }

  function handleTextChange(key: keyof FormState) {
    return (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      update(key, event.target.value as FormState[typeof key]);
  }

  function applyModePreset(mode: TuningMode): void {
    const preset = createParameterSelections(catalog.parameters, mode);
    setSelections((current) => {
      const next = { ...preset };
      for (const [name, item] of Object.entries(next)) {
        if (current[name]) next[name] = { ...item, baseline: current[name].baseline };
      }
      return next;
    });
  }

  function changeMode(mode: TuningMode): void {
    update("tuning_mode", mode);
    applyModePreset(mode);
  }

  function resetBaselineDefaults(): void {
    setForm((previous) => ({
      ...previous,
      baseline_kp_xy: DEFAULTS.baseline_kp_xy,
      baseline_kd_xy: DEFAULTS.baseline_kd_xy,
      baseline_ki_xy: DEFAULTS.baseline_ki_xy,
      baseline_vel_limit: DEFAULTS.baseline_vel_limit,
      baseline_accel_limit: DEFAULTS.baseline_accel_limit,
      baseline_disturbance_rejection: DEFAULTS.baseline_disturbance_rejection,
    }));
    setSelections(createParameterSelections(catalog.parameters, form.tuning_mode));
  }

  function saveDraftNow(): void {
    const savedAt = saveExperimentDraft({
      active_step: step,
      form: { ...form, llm_api_key: "" },
      selections,
    });
    setDraftSavedAt(savedAt);
  }

  function handleReset(): void {
    clearExperimentDraft();
    setForm(DEFAULTS);
    setSelections(createParameterSelections(catalog.parameters, DEFAULTS.tuning_mode));
    setErrors({});
    setSubmitError(null);
    setDraftSavedAt(null);
    setStep(0);
  }

  function errorsForStep(targetStep: number): FieldErrors {
    const all = validate(form, selections, catalog);
    return Object.fromEntries(
      Object.entries(all).filter(([key]) => errorStep(key, catalog) === targetStep),
    );
  }

  function nextStep(): void {
    const nextErrors = errorsForStep(step);
    if (Object.keys(nextErrors).length > 0) {
      setErrors((previous) => ({ ...previous, ...nextErrors }));
      focusErrorField(Object.keys(nextErrors)[0], catalog);
      return;
    }
    setStep((current) => Math.min(6, current + 1));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setSubmitError(null);
    const nextErrors = validate(form, selections, catalog);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      const firstStep = Math.min(...Object.keys(nextErrors).map((key) => errorStep(key, catalog)));
      const firstKey = Object.keys(nextErrors).find((key) => errorStep(key, catalog) === firstStep) ?? Object.keys(nextErrors)[0];
      setStep(firstStep);
      focusErrorField(firstKey, catalog);
      return;
    }
    setSubmitting(true);
    const advancedRequest = formToRequest(form, selections, catalog);
    let usedLegacyApi = false;
    try {
      let created;
      try {
        created = await apiClient.createJob(advancedRequest);
      } catch (error) {
        if (!isLegacyContractRejection(error, advancedRequest)) throw error;
        usedLegacyApi = true;
        created = await apiClient.createJob(legacyRequest(advancedRequest));
      }
      persistStudyForJob(
        created.id,
        buildStudyMetadata(form, selections, estimatedTrials, usedLegacyApi),
      );
      clearExperimentDraft();
      navigate(`/jobs/${created.id}`, { replace: false });
    } catch (error) {
      setSubmitError(
        error instanceof ApiClientError
          ? error.message
          : "Failed to submit the experiment. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  const customTrack = parseReferenceTrackInput(form.reference_track_json).points ?? [];
  const selectedCount = Object.values(selections).filter((selection) => selection.selected).length;

  return (
    <section className="stack-md experiment-wizard-page">
      <header className="page-header experiment-header">
        <div>
          <div className="eyebrow">{t("wizard.eyebrow")}</div>
          <h1>{t("wizard.title")}</h1>
          <p className="page-header-subtitle">{t("wizard.subtitle")}</p>
        </div>
        <div className="draft-status" aria-live="polite">
          {draftSavedAt ? `${t("wizard.saved")} · ${new Date(draftSavedAt).toLocaleTimeString()}` : t("wizard.draftNotSaved")}
        </div>
      </header>

      <div className="mode-selector" role="radiogroup" aria-label="Tuning experience level">
        {(["basic", "advanced", "expert"] as const).map((mode) => (
          <button
            type="button"
            role="radio"
            aria-checked={form.tuning_mode === mode}
            className={`mode-card${form.tuning_mode === mode ? " mode-card-active" : ""}`}
            onClick={() => changeMode(mode)}
            key={mode}
          >
            <strong>{t(`wizard.mode.${mode}` as TranslationKey)}</strong>
            <span>
              {t(`wizard.mode.${mode}Desc` as TranslationKey)}
            </span>
          </button>
        ))}
      </div>

      <nav className="wizard-stepper" aria-label="Experiment setup steps">
        {WIZARD_STEPS.map((wizardStep, index) => (
          <button
            key={wizardStep.key}
            type="button"
            className={`${step === index ? "wizard-step-active" : ""}${step > index ? " wizard-step-complete" : ""}`}
            aria-current={step === index ? "step" : undefined}
            onClick={() => setStep(index)}
          >
            <span className="wizard-step-number">{step > index ? "✓" : index + 1}</span>
            <span className="wizard-step-label">{t(wizardStep.key)}</span>
          </button>
        ))}
      </nav>

      <form onSubmit={handleSubmit} noValidate className="experiment-form">
        {submitError ? <Alert tone="danger" title={t("wizard.submissionFailed")}>{submitError}</Alert> : null}
        {catalogMessage ? <Alert tone="info" title={t("wizard.catalogTitle")}>{catalogMessage}</Alert> : null}

        <div hidden={step !== 0} className="wizard-panel">
          <SectionCard title={t("wizard.section.vehicle")} description={t("wizard.section.vehicleDesc")}>
            <div className="form-grid">
              <Field label="Experiment Name" htmlFor="display_name">
                <input id="display_name" value={form.display_name} onChange={handleTextChange("display_name")} placeholder="e.g. x500 anti-wind XY study" />
              </Field>
              <Field label="PX4 Version" required error={errors.px4_version} htmlFor="px4_version">
                <select id="px4_version" value={form.px4_version} onChange={(event) => update("px4_version", event.target.value)}>
                  <option value="v1.16">v1.16</option>
                  <option value="v1.17">v1.17</option>
                  <option value="main">main</option>
                </select>
              </Field>
              {form.tuning_mode === "expert" ? (
                <Field label="Firmware Commit" htmlFor="firmware_commit" hint="Optional immutable commit SHA for exact replay.">
                  <input id="firmware_commit" value={form.firmware_commit} onChange={handleTextChange("firmware_commit")} />
                </Field>
              ) : null}
              <Field label="Vehicle Type" required error={errors.vehicle_type} htmlFor="vehicle_type">
                <select id="vehicle_type" value={form.vehicle_type} onChange={(event) => update("vehicle_type", event.target.value)}>
                  <option value="multicopter">Multicopter</option>
                </select>
              </Field>
              <Field label="Airframe" required error={errors.airframe} htmlFor="airframe">
                <select id="airframe" value={form.airframe} onChange={(event) => update("airframe", event.target.value)}>
                  <option value="x500">x500 quadrotor</option>
                  <option value="quad_x">Generic quad X</option>
                </select>
              </Field>
              <Field label="Gazebo Model" required error={errors.simulator_model} htmlFor="simulator_model">
                <select id="simulator_model" value={form.simulator_model} onChange={(event) => update("simulator_model", event.target.value)}>
                  <option value="gz_x500">gz_x500</option>
                  <option value="gz_x500_depth">gz_x500_depth</option>
                  <option value="gz_x500_vision">gz_x500_vision</option>
                </select>
              </Field>
              <Field label="Gazebo World" required error={errors.simulator_world} htmlFor="simulator_world">
                <select id="simulator_world" value={form.simulator_world} onChange={(event) => update("simulator_world", event.target.value)}>
                  <option value="default">default</option>
                  <option value="windy">windy</option>
                  <option value="warehouse">warehouse</option>
                </select>
              </Field>
            </div>
          </SectionCard>
        </div>

        <div hidden={step !== 1} className="wizard-panel">
          <SectionCard title={t("wizard.section.objective")} description={t("wizard.section.objectiveDesc")}>
            <div className="objective-profile-grid">
              {OBJECTIVE_PROFILES.filter((profile) => profile !== "custom" || form.tuning_mode !== "basic").map((profile) => (
                <button
                  type="button"
                  key={profile}
                  className={`objective-card${form.objective_profile === profile ? " objective-card-active" : ""}`}
                  onClick={() => update("objective_profile", profile)}
                >
                  <strong>{t(`wizard.objective.${profile}` as TranslationKey)}</strong>
                  <span>{profile === "robust" ? t("wizard.objective.robustDesc") : t("wizard.objective.genericDesc")}</span>
                </button>
              ))}
            </div>
            <Field label="Objective Profile" required error={errors.objective_profile} htmlFor="objective_profile">
              <select id="objective_profile" value={form.objective_profile} onChange={(event) => update("objective_profile", event.target.value as ObjectiveProfile)}>
                {OBJECTIVE_PROFILES.map((profile) => <option key={profile} value={profile}>{t(`wizard.objective.${profile}` as TranslationKey)}</option>)}
              </select>
            </Field>
            {form.tuning_mode !== "basic" ? (
              <>
                <div className="form-grid objective-weight-grid">
                  <Field label="Tracking accuracy weight" htmlFor="objective_weight_tracking" error={errors.objective_weights}>
                    <input id="objective_weight_tracking" type="number" min="0" max="100" step="0.05" value={form.objective_weight_tracking} onChange={handleTextChange("objective_weight_tracking")} />
                  </Field>
                  <Field label="Completion speed weight" htmlFor="objective_weight_speed">
                    <input id="objective_weight_speed" type="number" min="0" max="100" step="0.05" value={form.objective_weight_speed} onChange={handleTextChange("objective_weight_speed")} />
                  </Field>
                  <Field label="Smoothness weight" htmlFor="objective_weight_smoothness">
                    <input id="objective_weight_smoothness" type="number" min="0" max="100" step="0.05" value={form.objective_weight_smoothness} onChange={handleTextChange("objective_weight_smoothness")} />
                  </Field>
                  <Field label="Robust pass-rate weight" htmlFor="objective_weight_robustness">
                    <input id="objective_weight_robustness" type="number" min="0" max="100" step="0.05" value={form.objective_weight_robustness} onChange={handleTextChange("objective_weight_robustness")} />
                  </Field>
                </div>
                <div className="form-grid">
                  <Field label="Robust aggregation" htmlFor="robust_aggregation" error={errors.robust_aggregation}>
                    <select id="robust_aggregation" value={form.robust_aggregation} onChange={(event) => update("robust_aggregation", event.target.value as RobustAggregation)}>
                      <option value="mean">Mean</option>
                      <option value="worst">Worst case</option>
                      <option value="cvar">CVaR tail risk</option>
                      <option value="percentile">Percentile</option>
                    </select>
                  </Field>
                  {form.robust_aggregation === "cvar" ? <Field label="CVaR alpha" htmlFor="cvar_alpha" error={errors.cvar_alpha}><input id="cvar_alpha" type="number" step="0.05" value={form.cvar_alpha} onChange={handleTextChange("cvar_alpha")} /></Field> : null}
                  {form.robust_aggregation === "percentile" ? <Field label="Percentile" htmlFor="percentile" error={errors.percentile}><input id="percentile" type="number" step="1" value={form.percentile} onChange={handleTextChange("percentile")} /></Field> : null}
                </div>
              </>
            ) : null}
          </SectionCard>
        </div>

        <div hidden={step !== 2} className="wizard-panel">
          <SectionCard title={t("wizard.section.parameters")} description={t("wizard.section.parametersDesc")}>
            <ParameterSelector
              catalog={catalog.parameters}
              catalogSource={catalog.source}
              mode={form.tuning_mode}
              selections={selections}
              estimatedTrials={estimatedTrials}
              errors={errors}
              onChange={setSelections}
              onApplyPreset={applyModePreset}
            />
            <details className="legacy-compatibility-fields">
              <summary>{t("wizard.legacyTitle")}</summary>
              <p className="form-hint">{t("wizard.legacyHint")}</p>
              <div className="form-grid">
                {([
                  ["baseline_kp_xy", "kp_xy"],
                  ["baseline_kd_xy", "kd_xy"],
                  ["baseline_ki_xy", "ki_xy"],
                  ["baseline_vel_limit", "vel_limit"],
                  ["baseline_accel_limit", "accel_limit"],
                  ["baseline_disturbance_rejection", "disturbance_rejection"],
                ] as const).map(([key, label]) => (
                  <Field key={key} label={label} htmlFor={key} error={errors[key]}>
                    <input id={key} type="number" step="any" value={form[key]} onChange={handleTextChange(key)} />
                  </Field>
                ))}
              </div>
              <button type="button" className="btn btn-ghost btn-small" onClick={resetBaselineDefaults}>{t("wizard.resetBaseline")}</button>
            </details>
          </SectionCard>
        </div>

        <div hidden={step !== 3} className="wizard-panel">
          <SectionCard title={t("wizard.section.scenarios")} description={t("wizard.section.scenariosDesc")}>
            <div className="form-grid">
              {(["north", "east", "south", "west"] as const).map((direction) => {
                const key = `wind_${direction}` as const;
                return <Field key={key} label={`Wind ${direction}`} required htmlFor={key} error={errors[key]} hint="m/s, allowed -10 to 10"><input id={key} type="number" step="0.1" value={form[key]} onChange={handleTextChange(key)} /></Field>;
              })}
              <Field label="Sensor Noise Level" required htmlFor="sensor_noise_level" error={errors.sensor_noise_level}>
                <select id="sensor_noise_level" value={form.sensor_noise_level} onChange={(event) => update("sensor_noise_level", event.target.value as SensorNoiseLevel)}>
                  {SENSOR_NOISE_LEVELS.map((level) => <option key={level} value={level}>{level}</option>)}
                </select>
              </Field>
              <Field label="Search seeds" required htmlFor="search_seeds" error={errors.search_seeds} hint="Common seeds shared by every candidate.">
                <input id="search_seeds" value={form.search_seeds} onChange={handleTextChange("search_seeds")} />
              </Field>
              <Field label="Holdout seeds" required htmlFor="holdout_seeds" error={errors.holdout_seeds ?? errors.seed_overlap} hint="Never used to propose candidates.">
                <input id="holdout_seeds" value={form.holdout_seeds} onChange={handleTextChange("holdout_seeds")} />
              </Field>
              <Field label="Common random numbers" htmlFor="common_random_numbers" hint="Makes candidate comparisons use matched stochastic conditions.">
                <select id="common_random_numbers" value={form.common_random_numbers ? "yes" : "no"} onChange={(event) => update("common_random_numbers", event.target.value === "yes")}>
                  <option value="yes">yes</option><option value="no">no</option>
                </select>
              </Field>
            </div>
            <button type="button" className="btn btn-ghost" onClick={() => setShowAdvancedScenario((shown) => !shown)}>{showAdvancedScenario ? t("wizard.hideAdvanced") : t("wizard.showAdvanced")}</button>
            {showAdvancedScenario ? (
              <div className="advanced-scenario-panel">
                <div className="form-grid">
                  <Field label="Enable advanced scenario" htmlFor="advanced_enabled"><select id="advanced_enabled" value={form.advanced_enabled ? "yes" : "no"} onChange={(event) => update("advanced_enabled", event.target.value === "yes")}><option value="no">no</option><option value="yes">yes</option></select></Field>
                  <Field label="Enable gust" htmlFor="gust_enabled"><select id="gust_enabled" value={form.gust_enabled ? "yes" : "no"} onChange={(event) => update("gust_enabled", event.target.value === "yes")}><option value="no">no</option><option value="yes">yes</option></select></Field>
                  <Field label="Gust magnitude (m/s)" htmlFor="gust_magnitude_mps" error={errors.gust_magnitude_mps}><input id="gust_magnitude_mps" type="number" step="0.1" value={form.gust_magnitude_mps} onChange={handleTextChange("gust_magnitude_mps")} /></Field>
                  <Field label="Gust direction (deg)" htmlFor="gust_direction_deg" error={errors.gust_direction_deg}><input id="gust_direction_deg" type="number" step="1" value={form.gust_direction_deg} onChange={handleTextChange("gust_direction_deg")} /></Field>
                  <Field label="Gust period (s)" htmlFor="gust_period_s" error={errors.gust_period_s}><input id="gust_period_s" type="number" step="0.1" value={form.gust_period_s} onChange={handleTextChange("gust_period_s")} /></Field>
                  <Field label="GPS noise (m)" htmlFor="gps_noise_m" error={errors.gps_noise_m}><input id="gps_noise_m" type="number" step="0.1" value={form.gps_noise_m} onChange={handleTextChange("gps_noise_m")} /></Field>
                  <Field label="Baro noise (m)" htmlFor="baro_noise_m" error={errors.baro_noise_m}><input id="baro_noise_m" type="number" step="0.1" value={form.baro_noise_m} onChange={handleTextChange("baro_noise_m")} /></Field>
                  <Field label="IMU noise scale" htmlFor="imu_noise_scale" error={errors.imu_noise_scale}><input id="imu_noise_scale" type="number" step="0.1" value={form.imu_noise_scale} onChange={handleTextChange("imu_noise_scale")} /></Field>
                  <Field label="Dropout rate" htmlFor="dropout_rate" error={errors.dropout_rate}><input id="dropout_rate" type="number" step="0.01" value={form.dropout_rate} onChange={handleTextChange("dropout_rate")} /></Field>
                  <Field label="Battery initial percent" htmlFor="battery_initial_percent" error={errors.battery_initial_percent}><input id="battery_initial_percent" type="number" step="1" value={form.battery_initial_percent} onChange={handleTextChange("battery_initial_percent")} /></Field>
                  <Field label="Battery voltage sag" htmlFor="battery_voltage_sag"><select id="battery_voltage_sag" value={form.battery_voltage_sag ? "yes" : "no"} onChange={(event) => update("battery_voltage_sag", event.target.value === "yes")}><option value="no">no</option><option value="yes">yes</option></select></Field>
                  <Field label="Payload mass (kg)" htmlFor="mass_payload_kg" error={errors.mass_payload_kg}><input id="mass_payload_kg" type="number" step="0.1" value={form.mass_payload_kg} onChange={handleTextChange("mass_payload_kg")} /></Field>
                </div>
                <Field label="Obstacles JSON" htmlFor="obstacles_json" error={errors.obstacles_json} hint="Obstacle editor import format; [] means no obstacles.">
                  <textarea id="obstacles_json" rows={5} value={form.obstacles_json} onChange={handleTextChange("obstacles_json")} />
                </Field>
                <button type="button" className="btn btn-ghost btn-small" onClick={() => update("obstacles_json", OBSTACLES_JSON_EXAMPLE)}>{t("wizard.useObstacleExample")}</button>
              </div>
            ) : null}
          </SectionCard>
        </div>

        <div hidden={step !== 4} className="wizard-panel">
          <SectionCard title={t("wizard.section.track")} description={t("wizard.section.trackDesc")}>
            <div className="form-grid">
              <Field label="Track Type" required htmlFor="track_type" error={errors.track_type}>
                <select id="track_type" value={form.track_type} onChange={(event) => {
                  const next = event.target.value as TrackType;
                  update("track_type", next);
                  if (next === "custom" && form.reference_track_json.trim() === "") update("reference_track_json", CUSTOM_REFERENCE_TRACK_EXAMPLE);
                }}>
                  {TRACK_TYPES.map((track) => <option key={track} value={track}>{track}</option>)}
                </select>
              </Field>
              {form.track_type === "circle" ? <Field label="Circle Radius (m)" htmlFor="circle_radius_m" error={errors.circle_radius_m}><input id="circle_radius_m" type="number" step="0.1" value={form.circle_radius_m} onChange={handleTextChange("circle_radius_m")} /></Field> : null}
              {form.track_type === "u_turn" ? <><Field label="U-turn Straight Length (m)" htmlFor="u_turn_straight_length_m" error={errors.u_turn_straight_length_m}><input id="u_turn_straight_length_m" type="number" step="0.1" value={form.u_turn_straight_length_m} onChange={handleTextChange("u_turn_straight_length_m")} /></Field><Field label="U-turn Radius (m)" htmlFor="u_turn_turn_radius_m" error={errors.u_turn_turn_radius_m}><input id="u_turn_turn_radius_m" type="number" step="0.1" value={form.u_turn_turn_radius_m} onChange={handleTextChange("u_turn_turn_radius_m")} /></Field></> : null}
              {form.track_type === "lemniscate" ? <Field label="Figure-eight Scale (m)" htmlFor="lemniscate_scale_m" error={errors.lemniscate_scale_m}><input id="lemniscate_scale_m" type="number" step="0.1" value={form.lemniscate_scale_m} onChange={handleTextChange("lemniscate_scale_m")} /></Field> : null}
              <Field label="Start X" required htmlFor="start_x" error={errors.start_x}><input id="start_x" type="number" step="0.1" value={form.start_x} onChange={handleTextChange("start_x")} /></Field>
              <Field label="Start Y" required htmlFor="start_y" error={errors.start_y}><input id="start_y" type="number" step="0.1" value={form.start_y} onChange={handleTextChange("start_y")} /></Field>
              <Field label="Altitude (m)" required htmlFor="altitude_m" error={errors.altitude_m} hint="Allowed range: 1.0–20.0"><input id="altitude_m" type="number" min="1" max="20" step="0.1" value={form.altitude_m} onChange={handleTextChange("altitude_m")} /></Field>
            </div>
            {form.track_type !== "custom" ? (
              <div className="generated-track-callout">
                <span>{t("wizard.generatedTrack")}</span>
                <button type="button" className="btn btn-ghost btn-small" onClick={() => {
                  const generated = referenceTrack(form) ?? [];
                  update("reference_track_json", JSON.stringify(generated, null, 2));
                  update("track_type", "custom");
                }}>{t("wizard.convertTrack")}</button>
              </div>
            ) : (
              <>
                <TrackEditor2D
                  points={customTrack}
                  defaultAltitude={Number(form.altitude_m) || 3}
                  onChange={(points) => update("reference_track_json", JSON.stringify(points, null, 2))}
                />
                <details className="json-import" open={Boolean(errors.reference_track_json)}>
                  <summary>{t("wizard.jsonImport")}</summary>
                  <Field label="Reference track (JSON)" required htmlFor="reference_track_json" error={errors.reference_track_json} hint="Paste a JSON waypoint array; the editor updates when the JSON is valid.">
                    <textarea id="reference_track_json" rows={8} value={form.reference_track_json} onChange={handleTextChange("reference_track_json")} />
                  </Field>
                </details>
              </>
            )}
          </SectionCard>
        </div>

        <div hidden={step !== 5} className="wizard-panel">
          <SectionCard title={t("wizard.section.constraints")} description={t("wizard.section.constraintsDesc")}>
            <div className="constraint-badges"><span>✓ {t("wizard.noCrash")}</span><span>✓ {t("wizard.noTimeout")}</span><span>✓ {t("wizard.holdoutValidation")}</span></div>
            <div className="form-grid">
              <Field label="Simulator Backend" required htmlFor="simulator_backend" error={errors.simulator_backend} hint="real_cli runs PX4/Gazebo on a worker; mock is for UI and orchestration checks.">
                <select id="simulator_backend" value={form.simulator_backend} onChange={(event) => update("simulator_backend", event.target.value as SimulatorBackend)}>{SIMULATOR_BACKENDS.map((backend) => <option key={backend} value={backend}>{backend}</option>)}</select>
              </Field>
              <Field label="Optimizer Strategy" required htmlFor="optimizer_strategy" error={errors.optimizer_strategy}>
                <select id="optimizer_strategy" value={form.optimizer_strategy} onChange={(event) => update("optimizer_strategy", event.target.value as OptimizerStrategy)}>{OPTIMIZER_STRATEGIES.map((strategy) => <option key={strategy} value={strategy}>{strategy}</option>)}</select>
              </Field>
              <Field label="Max Iterations" required htmlFor="max_iterations" error={errors.max_iterations}><input id="max_iterations" type="number" min="1" max="100" step="1" value={form.max_iterations} onChange={handleTextChange("max_iterations")} /></Field>
              <Field label="Trials per Candidate" required htmlFor="trials_per_candidate" error={errors.trials_per_candidate}><input id="trials_per_candidate" type="number" min="1" max="10" step="1" value={form.trials_per_candidate} onChange={handleTextChange("trials_per_candidate")} /></Field>
              <Field label="Maximum total trials" required htmlFor="max_total_trials" error={errors.max_total_trials} hint="Absolute queue and cost guardrail, including baseline and failures."><input id="max_total_trials" type="number" min="1" max="10000" step="1" value={form.max_total_trials} onChange={handleTextChange("max_total_trials")} /></Field>
              <Field label="Target RMSE" htmlFor="target_rmse" error={errors.target_rmse}><input id="target_rmse" type="number" step="0.01" value={form.target_rmse} onChange={handleTextChange("target_rmse")} /></Field>
              <Field label="Target Max Error" htmlFor="target_max_error" error={errors.target_max_error}><input id="target_max_error" type="number" step="0.01" value={form.target_max_error} onChange={handleTextChange("target_max_error")} /></Field>
              <Field label="Min Pass Rate" required htmlFor="min_pass_rate" error={errors.min_pass_rate}><input id="min_pass_rate" type="number" min="0" max="1" step="0.05" value={form.min_pass_rate} onChange={handleTextChange("min_pass_rate")} /></Field>
            </div>
            <div className="budget-estimate"><strong>{t("wizard.estimate")}: {estimatedTrials} trials</strong><span>{selectedCount} dimensions · {form.max_iterations} generations · {searchSeedCount} matched search seeds · hard cap {form.max_total_trials}</span></div>
            {form.optimizer_strategy === "gpt" ? (
              <div className="llm-config-panel">
                <h3>{t("wizard.providerTitle")}</h3>
                <div className="form-grid">
                  <Field label="LLM Provider" htmlFor="llm_provider"><select id="llm_provider" value={form.llm_provider} onChange={(event) => {
                    const provider = event.target.value;
                    update("llm_provider", provider);
                    if (provider === "qwen") {
                      update("llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1");
                      update("llm_model", "qwen-plus");
                    } else if (provider === "deepseek") {
                      update("llm_base_url", "https://api.deepseek.com");
                      update("llm_model", "deepseek-v4-flash");
                    } else if (provider === "openai") {
                      update("llm_base_url", "");
                      update("llm_model", "");
                    } else {
                      update("llm_base_url", "");
                      update("llm_model", "");
                    }
                  }}><option value="openai">OpenAI</option><option value="qwen">Qwen</option><option value="deepseek">DeepSeek</option><option value="custom">Custom compatible API</option></select></Field>
                  <Field label="LLM API Key" required htmlFor="llm_api_key" error={errors.llm_api_key} hint={t("wizard.secret")}><input id="llm_api_key" type="password" autoComplete="off" value={form.llm_api_key} onChange={handleTextChange("llm_api_key")} /></Field>
                  <Field label="LLM Model" htmlFor="llm_model" error={errors.llm_model}><input id="llm_model" value={form.llm_model} onChange={handleTextChange("llm_model")} placeholder="Backend default" /></Field>
                  <Field label="Compatible API Base URL" htmlFor="llm_base_url" error={errors.llm_base_url}><input id="llm_base_url" type="url" value={form.llm_base_url} onChange={handleTextChange("llm_base_url")} placeholder="https://…/v1" /></Field>
                </div>
              </div>
            ) : null}
          </SectionCard>
        </div>

        <div hidden={step !== 6} className="wizard-panel">
          <SectionCard title={t("wizard.section.review")} description={t("wizard.section.reviewDesc")}>
            <div className="review-grid">
              <ReviewBlock title={t("wizard.reviewVehicle")}><strong>{form.airframe} · {form.simulator_model}</strong><span>PX4 {form.px4_version}{form.firmware_commit ? ` @ ${form.firmware_commit}` : ""}</span><span>World: {form.simulator_world}</span></ReviewBlock>
              <ReviewBlock title={t("wizard.reviewSearch")}><strong>{selectedCount} tunable parameters</strong><span>{form.optimizer_strategy} · {form.robust_aggregation}</span><span>{catalog.catalog_version ?? "built-in catalog"}</span></ReviewBlock>
              <ReviewBlock title={t("wizard.reviewScenarios")}><strong>{searchSeedCount} matched search seeds</strong><span>{parseSeedList(form.holdout_seeds).values.length} independent holdout seeds</span><span>{form.advanced_enabled ? "Advanced environment enabled" : "Standard environment"}</span></ReviewBlock>
              <ReviewBlock title={t("wizard.reviewBudget")}><strong>At most {form.max_total_trials} trials</strong><span>Estimated plan: {estimatedTrials}</span><span>{form.trials_per_candidate} trials per candidate</span></ReviewBlock>
            </div>
            <div className="review-parameter-list">
              <h3>{t("wizard.selectedParameters")}</h3>
              {selectedParameters(selections).map((parameter) => <code key={parameter.name}>{parameter.name} [{parameter.search_min}, {parameter.search_max}]</code>)}
            </div>
            <Alert tone="info" title={t("wizard.compatibilityTitle")}>
              {t("wizard.compatibilityText")}
            </Alert>
          </SectionCard>
        </div>

        <div className="wizard-actions">
          <button type="button" className="btn btn-ghost" disabled={step === 0 || submitting} onClick={() => setStep((current) => Math.max(0, current - 1))}>{t("wizard.back")}</button>
          <button type="button" className="btn" onClick={saveDraftNow} disabled={submitting}>{t("wizard.save")}</button>
          <button type="button" className="btn" disabled={step === 6 || submitting} onClick={nextStep}>{t("wizard.next")}</button>
          <button className="btn btn-primary" type="submit" disabled={submitting}>{submitting ? "Creating…" : t("wizard.create")}</button>
          <button type="button" className="btn btn-ghost" onClick={handleReset} disabled={submitting}>{t("wizard.reset")}</button>
        </div>
      </form>
    </section>
  );
}

function ReviewBlock({ title, children }: { title: string; children: ReactNode }) {
  return <div className="review-block"><h3>{title}</h3>{children}</div>;
}

interface FieldProps {
  label: string;
  htmlFor: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: ReactNode;
}

function Field({ label, htmlFor, required, error, hint, children }: FieldProps) {
  return (
    <div className={`form-field${error ? " form-field-error" : ""}`}>
      <label htmlFor={htmlFor} className={required ? "form-field-required" : undefined}>{label}</label>
      {children}
      {error ? <span className="form-error" role="alert">{error}</span> : hint ? <span className="form-hint">{hint}</span> : null}
    </div>
  );
}
