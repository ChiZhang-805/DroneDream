import { useEffect, useRef, useState } from "react";
import type {
  ChangeEvent,
  FormEvent,
  ReactNode,
  WheelEvent as ReactWheelEvent,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { Alert } from "../components/Alert";
import { ParameterSelector } from "../components/ParameterSelector";
import { SectionCard } from "../components/SectionCard";
import { TrackEditor2D } from "../components/TrackEditor2D";
import { apiClient, ApiClientError } from "../api/client";
import { openAppSettings } from "../appSettings";
import { publicDemoConsole } from "../features/demo/publicDemo";
import { recordProductEvent } from "../features/analytics/productEvents";
import {
  EXPERIMENTAL_OPTIMIZER_STRATEGIES,
  HARNESS_OPTIMIZER_STRATEGIES,
  LEGACY_OPTIMIZER_STRATEGIES,
  OBJECTIVE_PROFILES,
  OPTIMIZER_STRATEGIES,
  SENSOR_NOISE_LEVELS,
  SIMULATOR_BACKENDS,
  TRACK_TYPES,
  optimizerUsesModelAccess,
} from "../types/api";
import type {
  BaselineParameters,
  BackendCapabilitiesResponse,
  ExperimentStudyConfig,
  JobCreateRequest,
  ObjectiveConfig,
  ObjectiveProfile,
  OptimizerStrategy,
  ParameterCatalogResponse,
  ParameterSpaceSelection,
  RobustAggregation,
  ScenarioAdvancedConfig,
  ScenarioObstacle,
  ScenarioSuiteConfig,
  SensorNoiseLevel,
  SimulatorBackend,
  TrackPoint,
  TrackType,
  TuningMode,
  UserExperiencePreferences,
} from "../types/api";
import {
  BUILTIN_PARAMETER_CATALOG,
  createParameterSelections,
  normalizeApiCatalog,
  selectedParameters,
  type ParameterSelectionMap,
} from "../features/experiment/parameterCatalog";
import { runtimeCapabilityErrors } from "../features/experiment/capabilities";
import {
  optimizerStrategyCard,
  optimizerStrategyDescription,
  optimizerStrategyLabel,
} from "../features/experiment/optimizerStrategies";
import { useModelAccess } from "../features/settings/ModelAccessContext";
import { issueManagedModelGrant } from "../features/settings/cloudModelAccess";
import {
  calculateTrialPlan as calculateTrialPlanFromInputs,
  type TrialPlan,
} from "../features/experiment/trialPlan";
import {
  clearExperimentDraft,
  loadExperimentDraft,
  persistStudyForJob,
  saveExperimentDraft,
} from "../features/experiment/draftStorage";
import { recordManualDraftEdits } from "../features/experiment/assistantDraft";
import { useOptionalAuth } from "../features/auth/AuthContext";
import {
  EXPERIMENT_DRAFT_SCHEMA,
  EXPERIMENT_FORM_DEFAULTS,
  type ExperimentFormState,
  type ScenarioPreset,
} from "../features/experiment/formState";
import { ExperienceTrackPreview } from "../features/experiment/ExperienceTrackPreview";
import {
  applyStarterExperienceTemplate,
  findStarterExperienceTemplate,
  STARTER_EXPERIENCE_CATALOG_VERSION,
  STARTER_EXPERIENCE_TEMPLATES,
  type StarterExperienceId,
  type StarterExperienceTemplate,
} from "../features/experiment/experienceTemplates";
import {
  createExperimentWorkspaceId,
  isExperimentWorkspaceNameAvailable,
  listExperimentWorkspaces,
  registerExperimentWorkspace,
  updateExperimentWorkspace,
} from "../features/experiment/workspaceRegistry";
import { generateReferenceTrack } from "../utils/referenceTrack";
import { formatNumber } from "../utils/format";
import { useI18n } from "../i18n/I18nProvider";
import { useEditionTheme } from "../theme/EditionThemeProvider";
import type { TranslationKey, TranslationParams } from "../i18n/I18nProvider";

type Translate = (key: TranslationKey, params?: TranslationParams) => string;
type FormState = ExperimentFormState;
const DEFAULTS: FormState = (
  ["sim", "lab"].includes(
    (import.meta.env.VITE_DRONEDREAM_EDITION as string | undefined)?.toLowerCase() ?? "",
  )
    ? { ...EXPERIMENT_FORM_DEFAULTS, optimizer_strategy: "llm_harness" }
    : EXPERIMENT_FORM_DEFAULTS
);

function isDraftRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

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

const WIZARD_STEPS: Array<{ key: TranslationKey }> = [
  { key: "wizard.step.flightSetup" },
  { key: "wizard.step.parameters" },
  { key: "wizard.step.scenarios" },
  { key: "wizard.step.constraints" },
  { key: "wizard.step.review" },
];

const STARTER_EXPERIENCE_I18N: Record<
  StarterExperienceId,
  { title: TranslationKey; description: TranslationKey }
> = {
  "hover-basics": {
    title: "wizard.starter.hover.title",
    description: "wizard.starter.hover.description",
  },
  "first-circle": {
    title: "wizard.starter.circle.title",
    description: "wizard.starter.circle.description",
  },
  "light-wind-circle": {
    title: "wizard.starter.wind.title",
    description: "wizard.starter.wind.description",
  },
  "wind-sensor-circle": {
    title: "wizard.starter.combined.title",
    description: "wizard.starter.combined.description",
  },
};

const OBJECTIVE_WEIGHT_PRESETS: Record<
  Exclude<ObjectiveProfile, "custom">,
  Pick<
    FormState,
    | "objective_weight_tracking"
    | "objective_weight_speed"
    | "objective_weight_smoothness"
    | "objective_weight_robustness"
    | "robust_aggregation"
    | "cvar_alpha"
    | "percentile"
  >
> = {
  stable: {
    objective_weight_tracking: "1",
    objective_weight_speed: "0.15",
    objective_weight_smoothness: "0.75",
    objective_weight_robustness: "0.8",
    robust_aggregation: "mean",
    cvar_alpha: "0.2",
    percentile: "95",
  },
  fast: {
    objective_weight_tracking: "0.75",
    objective_weight_speed: "1",
    objective_weight_smoothness: "0.2",
    objective_weight_robustness: "0.4",
    robust_aggregation: "mean",
    cvar_alpha: "0.2",
    percentile: "95",
  },
  smooth: {
    objective_weight_tracking: "0.75",
    objective_weight_speed: "0.2",
    objective_weight_smoothness: "1",
    objective_weight_robustness: "0.65",
    robust_aggregation: "mean",
    cvar_alpha: "0.2",
    percentile: "95",
  },
  robust: {
    objective_weight_tracking: "1",
    objective_weight_speed: "0.25",
    objective_weight_smoothness: "0.35",
    objective_weight_robustness: "1",
    robust_aggregation: "cvar",
    cvar_alpha: "0.2",
    percentile: "95",
  },
};

const FIELD_STEPS: Record<string, number> = {
  display_name: 0,
  px4_version: 0,
  firmware_commit: 0,
  vehicle_type: 0,
  airframe: 0,
  simulator_model: 0,
  simulator_world: 0,
  simulation_speed_factor: 0,
  instance_id: 0,
  objective_profile: 0,
  objective_weights: 0,
  robust_aggregation: 0,
  cvar_alpha: 0,
  percentile: 0,
  parameters: 1,
  baseline_kp_xy: 1,
  baseline_kd_xy: 1,
  baseline_ki_xy: 1,
  baseline_vel_limit: 1,
  baseline_accel_limit: 1,
  baseline_disturbance_rejection: 1,
  wind_north: 2,
  wind_east: 2,
  wind_south: 2,
  wind_west: 2,
  sensor_noise_level: 2,
  search_seeds: 2,
  holdout_seeds: 2,
  seed_overlap: 2,
  scenario_cases: 2,
  advanced_enabled: 2,
  gps_noise_m: 2,
  baro_noise_m: 2,
  imu_noise_scale: 2,
  dropout_rate: 2,
  battery_initial_percent: 2,
  mass_payload_kg: 2,
  gust_magnitude_mps: 2,
  gust_direction_deg: 2,
  gust_period_s: 2,
  obstacles_json: 2,
  track_type: 0,
  reference_track_json: 0,
  circle_radius_m: 0,
  u_turn_straight_length_m: 0,
  u_turn_turn_radius_m: 0,
  lemniscate_scale_m: 0,
  start_x: 0,
  start_y: 0,
  altitude_m: 0,
  simulator_backend: 3,
  optimizer_strategy: 3,
  max_iterations: 3,
  trials_per_candidate: 3,
  max_total_trials: 3,
  exploration_additional_generations: 3,
  exploration_additional_trials: 3,
  exploration_additional_provider_turns: 3,
  exploration_additional_time_minutes: 3,
  target_rmse: 3,
  target_max_error: 3,
  min_pass_rate: 3,
  llm_api_key: 3,
  llm_model: 3,
  llm_base_url: 3,
};

const SIMULATOR_WORLD_KEYS: Record<string, TranslationKey> = {
  default: "wizard.world.default",
  aruco: "wizard.world.aruco",
  baylands: "wizard.world.baylands",
  ridge: "wizard.world.ridge",
  walls: "wizard.world.walls",
  windy: "wizard.world.windy",
  moving_platform: "wizard.world.movingPlatform",
};

const PX4_VERSION_HINT_KEYS: Record<string, TranslationKey> = {
  "v1.16": "wizard.hint.px4.v116",
  "v1.17": "wizard.hint.px4.v117",
  main: "wizard.hint.px4.main",
};

const AIRFRAME_HINT_KEYS: Record<string, TranslationKey> = {
  x500: "wizard.hint.airframe.x500",
  quad_x: "wizard.hint.airframe.quadX",
};

const SIMULATOR_MODEL_HINT_KEYS: Record<string, TranslationKey> = {
  gz_x500: "wizard.hint.model.x500",
  gz_x500_depth: "wizard.hint.model.depth",
  gz_x500_vision: "wizard.hint.model.vision",
  gz_x500_mono_cam: "wizard.hint.model.monoFront",
  gz_x500_mono_cam_down: "wizard.hint.model.monoDown",
  gz_x500_lidar_down: "wizard.hint.model.lidarDown",
  gz_x500_lidar_front: "wizard.hint.model.lidarFront",
  gz_x500_lidar_2d: "wizard.hint.model.lidar2d",
  gz_x500_gimbal: "wizard.hint.model.gimbal",
};

const SIMULATOR_WORLD_HINT_KEYS: Record<string, TranslationKey> = {
  default: "wizard.hint.world.default",
  aruco: "wizard.hint.world.aruco",
  baylands: "wizard.hint.world.baylands",
  ridge: "wizard.hint.world.ridge",
  walls: "wizard.hint.world.walls",
  windy: "wizard.hint.world.windy",
  moving_platform: "wizard.hint.world.movingPlatform",
};

const OBJECTIVE_HINT_KEYS: Record<ObjectiveProfile, TranslationKey> = {
  stable: "wizard.hint.objective.stable",
  fast: "wizard.hint.objective.fast",
  smooth: "wizard.hint.objective.smooth",
  robust: "wizard.hint.objective.robust",
  custom: "wizard.hint.objective.custom",
};

const AGGREGATION_HINT_KEYS: Record<RobustAggregation, TranslationKey> = {
  mean: "wizard.hint.aggregation.mean",
  worst: "wizard.hint.aggregation.worst",
  cvar: "wizard.hint.aggregation.cvar",
  percentile: "wizard.hint.aggregation.percentile",
};

const TRACK_HINT_KEYS: Record<TrackType, TranslationKey> = {
  hover: "wizard.hint.track.hover",
  circle: "wizard.hint.track.circle",
  u_turn: "wizard.hint.track.uTurn",
  lemniscate: "wizard.hint.track.lemniscate",
  custom: "wizard.hint.track.custom",
};

const SENSOR_NOISE_HINT_KEYS: Record<SensorNoiseLevel, TranslationKey> = {
  low: "wizard.hint.noise.low",
  medium: "wizard.hint.noise.medium",
  high: "wizard.hint.noise.high",
};

const SIMULATOR_BACKEND_HINT_KEYS: Record<SimulatorBackend, TranslationKey> = {
  real_cli: "wizard.hint.backend.realCli",
  mock: "wizard.hint.backend.mock",
};
const USER_SIMULATOR_BACKENDS: readonly SimulatorBackend[] = import.meta.env.MODE === "test"
  ? SIMULATOR_BACKENDS
  : ["real_cli"];

function selectedHint(
  keys: Record<string, TranslationKey>,
  value: string,
  t: Translate,
): string {
  const key = keys[value];
  return key ? t(key) : "";
}

function simulatorWorldLabel(world: string, t: Translate): string {
  const key = SIMULATOR_WORLD_KEYS[world];
  return key ? t(key) : t("wizard.world.unknown");
}

function llmProviderLabel(provider: string, t: Translate): string {
  if (provider === "openai") return "OpenAI";
  if (provider === "qwen") return "Qwen";
  if (provider === "deepseek") return "DeepSeek";
  return t("wizard.llm.customProvider");
}

function opensAdvancedScenarioDialog(errorKey: string): boolean {
  return errorKey === "obstacles_json";
}

function opensTrackDialog(errorKey: string): boolean {
  return errorKey === "reference_track_json";
}

function opensModelSettings(errorKey: string): boolean {
  return errorKey.startsWith("llm_");
}

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

function localizedIssue(
  t: Translate | undefined,
  key: TranslationKey,
  params?: TranslationParams,
): string {
  return t ? t(key, params) : key;
}

function parseSeedList(raw: string, t?: Translate): { values: number[]; error: string | null } {
  const tokens = raw.split(/[\s,]+/).filter(Boolean);
  const values = tokens.map(Number);
  if (values.length === 0) return { values: [], error: localizedIssue(t, "wizard.validation.seedRequired") };
  if (values.length > 100) return { values: [], error: localizedIssue(t, "wizard.validation.seedMax") };
  if (values.some((value) => !Number.isInteger(value) || value < 0)) {
    return { values: [], error: localizedIssue(t, "wizard.validation.seedFormat") };
  }
  if (new Set(values).size !== values.length) {
    return { values: [], error: localizedIssue(t, "wizard.validation.seedFormat") };
  }
  return { values, error: null };
}

function parseReferenceTrackInput(raw: string, t?: Translate): {
  points: TrackPoint[] | null;
  error: string | null;
} {
  if (raw.trim() === "") return { points: null, error: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return { points: null, error: localizedIssue(t, "wizard.validation.jsonArrayValid") };
  }
  if (!Array.isArray(parsed)) return { points: null, error: localizedIssue(t, "wizard.validation.jsonArray") };
  if (parsed.length > 10_000) {
    return {
      points: null,
      error: localizedIssue(t, "wizard.validation.trackPointMax", { max: 10_000 }),
    };
  }
  const points: TrackPoint[] = [];
  for (let index = 0; index < parsed.length; index += 1) {
    const value = parsed[index];
    if (!value || typeof value !== "object") {
      return { points: null, error: localizedIssue(t, "wizard.validation.trackPointObject", { index: index + 1 }) };
    }
    const candidate = value as { x?: unknown; y?: unknown; z?: unknown };
    const x = candidate.x;
    const y = candidate.y;
    const zValue = candidate.z;
    if (typeof x !== "number" || !Number.isFinite(x) || typeof y !== "number" || !Number.isFinite(y)) {
      return { points: null, error: localizedIssue(t, "wizard.validation.trackPointXY", { index: index + 1 }) };
    }
    if (zValue !== undefined && zValue !== null && (typeof zValue !== "number" || !Number.isFinite(zValue))) {
      return { points: null, error: localizedIssue(t, "wizard.validation.trackPointZ", { index: index + 1 }) };
    }
    points.push({ x, y, z: zValue === undefined || zValue === null ? null : zValue });
  }
  return { points, error: null };
}

function finiteObstacleNumber(
  value: unknown,
  field: string,
  index: number,
  t?: Translate,
): { value: number; error: string | null } {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return { value: 0, error: localizedIssue(t, "wizard.validation.obstacleFinite", { index: index + 1, field }) };
  }
  return { value, error: null };
}

function positiveObstacleNumber(
  value: unknown,
  field: string,
  index: number,
  t?: Translate,
): { value: number; error: string | null } {
  const parsed = finiteObstacleNumber(value, field, index, t);
  if (parsed.error) return parsed;
  return parsed.value > 0
    ? parsed
    : { value: 0, error: localizedIssue(t, "wizard.validation.obstaclePositive", { index: index + 1, field }) };
}

function parseObstacles(raw: string, t?: Translate): { value: ScenarioObstacle[]; error: string | null } {
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return { value: [], error: localizedIssue(t, "wizard.validation.jsonArray") };
    if (parsed.length > 100) return { value: [], error: localizedIssue(t, "wizard.validation.obstacleMax") };
    const obstacles: ScenarioObstacle[] = [];
    for (let index = 0; index < parsed.length; index += 1) {
      const item = parsed[index];
      if (!isDraftRecord(item)) {
        return { value: [], error: localizedIssue(t, "wizard.validation.obstacleObject", { index: index + 1 }) };
      }
      if (item.type !== "cylinder" && item.type !== "box") {
        return { value: [], error: localizedIssue(t, "wizard.validation.obstacleType", { index: index + 1 }) };
      }
      const x = finiteObstacleNumber(item.x, "x", index, t);
      const y = finiteObstacleNumber(item.y, "y", index, t);
      const z = finiteObstacleNumber(item.z, "z", index, t);
      const coordinateError = x.error ?? y.error ?? z.error;
      if (coordinateError) return { value: [], error: coordinateError };
      if (item.type === "cylinder") {
        const radius = positiveObstacleNumber(item.radius, "radius", index, t);
        const height = positiveObstacleNumber(item.height, "height", index, t);
        if (radius.error ?? height.error) {
          return { value: [], error: radius.error ?? height.error };
        }
        obstacles.push({
          type: "cylinder",
          x: x.value,
          y: y.value,
          z: z.value,
          radius: radius.value,
          height: height.value,
        });
      } else {
        const sizeX = positiveObstacleNumber(item.size_x, "size_x", index, t);
        const sizeY = positiveObstacleNumber(item.size_y, "size_y", index, t);
        const sizeZ = positiveObstacleNumber(item.size_z, "size_z", index, t);
        const sizeError = sizeX.error ?? sizeY.error ?? sizeZ.error;
        if (sizeError) return { value: [], error: sizeError };
        obstacles.push({
          type: "box",
          x: x.value,
          y: y.value,
          z: z.value,
          size_x: sizeX.value,
          size_y: sizeY.value,
          size_z: sizeZ.value,
        });
      }
    }
    return { value: obstacles, error: null };
  } catch {
    return { value: [], error: localizedIssue(t, "wizard.validation.jsonArrayValid") };
  }
}

function calculateTrialPlan(form: FormState, selectedDimensions = 1): TrialPlan {
  const search = parseSeedList(form.search_seeds);
  const holdout = parseSeedList(form.holdout_seeds);
  const searchCaseCount = [
    form.nominal_search_enabled,
    form.wind_search_enabled,
    form.noise_search_enabled,
  ].filter(Boolean).length;
  const holdoutCaseCount = [
    form.nominal_holdout_enabled,
    form.combined_holdout_enabled,
  ].filter(Boolean).length;
  return calculateTrialPlanFromInputs({
    searchSeedCount: search.error ? null : search.values.length,
    holdoutSeedCount: holdout.error ? null : holdout.values.length,
    searchCaseCount,
    holdoutCaseCount,
    maxIterations: parseNumber(form.max_iterations),
    maxTotalTrials: parseNumber(form.max_total_trials),
    optimizerStrategy: form.optimizer_strategy,
    selectedDimensions,
  });
}

function errorStep(key: string, catalog: ParameterCatalogResponse): number {
  if (FIELD_STEPS[key] !== undefined) return FIELD_STEPS[key];
  if (catalog.parameters.some((parameter) => parameter.name === key)) return 1;
  return 0;
}

function focusErrorField(key: string, catalog: ParameterCatalogResponse): void {
  const isParameter = catalog.parameters.some((parameter) => parameter.name === key);
  const aliases: Record<string, string> = {
    objective_weights: "objective_weight_tracking",
    seed_overlap: "holdout_seeds",
    parameters: "parameter-search",
  };
  const candidateIds = isParameter
    ? [`parameter-${key}-min`, `parameter-${key}-baseline`]
    : [aliases[key] ?? key];
  window.setTimeout(() => {
    for (const id of candidateIds) {
      const field = document.getElementById(id);
      if (field) {
        field.focus();
        return;
      }
    }
  }, 0);
}

function validate(
  form: FormState,
  selections: ParameterSelectionMap,
  catalog: ParameterCatalogResponse,
  capabilities: BackendCapabilitiesResponse | null = null,
  t: Translate,
): FieldErrors {
  const errors: FieldErrors = {};
  if (form.display_name.trim() === "") {
    errors.display_name = t("wizard.validation.required");
  } else if (form.display_name.trim().length > 255) {
    errors.display_name = t("wizard.validation.nameMax");
  }
  (["px4_version", "vehicle_type", "airframe", "simulator_model", "simulator_world"] as const).forEach((key) => {
    if (form[key].trim() === "") errors[key] = t("wizard.validation.required");
  });
  if (
    form.px4_version.trim() !== "" &&
    catalog.px4_version !== form.px4_version
  ) {
    errors.px4_version = t("wizard.validation.catalogMissing", { version: form.px4_version });
  }
  if (
    form.firmware_commit.trim() !== "" &&
    !/^[0-9a-f]{7,40}$/iu.test(form.firmware_commit.trim())
  ) {
    errors.firmware_commit = t("wizard.validation.firmwareSha");
  }
  const simulationSpeedFactor = parseNumber(form.simulation_speed_factor);
  if (
    simulationSpeedFactor === null ||
    simulationSpeedFactor < 0.1 ||
    simulationSpeedFactor > 100
  ) {
    errors.simulation_speed_factor = t("wizard.validation.between", { min: 0.1, max: 100 });
  }
  const instanceId = parseNumber(form.instance_id);
  if (
    instanceId === null ||
    !Number.isInteger(instanceId) ||
    instanceId < 0 ||
    instanceId > 255
  ) {
    errors.instance_id = t("wizard.validation.integerBetween", { min: 0, max: 255 });
  }
  if (!OBJECTIVE_PROFILES.includes(form.objective_profile)) {
    errors.objective_profile = t("wizard.validation.objectiveProfile");
  }
  const weights = [
    form.objective_weight_tracking,
    form.objective_weight_speed,
    form.objective_weight_smoothness,
    form.objective_weight_robustness,
  ].map(parseNumber);
  if (weights.some((weight) => weight === null || weight < 0 || weight > 100)) {
    errors.objective_weights = t("wizard.validation.objectiveWeightsRange");
  } else if (weights.reduce<number>((sum, weight) => sum + Number(weight), 0) <= 0) {
    errors.objective_weights = t("wizard.validation.objectivePositive");
  }
  if (!["mean", "worst", "cvar", "percentile"].includes(form.robust_aggregation)) {
    errors.robust_aggregation = t("wizard.validation.aggregation");
  }
  if (form.robust_aggregation === "cvar") {
    const cvarAlpha = parseNumber(form.cvar_alpha);
    if (cvarAlpha === null || cvarAlpha <= 0 || cvarAlpha >= 1) {
      errors.cvar_alpha = t("wizard.validation.exclusive", { min: 0, max: 1 });
    }
  }
  if (form.robust_aggregation === "percentile") {
    const percentile = parseNumber(form.percentile);
    if (percentile === null || percentile <= 0 || percentile > 100) {
      errors.percentile = t("wizard.validation.percentile");
    }
  }

  const selected = Object.values(selections).filter((selection) => selection.selected);
  if (selected.length === 0) errors.parameters = t("wizard.validation.parameterRequired");
  else if (selected.length > 64) errors.parameters = t("wizard.validation.parameterMax");
  for (const parameter of catalog.parameters) {
    const selection = selections[parameter.name];
    if (!selection?.selected) continue;
    if (
      !Number.isFinite(selection.baseline) ||
      !Number.isFinite(selection.search_min) ||
      !Number.isFinite(selection.search_max)
    ) {
      errors[parameter.name] = t("wizard.validation.parameterFinite");
    } else if (
      parameter.value_type === "integer" &&
      ![
        selection.baseline,
        selection.search_min,
        selection.search_max,
      ].every(Number.isInteger)
    ) {
      errors[parameter.name] = t("wizard.validation.parameterInteger");
    } else if (selection.search_min >= selection.search_max) {
      errors[parameter.name] = t("wizard.validation.searchOrder");
    } else if (
      selection.search_min < parameter.absolute_min ||
      selection.search_max > parameter.absolute_max
    ) {
      errors[parameter.name] = t("wizard.validation.searchInside", { min: parameter.absolute_min, max: parameter.absolute_max });
    } else if (
      selection.baseline < selection.search_min ||
      selection.baseline > selection.search_max
    ) {
      errors[parameter.name] = t("wizard.validation.baselineInside");
    } else if (selection.scale === "log" && selection.search_min <= 0) {
      errors[parameter.name] = t("wizard.validation.logPositive");
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
      errors[key] = t("wizard.validation.between", { min: minimum, max: maximum });
    }
  }

  if (!TRACK_TYPES.includes(form.track_type)) errors.track_type = t("wizard.validation.trackType");
  const parsedTrack = parseReferenceTrackInput(form.reference_track_json, t);
  if (parsedTrack.error) errors.reference_track_json = parsedTrack.error;
  if (form.track_type === "custom" && (!parsedTrack.points || parsedTrack.points.length < 2)) {
    errors.reference_track_json = parsedTrack.error ?? t("wizard.validation.customTrack");
  }
  if (form.track_type === "circle") {
    const value = parseNumber(form.circle_radius_m);
    if (value === null || value <= 0 || value > 100) errors.circle_radius_m = t("wizard.validation.positiveAtMost", { max: 100 });
  }
  if (form.track_type === "u_turn") {
    const straight = parseNumber(form.u_turn_straight_length_m);
    const radius = parseNumber(form.u_turn_turn_radius_m);
    if (straight === null || straight <= 0 || straight > 200) errors.u_turn_straight_length_m = t("wizard.validation.positiveAtMost", { max: 200 });
    if (radius === null || radius <= 0 || radius > 100) errors.u_turn_turn_radius_m = t("wizard.validation.positiveAtMost", { max: 100 });
  }
  if (form.track_type === "lemniscate") {
    const value = parseNumber(form.lemniscate_scale_m);
    if (value === null || value <= 0 || value > 100) errors.lemniscate_scale_m = t("wizard.validation.positiveAtMost", { max: 100 });
  }
  const startX = parseNumber(form.start_x);
  const startY = parseNumber(form.start_y);
  if (startX === null) errors.start_x = t("wizard.validation.requiredNumber");
  if (startY === null) errors.start_y = t("wizard.validation.requiredNumber");
  if (
    form.track_type === "hover"
    && startX !== null
    && startY !== null
    && (Math.abs(startX) > 1e-9 || Math.abs(startY) > 1e-9)
  ) {
    errors.start_x = t("wizard.validation.hoverOrigin");
    errors.start_y = t("wizard.validation.hoverOrigin");
  }
  const altitude = parseNumber(form.altitude_m);
  if (altitude === null) errors.altitude_m = t("wizard.validation.requiredNumber");
  else if (altitude < 1 || altitude > 20) errors.altitude_m = t("wizard.validation.between", { min: 1, max: 20 });

  (["wind_north", "wind_east", "wind_south", "wind_west"] as const).forEach((key) => {
    const value = parseNumber(form[key]);
    if (value === null) errors[key] = t("wizard.validation.requiredNumber");
    else if (value < -10 || value > 10) errors[key] = t("wizard.validation.between", { min: -10, max: 10 });
  });
  if (!SENSOR_NOISE_LEVELS.includes(form.sensor_noise_level)) {
    errors.sensor_noise_level = t("wizard.validation.sensorNoise");
  }
  const searchSeeds = parseSeedList(form.search_seeds, t);
  const holdoutSeeds = parseSeedList(form.holdout_seeds, t);
  if (searchSeeds.error) errors.search_seeds = searchSeeds.error;
  const hasTrainingCase = form.nominal_search_enabled || form.wind_search_enabled || form.noise_search_enabled;
  const hasHoldoutCase = form.nominal_holdout_enabled || form.combined_holdout_enabled;
  if (!hasTrainingCase) errors.scenario_cases = t("wizard.validation.searchScenario");
  if (hasHoldoutCase && holdoutSeeds.error) errors.holdout_seeds = holdoutSeeds.error;
  if (
    !searchSeeds.error &&
    hasHoldoutCase &&
    !holdoutSeeds.error &&
    holdoutSeeds.values.some((seed) => searchSeeds.values.includes(seed))
  ) {
    errors.seed_overlap = t("wizard.validation.holdoutOverlap");
  }

  if (form.advanced_enabled) {
    const bounded: Array<[keyof FormState, number, number, string]> = [
      ["gps_noise_m", 0, 100, t("wizard.validation.between", { min: 0, max: 100 })],
      ["baro_noise_m", 0, 100, t("wizard.validation.between", { min: 0, max: 100 })],
      ["imu_noise_scale", 0, 10, t("wizard.validation.between", { min: 0, max: 10 })],
      ["dropout_rate", 0, 1, t("wizard.validation.between", { min: 0, max: 1 })],
      ["battery_initial_percent", 0, 100, t("wizard.validation.between", { min: 0, max: 100 })],
    ];
    for (const [key, minimum, maximum, message] of bounded) {
      const value = parseNumber(form[key] as string);
      if (value === null || value < minimum || value > maximum) errors[key] = message;
    }
    if (form.mass_payload_kg.trim() !== "") {
      const value = parseNumber(form.mass_payload_kg);
      if (value === null || value < 0 || value > 20) errors.mass_payload_kg = t("wizard.validation.between", { min: 0, max: 20 });
    }
    if (form.gust_enabled) {
      const magnitude = parseNumber(form.gust_magnitude_mps);
      const direction = parseNumber(form.gust_direction_deg);
      const period = parseNumber(form.gust_period_s);
      if (magnitude === null || magnitude < 0 || magnitude > 30) errors.gust_magnitude_mps = t("wizard.validation.gustMagnitude");
      if (direction === null || direction < 0 || direction >= 360) errors.gust_direction_deg = t("wizard.validation.gustDirection");
      if (period === null || period <= 0 || period > 300) errors.gust_period_s = t("wizard.validation.gustPeriod");
      const northMps = parseNumber(form.wind_north);
      const eastMps = parseNumber(form.wind_east);
      const southMps = parseNumber(form.wind_south);
      const westMps = parseNumber(form.wind_west);
      if (
        magnitude !== null && magnitude > 0 &&
        direction !== null && direction >= 0 && direction < 360 &&
        northMps !== null && eastMps !== null && southMps !== null && westMps !== null
      ) {
        const netNorthMps = northMps - southMps;
        const netEastMps = eastMps - westMps;
        if (Math.hypot(netNorthMps, netEastMps) > 1e-9) {
          const steadyDirectionDeg =
            ((Math.atan2(netEastMps, netNorthMps) * 180) / Math.PI + 360) % 360;
          const angularDeltaDeg = Math.abs(
            ((direction - steadyDirectionDeg + 540) % 360) - 180,
          );
          if (angularDeltaDeg > 0.001) {
            errors.gust_direction_deg = t("wizard.validation.gustDirectionAlignment", {
              direction: formatNumber(steadyDirectionDeg, 3),
            });
          }
        }
      }
    }
    const obstacleResult = parseObstacles(form.obstacles_json, t);
    if (obstacleResult.error) errors.obstacles_json = obstacleResult.error;
  }

  if (!SIMULATOR_BACKENDS.includes(form.simulator_backend)) {
    errors.simulator_backend = t("wizard.validation.simulatorBackend");
  } else if (form.simulator_backend === "real_cli") {
    Object.assign(
      errors,
      runtimeCapabilityErrors(
        form.simulator_backend,
        form.optimizer_strategy,
        capabilities,
        {
          realSimulatorNotReady: t("wizard.realCliUnavailable"),
          gptNotReady: t("wizard.gptUnavailable"),
        },
      ),
    );
  }
  if (!OPTIMIZER_STRATEGIES.includes(form.optimizer_strategy)) {
    errors.optimizer_strategy = t("wizard.validation.optimizerStrategy");
  } else if (optimizerUsesModelAccess(form.optimizer_strategy)) {
    Object.assign(
      errors,
      runtimeCapabilityErrors(
        form.simulator_backend,
        form.optimizer_strategy,
        capabilities,
        {
          realSimulatorNotReady: t("wizard.realCliUnavailable"),
          gptNotReady: t("wizard.gptUnavailable"),
        },
      ),
    );
  }
  const maxIterations = parseNumber(form.max_iterations);
  if (maxIterations === null || !Number.isInteger(maxIterations) || maxIterations < 1 || maxIterations > 100) {
    errors.max_iterations = t("wizard.validation.integerBetween", { min: 1, max: 100 });
  }
  const trials = parseNumber(form.trials_per_candidate);
  if (trials === null || !Number.isInteger(trials) || trials < 1 || trials > 10) {
    errors.trials_per_candidate = t("wizard.validation.integerBetween", { min: 1, max: 10 });
  }
  const maxTotal = parseNumber(form.max_total_trials);
  if (maxTotal === null || !Number.isInteger(maxTotal) || maxTotal < 1 || maxTotal > 10000) {
    errors.max_total_trials = t("wizard.validation.integerBetween", { min: 1, max: 10000 });
  } else {
    const trialPlan = calculateTrialPlan(form);
    if (trialPlan.minimumRequiredTrials > 0 && maxTotal < trialPlan.minimumRequiredTrials) {
      errors.max_total_trials = t(
        form.optimizer_strategy === "none"
          ? "wizard.validation.minBaselineBudget"
          : "wizard.validation.minTrialBudget",
        { count: trialPlan.minimumRequiredTrials },
      );
    }
  }
  if (form.continue_exploration_after_qualified) {
    const generations = parseNumber(form.exploration_additional_generations);
    const explorationTrials = parseNumber(form.exploration_additional_trials);
    const providerTurns = parseNumber(form.exploration_additional_provider_turns);
    const timeMinutes = parseNumber(form.exploration_additional_time_minutes);
    if (
      generations === null || !Number.isInteger(generations)
      || generations < 1 || generations > 32
    ) {
      errors.exploration_additional_generations = t(
        "wizard.validation.integerBetween", { min: 1, max: 32 },
      );
    }
    if (
      explorationTrials === null || !Number.isInteger(explorationTrials)
      || explorationTrials < 2 || explorationTrials > 5000
    ) {
      errors.exploration_additional_trials = t(
        "wizard.validation.integerBetween", { min: 2, max: 5000 },
      );
    }
    if (optimizerUsesModelAccess(form.optimizer_strategy)) {
      if (
        providerTurns === null || !Number.isInteger(providerTurns)
        || providerTurns < 0 || providerTurns > 128
      ) {
        errors.exploration_additional_provider_turns = t(
          "wizard.validation.integerBetween", { min: 0, max: 128 },
        );
      } else if (generations !== null && providerTurns > generations * 4) {
        errors.exploration_additional_provider_turns = t(
          "wizard.validation.explorationProviderCap", { count: generations * 4 },
        );
      }
    }
    if (
      timeMinutes === null || !Number.isInteger(timeMinutes)
      || timeMinutes < 1 || timeMinutes > 1440
    ) {
      errors.exploration_additional_time_minutes = t(
        "wizard.validation.integerBetween", { min: 1, max: 1440 },
      );
    }
  }
  if (form.target_rmse.trim() !== "") {
    const value = parseNumber(form.target_rmse);
    if (value === null || value < 0 || value > 100) errors.target_rmse = t("wizard.validation.between", { min: 0, max: 100 });
  }
  if (form.target_max_error.trim() !== "") {
    const value = parseNumber(form.target_max_error);
    if (value === null || value < 0 || value > 100) errors.target_max_error = t("wizard.validation.between", { min: 0, max: 100 });
  }
  const passRate = parseNumber(form.min_pass_rate);
  if (passRate === null || passRate < 0 || passRate > 1) errors.min_pass_rate = t("wizard.validation.between", { min: 0, max: 1 });
  if (optimizerUsesModelAccess(form.optimizer_strategy)) {
    if (form.llm_access_mode === "byok") {
      if (form.llm_api_key.trim() === "") {
        errors.llm_api_key = t("wizard.validation.apiKeyRequired");
      } else if (form.llm_api_key.length > 512) {
        errors.llm_api_key = t("wizard.validation.apiKeyMax");
      }
      if (form.llm_provider !== "openai" && form.llm_model.trim() === "") {
        errors.llm_model = t("wizard.validation.modelRequired");
      } else if (form.llm_model.length > 128) {
        errors.llm_model = t("wizard.validation.modelMax");
      }
      if (form.llm_provider !== "openai" && form.llm_base_url.trim() === "") {
        errors.llm_base_url = t("wizard.validation.baseUrlRequired");
      } else if (
        form.llm_base_url.trim() !== "" &&
        !isValidLlmBaseUrl(form.llm_base_url.trim())
      ) {
        errors.llm_base_url = t("wizard.validation.baseUrlInvalid");
      } else if (form.llm_base_url.length > 2048) {
        errors.llm_base_url = t("wizard.validation.baseUrlMax");
      }
    }
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
    cvar_alpha: form.robust_aggregation === "cvar" ? Number(form.cvar_alpha) : 0.2,
    percentile: form.robust_aggregation === "percentile" ? Number(form.percentile) : 95,
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
      ...(form.nominal_search_enabled
        ? [{ id: "nominal-search", scenario_type: "nominal" as const, seeds: searchSeeds, weight: 1, enabled: true, holdout: false, config: commonConfig }]
        : []),
      ...(form.wind_search_enabled
        ? [{ id: "wind-search", scenario_type: "wind_perturbed" as const, seeds: searchSeeds, weight: 1.2, enabled: true, holdout: false, config: commonConfig }]
        : []),
      ...(form.noise_search_enabled
        ? [{ id: "noise-search", scenario_type: "noise_perturbed" as const, seeds: searchSeeds, weight: 1, enabled: true, holdout: false, config: commonConfig }]
        : []),
      ...(form.nominal_holdout_enabled
        ? [{ id: "nominal-holdout", scenario_type: "nominal" as const, seeds: holdoutSeeds, weight: 1, enabled: true, holdout: true, config: commonConfig }]
        : []),
      ...(form.combined_holdout_enabled
        ? [{ id: "combined-holdout", scenario_type: "combined_perturbed" as const, seeds: holdoutSeeds, weight: 1.5, enabled: true, holdout: true, config: commonConfig }]
        : []),
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
    if (parameter.legacy_key && selections[parameter.name]?.selected) {
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
  platformGrant: string | null = null,
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
      choices: definition?.choices?.length
        ? definition.choices.map((choice) => choice.value)
        : null,
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
      headless: form.simulator_headless,
      simulation_speed_factor: Number(form.simulation_speed_factor),
      instance_id: Number(form.instance_id),
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
    completion_policy: "first_qualified_stop",
  };
  if (form.continue_exploration_after_qualified) {
    request.continue_exploration_after_qualified = true;
    request.exploration_budget = {
      additional_generation_cap: Number(form.exploration_additional_generations),
      additional_trial_cap: Number(form.exploration_additional_trials),
      additional_provider_turn_cap: optimizerUsesModelAccess(form.optimizer_strategy)
        ? Number(form.exploration_additional_provider_turns)
        : 0,
      additional_time_budget_seconds:
        Number(form.exploration_additional_time_minutes) * 60,
    };
  }
  if (optimizerUsesModelAccess(form.optimizer_strategy)) {
    request.llm = form.llm_access_mode === "platform"
      ? {
          access_mode: "platform",
          provider: "dronedream",
          platform_grant: platformGrant,
          api_key: null,
          model: null,
          base_url: null,
        }
      : {
          access_mode: "byok",
          provider: form.llm_provider,
          api_key: form.llm_api_key.trim(),
          platform_grant: null,
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
  delete legacy.completion_policy;
  delete legacy.provider_turn_cap;
  delete legacy.continue_exploration_after_qualified;
  delete legacy.exploration_budget;
  delete legacy.llm;
  if (llm) {
    if (llm.access_mode === "platform" || !llm.api_key) return legacy;
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
  // An old backend cannot enforce an immutable first-qualified receipt or a
  // separately bounded continuation child. Never silently erase that choice.
  if (request.continue_exploration_after_qualified) return false;
  if (request.llm && request.llm.provider !== "openai") return false;
  const evidence = `${error.message} ${JSON.stringify(error.details ?? "")}`.toLowerCase();
  const advancedFields = [
    "vehicle_profile",
    "parameter_space",
    "objective_config",
    "scenario_suite",
    "max_total_trials",
    "llm",
    "completion_policy",
    "provider_turn_cap",
    "continue_exploration_after_qualified",
    "exploration_budget",
  ];
  const rejectionSignal =
    /\b(extra (fields?|inputs?)|unexpected (fields?|arguments?|properties?)|unknown (fields?|properties?)|unrecognized (fields?|properties?)|unsupported (fields?|properties?)|inputs? (are|is) not permitted)\b/u.test(
      evidence,
    );
  const explicitlyRejectsAdvancedFields =
    /\b(extra|unexpected|unknown|unrecognized|unsupported) advanced fields?\b/u.test(evidence);
  return explicitlyRejectsAdvancedFields || (
    rejectionSignal && advancedFields.some((field) => evidence.includes(field))
  );
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
  const [searchParams] = useSearchParams();
  const { t } = useI18n();
  const auth = useOptionalAuth();
  const ownerId = auth?.account?.id ?? "local";
  const editionTheme = useEditionTheme();
  const workspaceEdition = editionTheme.id;
  const { settings: modelAccess } = useModelAccess();
  const initialWorkspaceId = useRef((() => {
    const requested = searchParams.get("experiment");
    if (!requested || !/^[a-zA-Z0-9_-]{8,128}$/u.test(requested)) {
      return null;
    }
    return listExperimentWorkspaces(ownerId, workspaceEdition).some(
      (workspace) => workspace.id === requested && !workspace.archived,
    )
      ? requested
      : null;
  })()).current;
  const [workspaceId, setWorkspaceId] = useState<string | null>(
    initialWorkspaceId,
  );
  const initialDraft = useRef(
    initialWorkspaceId
      ? loadExperimentDraft(EXPERIMENT_DRAFT_SCHEMA, initialWorkspaceId)
      : null,
  ).current;
  const initialTemplate = useRef(
    initialWorkspaceId
      ? null
      : findStarterExperienceTemplate(searchParams.get("scenario")),
  ).current;
  const initialBaseForm = useRef<FormState>(
    initialDraft?.form
      ?? (initialTemplate
        ? applyStarterExperienceTemplate(DEFAULTS, initialTemplate)
        : DEFAULTS),
  ).current;
  const [form, setForm] = useState<FormState>(() => ({
    ...initialBaseForm,
    llm_provider: modelAccess.provider,
    llm_access_mode: modelAccess.accessMode,
    llm_api_key: modelAccess.apiKey,
    llm_model: modelAccess.model,
    llm_base_url: modelAccess.baseUrl,
  }));
  const [catalog, setCatalog] = useState<ParameterCatalogResponse>(BUILTIN_PARAMETER_CATALOG);
  const [selections, setSelections] = useState<ParameterSelectionMap>(() =>
    mergeSelections(
      createParameterSelections(BUILTIN_PARAMETER_CATALOG.parameters, initialBaseForm.tuning_mode),
      initialDraft?.selections,
    ),
  );
  const manualEditOriginForm = useRef<FormState>(
    initialDraft?.conversation ? initialDraft.form : initialBaseForm,
  ).current;
  const manualEditOriginSelections = useRef<ParameterSelectionMap>(
    initialDraft?.conversation
      ? initialDraft.selections
      : createParameterSelections(
        BUILTIN_PARAMETER_CATALOG.parameters,
        initialBaseForm.tuning_mode,
      ),
  ).current;
  const conversationRef = useRef(initialDraft?.conversation ?? null);
  const [step, setStep] = useState(() => Math.min(4, Math.max(0, initialDraft?.active_step ?? 0)));
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(() => {
    return new Set(initialDraft?.completed_steps ?? []);
  });
  const [nameConfirmed, setNameConfirmed] = useState(
    () => Boolean(initialDraft?.form.display_name.trim()),
  );
  const [experimentName, setExperimentName] = useState(
    () => initialDraft?.form.display_name ?? DEFAULTS.display_name,
  );
  const [experimentNameError, setExperimentNameError] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showAdvancedScenario, setShowAdvancedScenario] = useState(false);
  const [showTrackEditor, setShowTrackEditor] = useState(false);
  const [showTrackJson, setShowTrackJson] = useState(false);
  const [showParameterReview, setShowParameterReview] = useState(false);
  const [lastAppliedTemplateKey, setLastAppliedTemplateKey] = useState<string | null>(
    initialTemplate?.key ?? null,
  );
  const [savedDefaultsState, setSavedDefaultsState] =
    useState<"idle" | "loading" | "applied" | "empty" | "error">("idle");
  const [capabilities, setCapabilities] = useState<BackendCapabilitiesResponse | null>(null);
  const [capabilitiesUnavailable, setCapabilitiesUnavailable] = useState(false);
  const submittingRef = useRef(false);
  const advancedScenarioTriggerRef = useRef<HTMLButtonElement>(null);
  const trackEditorTriggerRef = useRef<HTMLButtonElement>(null);
  const trackJsonTriggerRef = useRef<HTMLButtonElement>(null);
  const parameterReviewTriggerRef = useRef<HTMLButtonElement>(null);
  const reviewParameterPreviewRef = useRef<HTMLDivElement>(null);
  const reviewParameterPreviewIndexRef = useRef(0);
  const reviewParameterWheelDeltaRef = useRef(0);
  const reviewParameterWheelDirectionRef = useRef(0);

  const selectedCount = Object.values(selections).filter(
    (selection) => selection.selected,
  ).length;
  const trialPlan = calculateTrialPlan(form, selectedCount);
  const estimatedTrials = trialPlan.scheduledTrials;
  const localPreviewPoints = referenceTrack(form) ?? [];

  useEffect(() => {
    if (!workspaceId || !initialDraft?.form.display_name.trim()) return;
      registerExperimentWorkspace({
        id: workspaceId,
        ownerId,
        edition: workspaceEdition,
        name: initialDraft.form.display_name,
        source: initialDraft.conversation ? "assistant" : "manual",
        activeStep: initialDraft.active_step,
        completedSteps: initialDraft.completed_steps,
      });
  }, [initialDraft, ownerId, workspaceEdition, workspaceId]);

  useEffect(() => {
    setForm((current) => {
      if (
        current.llm_provider === modelAccess.provider
        && current.llm_access_mode === modelAccess.accessMode
        && current.llm_api_key === modelAccess.apiKey
        && current.llm_model === modelAccess.model
        && current.llm_base_url === modelAccess.baseUrl
      ) {
        return current;
      }
      return {
        ...current,
        llm_access_mode: modelAccess.accessMode,
        llm_provider: modelAccess.provider,
        llm_api_key: modelAccess.apiKey,
        llm_model: modelAccess.model,
        llm_base_url: modelAccess.baseUrl,
      };
    });
  }, [modelAccess]);

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
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [form.px4_version, form.tuning_mode]);

  useEffect(() => {
    const capabilityApiOverride = import.meta.env.VITE_CAPABILITIES_API;
    if (
      capabilityApiOverride === "false"
      || (import.meta.env.MODE === "test" && capabilityApiOverride !== "true")
    ) {
      return undefined;
    }
    let active = true;
    apiClient
      .getCapabilities()
      .then((response) => {
        if (!active) return;
        setCapabilities(response);
        setCapabilitiesUnavailable(false);
      })
      .catch(() => {
        if (!active) return;
        // Compatibility with an older backend: keep the existing advisory
        // prompts and let the create endpoint remain authoritative.
        setCapabilities(null);
        setCapabilitiesUnavailable(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!nameConfirmed) return undefined;
    const timer = window.setTimeout(() => {
      conversationRef.current = recordManualDraftEdits(
        conversationRef.current,
        manualEditOriginForm,
        form,
        manualEditOriginSelections,
        selections,
      );
      saveExperimentDraft({
        active_step: step,
        completed_steps: [...completedSteps].sort((left, right) => left - right),
        form: { ...form, llm_api_key: "" },
        selections,
        conversation: conversationRef.current,
      }, workspaceId);
      if (workspaceId) {
        updateExperimentWorkspace(ownerId, workspaceId, {
          name: form.display_name,
          activeStep: step,
          completedSteps: [...completedSteps],
        }, workspaceEdition);
      }
    }, 700);
    return () => window.clearTimeout(timer);
  }, [
    completedSteps,
    form,
    manualEditOriginForm,
    manualEditOriginSelections,
    nameConfirmed,
    ownerId,
    workspaceEdition,
    selections,
    step,
    workspaceId,
  ]);

  useEffect(() => {
    if (
      nameConfirmed &&
      !showAdvancedScenario &&
      !showTrackEditor &&
      !showTrackJson &&
      !showParameterReview
    ) {
      return undefined;
    }
    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!nameConfirmed) {
          navigate(-1);
          return;
        }
        let returnFocus: HTMLButtonElement | null = null;
        if (showParameterReview) {
          setShowParameterReview(false);
          returnFocus = parameterReviewTriggerRef.current;
        } else if (showTrackJson) {
          setShowTrackJson(false);
          returnFocus = trackJsonTriggerRef.current;
        } else if (showTrackEditor) {
          setShowTrackEditor(false);
          returnFocus = trackEditorTriggerRef.current;
        } else {
          setShowAdvancedScenario(false);
          returnFocus = advancedScenarioTriggerRef.current;
        }
        window.requestAnimationFrame(() => returnFocus?.focus());
        return;
      }
      if (event.key !== "Tab") return;
      const dialogs = [...document.querySelectorAll<HTMLElement>('.wizard-modal[role="dialog"]')];
      const dialog = dialogs.at(-1);
      if (!dialog) return;
      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), '
          + 'textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => !element.hasAttribute("hidden"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleDialogKeyDown);
    return () => document.removeEventListener("keydown", handleDialogKeyDown);
  }, [
    nameConfirmed,
    navigate,
    showAdvancedScenario,
    showParameterReview,
    showTrackEditor,
    showTrackJson,
  ]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((previous) => ({ ...previous, [key]: value }));
    setErrors((previous) => {
      if (!previous[key]) return previous;
      const next = { ...previous };
      delete next[key];
      return next;
    });
  }

  function applyStarterTemplate(template: StarterExperienceTemplate): void {
    setForm((previous) => applyStarterExperienceTemplate(previous, template));
    applyModePreset(template.patch.tuning_mode);
    setLastAppliedTemplateKey(template.key);
    setErrors((previous) => {
      const next = { ...previous };
      for (const key of Object.keys(template.patch)) {
        delete next[key];
      }
      return next;
    });
  }

  function applySavedDefaults(preferences: UserExperiencePreferences): void {
    const template = STARTER_EXPERIENCE_TEMPLATES.find(
      (candidate) => candidate.key === preferences.default_template_key,
    );
    setForm((previous) => {
      const templated = template
        ? applyStarterExperienceTemplate(previous, template)
        : previous;
      const trackType = preferences.default_track_type ?? templated.track_type;
      return {
        ...templated,
        track_type: trackType,
        start_x: trackType === "hover" ? "0" : templated.start_x,
        start_y: trackType === "hover" ? "0" : templated.start_y,
        altitude_m: preferences.default_altitude_m === null
          ? templated.altitude_m
          : String(preferences.default_altitude_m),
      };
    });
    if (template) {
      applyModePreset(template.patch.tuning_mode);
      setLastAppliedTemplateKey(template.key);
    }
    setErrors((previous) => {
      const next = { ...previous };
      for (const key of ["track_type", "start_x", "start_y", "altitude_m"]) {
        delete next[key];
      }
      if (template) {
        for (const key of Object.keys(template.patch)) delete next[key];
      }
      return next;
    });
  }

  async function loadSavedDefaults(): Promise<void> {
    setSavedDefaultsState("loading");
    try {
      const preferences = await apiClient.getUserExperiencePreferences();
      const hasDefaults = (
        preferences.default_template_key !== null ||
        preferences.default_track_type !== null ||
        preferences.default_altitude_m !== null
      );
      if (!preferences.saved || !hasDefaults) {
        setSavedDefaultsState("empty");
        return;
      }
      applySavedDefaults(preferences);
      setSavedDefaultsState("applied");
    } catch {
      setSavedDefaultsState("error");
    }
  }

  function handleTextChange(key: keyof FormState) {
    return (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      update(key, event.target.value as FormState[typeof key]);
  }

  function applyObjectiveProfile(profile: ObjectiveProfile): void {
    setForm((previous) => ({
      ...previous,
      objective_profile: profile,
      ...(profile === "custom" ? {} : OBJECTIVE_WEIGHT_PRESETS[profile]),
    }));
    setErrors((previous) => {
      const next = { ...previous };
      delete next.objective_profile;
      delete next.objective_weights;
      delete next.robust_aggregation;
      delete next.cvar_alpha;
      delete next.percentile;
      return next;
    });
  }

  function handleObjectiveWeightChange(
    key:
      | "objective_weight_tracking"
      | "objective_weight_speed"
      | "objective_weight_smoothness"
      | "objective_weight_robustness",
  ) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const value = event.target.value;
      setForm((previous) => ({
        ...previous,
        [key]: value,
        objective_profile: "custom",
      }));
      setErrors((previous) => {
        if (!previous.objective_weights) return previous;
        const next = { ...previous };
        delete next.objective_weights;
        return next;
      });
    };
  }

  function applyScenarioPreset(preset: ScenarioPreset): void {
    const cleanEnvironment: Partial<FormState> = {
      wind_north: "0",
      wind_east: "0",
      wind_south: "0",
      wind_west: "0",
      sensor_noise_level: "medium",
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
      nominal_search_enabled: true,
      wind_search_enabled: false,
      noise_search_enabled: false,
      nominal_holdout_enabled: true,
      combined_holdout_enabled: false,
    };
    const presetValues: Record<ScenarioPreset, Partial<FormState>> = {
      nominal: {
        ...cleanEnvironment,
      },
      wind: {
        ...cleanEnvironment,
        wind_search_enabled: true,
        wind_north: "4",
        wind_east: "2",
        sensor_noise_level: "medium",
        advanced_enabled: true,
        gust_enabled: true,
        gust_magnitude_mps: "6",
        gust_direction_deg: "26.565051",
        gust_period_s: "12",
      },
      sensor: {
        ...cleanEnvironment,
        noise_search_enabled: true,
        sensor_noise_level: "high",
        advanced_enabled: true,
        gps_noise_m: "0",
        baro_noise_m: "0.5",
        imu_noise_scale: "1.4",
        dropout_rate: "0.05",
      },
      stress: {
        ...cleanEnvironment,
        wind_search_enabled: true,
        noise_search_enabled: true,
        nominal_holdout_enabled: false,
        combined_holdout_enabled: true,
        wind_north: "6",
        wind_east: "3",
        sensor_noise_level: "high",
        advanced_enabled: true,
        gust_enabled: true,
        gust_magnitude_mps: "10",
        gust_direction_deg: "26.565051",
        gust_period_s: "8",
        gps_noise_m: "0",
        baro_noise_m: "0.8",
        imu_noise_scale: "1.8",
        dropout_rate: "0.1",
        battery_initial_percent: "80",
        battery_voltage_sag: true,
        mass_payload_kg: "0.5",
      },
    };
    setForm((previous) => ({
      ...previous,
      ...presetValues[preset],
      scenario_preset: preset,
    }));
    setErrors((previous) => Object.fromEntries(
      Object.entries(previous).filter(([key]) => errorStep(key, catalog) !== 2),
    ));
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
    setForm((previous) => {
      const profile = mode === "basic" && previous.objective_profile === "custom"
        ? "robust"
        : previous.objective_profile;
      return {
        ...previous,
        tuning_mode: mode,
        objective_profile: profile,
        ...(mode === "basic" && profile !== "custom" ? OBJECTIVE_WEIGHT_PRESETS[profile] : {}),
      };
    });
    applyModePreset(mode);
  }

  function persistDraft(
    activeStep: number,
    nextForm: FormState = form,
    nextCompletedSteps: Set<number> = completedSteps,
    targetWorkspaceId: string | null = workspaceId,
  ): void {
    conversationRef.current = recordManualDraftEdits(
      conversationRef.current,
      manualEditOriginForm,
      nextForm,
      manualEditOriginSelections,
      selections,
    );
    saveExperimentDraft({
      active_step: activeStep,
      completed_steps: [...nextCompletedSteps].sort((left, right) => left - right),
      form: { ...nextForm, llm_api_key: "" },
      selections,
      conversation: conversationRef.current,
    }, targetWorkspaceId);
    if (targetWorkspaceId) {
      registerExperimentWorkspace({
        id: targetWorkspaceId,
        ownerId,
        edition: workspaceEdition,
        name: nextForm.display_name,
        source: conversationRef.current ? "assistant" : "manual",
        activeStep,
        completedSteps: [...nextCompletedSteps],
      });
    }
  }

  function confirmExperimentName(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmedName = experimentName.trim();
    if (trimmedName === "") {
      setExperimentNameError(t("wizard.validation.required"));
      return;
    }
    if (trimmedName.length > 255) {
      setExperimentNameError(t("wizard.validation.nameMax"));
      return;
    }
    if (
      !isExperimentWorkspaceNameAvailable(
        ownerId,
        trimmedName,
        workspaceEdition,
        workspaceId,
      )
    ) {
      setExperimentNameError(t("wizard.validation.nameUnique"));
      return;
    }
    const nextForm = { ...form, display_name: trimmedName };
    const targetWorkspaceId = workspaceId ?? createExperimentWorkspaceId();
    setForm(nextForm);
    setExperimentName(trimmedName);
    setExperimentNameError(null);
    setNameConfirmed(true);
    setWorkspaceId(targetWorkspaceId);
    persistDraft(step, nextForm, completedSteps, targetWorkspaceId);
  }

  function errorsForStep(targetStep: number): FieldErrors {
    const all = validate(form, selections, catalog, capabilities, t);
    return Object.fromEntries(
      Object.entries(all).filter(([key]) => errorStep(key, catalog) === targetStep),
    );
  }

  function nextStep(): void {
    const nextErrors = errorsForStep(step);
    const nextErrorKeys = Object.keys(nextErrors);
    if (nextErrorKeys.length > 0) {
      const firstErrorKey = nextErrorKeys[0];
      setErrors((previous) => ({ ...previous, ...nextErrors }));
      if (step === 2 && opensAdvancedScenarioDialog(firstErrorKey)) setShowAdvancedScenario(true);
      if (step === 0 && opensTrackDialog(firstErrorKey)) setShowTrackEditor(true);
      if (step === 3 && opensModelSettings(firstErrorKey)) openAppSettings();
      focusErrorField(firstErrorKey, catalog);
      return;
    }
    setErrors((previous) => Object.fromEntries(
      Object.entries(previous).filter(([key]) => errorStep(key, catalog) !== step),
    ));
    const nextStep = Math.min(4, step + 1);
    const nextCompletedSteps = new Set(completedSteps).add(step);
    setCompletedSteps(nextCompletedSteps);
    persistDraft(nextStep, form, nextCompletedSteps);
    setStep(nextStep);
  }

  function previousStep(): void {
    const previousStepIndex = Math.max(0, step - 1);
    persistDraft(previousStepIndex);
    setStep(previousStepIndex);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (step !== 4 || submittingRef.current) return;
    setSubmitError(null);
    const nextErrors = validate(form, selections, catalog, capabilities, t);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      const firstStep = Math.min(...Object.keys(nextErrors).map((key) => errorStep(key, catalog)));
      const firstKey = Object.keys(nextErrors).find((key) => errorStep(key, catalog) === firstStep) ?? Object.keys(nextErrors)[0];
      setStep(firstStep);
      if (firstStep === 2 && opensAdvancedScenarioDialog(firstKey)) setShowAdvancedScenario(true);
      if (firstStep === 0 && opensTrackDialog(firstKey)) setShowTrackEditor(true);
      if (firstStep === 3 && opensModelSettings(firstKey)) openAppSettings();
      focusErrorField(firstKey, catalog);
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    let usedLegacyApi = false;
    try {
      if (publicDemoConsole) {
        persistDraft(4);
        if (workspaceId) {
          updateExperimentWorkspace(ownerId, workspaceId, {
            status: "draft",
            activeStep: 4,
            completedSteps: [0, 1, 2, 3, 4],
          }, workspaceEdition);
        }
        navigate("/dashboard", { replace: false });
        return;
      }
      const platformGrant = (
        optimizerUsesModelAccess(form.optimizer_strategy)
        && form.llm_access_mode === "platform"
      )
        ? (await issueManagedModelGrant(
            "job",
            workspaceId ?? `draft:${ownerId}`,
          )).grant
        : null;
      const advancedRequest = formToRequest(
        form,
        selections,
        catalog,
        platformGrant,
      );
      let created;
      try {
        created = await apiClient.createJob(advancedRequest);
      } catch (error) {
        if (!isLegacyContractRejection(error, advancedRequest)) throw error;
        if (advancedRequest.llm?.access_mode === "platform") {
          throw new ApiClientError(
            "BACKEND_UPGRADE_REQUIRED",
            t("wizard.experimentalBackendRequired"),
            null,
            422,
          );
        }
        if (EXPERIMENTAL_OPTIMIZER_STRATEGIES.some(
          (strategy) => strategy === advancedRequest.optimizer_strategy,
        )) {
          throw new ApiClientError(
            "BACKEND_UPGRADE_REQUIRED",
            t("wizard.experimentalBackendRequired"),
            null,
            422,
          );
        }
        usedLegacyApi = true;
        created = await apiClient.createJob(legacyRequest(advancedRequest));
      }
      persistStudyForJob(
        created.id,
        buildStudyMetadata(form, selections, estimatedTrials, usedLegacyApi),
      );
      if (workspaceId) {
        updateExperimentWorkspace(ownerId, workspaceId, {
          status: "created",
          jobId: created.id,
          activeStep: 4,
          completedSteps: [0, 1, 2, 3, 4],
        }, workspaceEdition);
      }
      clearExperimentDraft(workspaceId);
      void recordProductEvent("job_created", {
        source: lastAppliedTemplateKey ? "fixed_scenario" : "manual_or_assistant",
        template_key: lastAppliedTemplateKey,
        used_legacy_api: usedLegacyApi,
      });
      navigate(`/jobs/${created.id}`, { replace: false });
    } catch (error) {
      setSubmitError(
        error instanceof ApiClientError
          ? `${t("wizard.validation.submitFailed")} (${error.code})`
          : t("wizard.validation.submitFailed"),
      );
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }

  const customTrack = parseReferenceTrackInput(form.reference_track_json, t).points ?? [];
  const selectedParameterRows = selectedParameters(selections);
  useEffect(() => {
    reviewParameterPreviewIndexRef.current = 0;
    reviewParameterWheelDeltaRef.current = 0;
    reviewParameterWheelDirectionRef.current = 0;
    if (reviewParameterPreviewRef.current) {
      reviewParameterPreviewRef.current.scrollLeft = 0;
    }
  }, [selectedParameterRows.length]);

  const handleReviewParameterWheel = (
    event: ReactWheelEvent<HTMLDivElement>,
  ) => {
    if (selectedParameterRows.length < 7) return;
    const preview = reviewParameterPreviewRef.current;
    const items = preview?.querySelectorAll<HTMLElement>("code");
    if (!preview || !items || items.length < 7) return;

    const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX)
      ? event.deltaY
      : event.deltaX;
    if (delta === 0) return;
    event.preventDefault();

    const direction = delta > 0 ? 1 : -1;
    if (
      reviewParameterWheelDirectionRef.current !== 0
      && reviewParameterWheelDirectionRef.current !== direction
    ) {
      reviewParameterWheelDeltaRef.current = 0;
    }
    reviewParameterWheelDirectionRef.current = direction;
    reviewParameterWheelDeltaRef.current += Math.abs(delta);
    const threshold = event.deltaMode === WheelEvent.DOM_DELTA_PIXEL ? 40 : 1;
    if (reviewParameterWheelDeltaRef.current < threshold) return;

    // Consume one deliberate wheel step per threshold crossing. A mouse wheel
    // notch therefore reveals exactly one parameter, while small touchpad
    // deltas are accumulated instead of causing a rapid multi-card jump.
    reviewParameterWheelDeltaRef.current = 0;
    const nextIndex = (
      reviewParameterPreviewIndexRef.current + direction + items.length
    ) % items.length;
    reviewParameterPreviewIndexRef.current = nextIndex;
    const firstOffset = items[0]?.offsetLeft ?? 0;
    const nextOffset = items[nextIndex]?.offsetLeft ?? firstOffset;
    preview.scrollTo({
      left: Math.max(0, nextOffset - firstOffset),
      behavior: "smooth",
    });
  };
  const realCliCapability = capabilities?.simulators.items.real_cli;
  const modelOptimizerCapability = capabilities?.optimizers.items[form.optimizer_strategy];
  const preflightErrors = validate(form, selections, catalog, capabilities, t);
  const preflightSteps = [...new Set(
    Object.keys(preflightErrors).map((key) => errorStep(key, catalog)),
  )].sort((left, right) => left - right);
  const currentStepHasErrors = Object.keys(preflightErrors).some(
    (key) => errorStep(key, catalog) === step,
  );

  if (!nameConfirmed) {
    return (
      <section className="experiment-name-entry">
        <div className="wizard-modal-backdrop" role="presentation">
          <form
            className="wizard-modal wizard-name-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="experiment-name-dialog-title"
            onSubmit={confirmExperimentName}
            noValidate
          >
            <header className="wizard-modal-header">
              <h3 id="experiment-name-dialog-title">{t("wizard.title")}</h3>
            </header>
            <Field
              label={t("wizard.field.experimentName")}
              htmlFor="experiment_name_prompt"
              required
              error={experimentNameError ?? undefined}
            >
              <input
                id="experiment_name_prompt"
                autoFocus
                value={experimentName}
                placeholder={t("wizard.field.experimentNamePlaceholder")}
                onChange={(event) => {
                  setExperimentName(event.target.value);
                  if (experimentNameError) setExperimentNameError(null);
                }}
              />
            </Field>
            <div className="wizard-name-actions">
              <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)}>
                {t("wizard.nameDialog.cancel")}
              </button>
              <button type="submit" className="btn btn-primary">
                {t("wizard.nameDialog.continue")}
              </button>
            </div>
          </form>
        </div>
      </section>
    );
  }

  return (
    <section className="stack-md experiment-wizard-page">
      <header className="page-header experiment-header">
        <div>
          <div className="eyebrow">{t("wizard.eyebrow")}</div>
          <h1>{t("wizard.title")}</h1>
        </div>
      </header>

      <nav aria-label={t("wizard.aria.steps")}>
        <ol className="wizard-stepper">
          {WIZARD_STEPS.map((wizardStep, index) => {
            const isCurrent = step === index;
            const isComplete = completedSteps.has(index) && !isCurrent;
            return (
              <li
                key={wizardStep.key}
                className={`${isCurrent ? "wizard-step-active" : ""}${isComplete ? " wizard-step-complete" : ""}`}
                aria-current={isCurrent ? "step" : undefined}
              >
                <span className="wizard-step-number">{isComplete ? "✓" : index + 1}</span>
                <span className="wizard-step-label">{t(wizardStep.key)}</span>
              </li>
            );
          })}
        </ol>
      </nav>
      <p className="sr-only" aria-live="polite">{t(WIZARD_STEPS[step].key)}</p>

      <form onSubmit={handleSubmit} noValidate className="experiment-form">
        {submitError ? <Alert tone="danger" title={t("wizard.submissionFailed")}>{submitError}</Alert> : null}

        {step === 0 ? (
          <div className="wizard-panel">
          <SectionCard title={t("wizard.section.flightSetup")}>
            <div className="wizard-flight-setup">
            <div className="form-field wizard-mode-field wizard-full-row">
              <label className="wizard-field-label" htmlFor="tuning_mode">{t("wizard.aria.modeSelector")}</label>
              <select
                id="tuning_mode"
                value={form.tuning_mode}
                onChange={(event) => changeMode(event.target.value as TuningMode)}
              >
                {(["basic", "advanced", "expert"] as const).map((mode) => (
                  <option value={mode} key={mode}>
                    {t(`wizard.mode.${mode}` as TranslationKey)}
                  </option>
                ))}
              </select>
            </div>
            <section
              className="stack-sm wizard-subsection starter-experience-section"
              aria-labelledby="starter-experience-title"
            >
              <div className="starter-experience-heading">
                <div>
                  <h3 id="starter-experience-title">{t("wizard.starter.title")}</h3>
                  <p>{t("wizard.starter.description")}</p>
                </div>
                <div className="starter-experience-heading-actions">
                  <span className="starter-experience-version">
                    {t("wizard.starter.catalogVersion", {
                      version: STARTER_EXPERIENCE_CATALOG_VERSION,
                    })}
                  </span>
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    disabled={savedDefaultsState === "loading"}
                    onClick={() => void loadSavedDefaults()}
                  >
                    {savedDefaultsState === "loading"
                      ? t("wizard.starter.loadingSaved")
                      : t("wizard.starter.loadSaved")}
                  </button>
                </div>
              </div>
              <div className="starter-experience-layout">
                <div className="starter-experience-grid">
                  {STARTER_EXPERIENCE_TEMPLATES.map((template) => {
                    const copy = STARTER_EXPERIENCE_I18N[template.id];
                    const title = t(copy.title);
                    return (
                      <article className="starter-experience-card" key={template.key}>
                        <div>
                          <strong>{title}</strong>
                          <span>v{template.version}</span>
                        </div>
                        <p>{t(copy.description)}</p>
                        <button
                          type="button"
                          className="btn btn-ghost btn-small"
                          aria-label={`${t("wizard.starter.apply")}: ${title}`}
                          onClick={() => applyStarterTemplate(template)}
                        >
                          {t("wizard.starter.apply")}
                        </button>
                      </article>
                    );
                  })}
                </div>
                <ExperienceTrackPreview
                  trackType={form.track_type}
                  points={localPreviewPoints}
                  altitudeM={Number(form.altitude_m)}
                  title={t("wizard.preview.title")}
                  hoverLabel={t("wizard.preview.hover")}
                  routeLabel={t("wizard.preview.route")}
                  pointCountLabel={t("wizard.preview.pointCount", {
                    count: localPreviewPoints.length,
                  })}
                  localOnlyLabel={t("wizard.preview.localOnly")}
                />
              </div>
              {lastAppliedTemplateKey ? (
                <p className="starter-experience-status" role="status">
                  {t("wizard.starter.applied", { key: lastAppliedTemplateKey })}
                </p>
              ) : null}
              {savedDefaultsState === "applied" ? (
                <p className="starter-experience-status" role="status">
                  {t("wizard.starter.savedApplied")}
                </p>
              ) : null}
              {savedDefaultsState === "empty" ? (
                <p className="starter-experience-note" role="status">
                  {t("wizard.starter.noSaved")}
                </p>
              ) : null}
              {savedDefaultsState === "error" ? (
                <p className="starter-experience-note" role="alert">
                  {t("wizard.starter.loadFailed")}
                </p>
              ) : null}
            </section>
            <section className="stack-sm wizard-subsection" aria-labelledby="flight-setup-vehicle-title">
              <h3 id="flight-setup-vehicle-title">{t("wizard.section.vehicle")}</h3>
              <div className="form-grid">
              <Field label={t("wizard.field.px4Version")} required error={errors.px4_version} htmlFor="px4_version" hint={selectedHint(PX4_VERSION_HINT_KEYS, form.px4_version, t)}>
                <select id="px4_version" value={form.px4_version} onChange={(event) => update("px4_version", event.target.value)}>
                  <option value="v1.16">v1.16</option>
                  <option value="v1.17">v1.17</option>
                  <option value="main">main</option>
                </select>
              </Field>
              {form.tuning_mode === "expert" || form.firmware_commit.trim() !== "" ? (
                <Field label={t("wizard.field.firmwareCommit")} htmlFor="firmware_commit" error={errors.firmware_commit} hint={t("wizard.field.firmwareCommitHint")}>
                  <input id="firmware_commit" value={form.firmware_commit} onChange={handleTextChange("firmware_commit")} />
                </Field>
              ) : null}
              <Field label={t("wizard.field.airframe")} required error={errors.airframe} htmlFor="airframe" hint={selectedHint(AIRFRAME_HINT_KEYS, form.airframe, t)}>
                <select id="airframe" value={form.airframe} onChange={(event) => update("airframe", event.target.value)}>
                  <option value="x500">{t("wizard.option.airframeX500")}</option>
                  <option value="quad_x">{t("wizard.option.airframeQuadX")}</option>
                </select>
              </Field>
              <Field label={t("wizard.field.gazeboModel")} required error={errors.simulator_model} htmlFor="simulator_model" hint={selectedHint(SIMULATOR_MODEL_HINT_KEYS, form.simulator_model, t)}>
                <select id="simulator_model" value={form.simulator_model} onChange={(event) => update("simulator_model", event.target.value)}>
                  <option value="gz_x500">gz_x500</option>
                  <option value="gz_x500_depth">gz_x500_depth</option>
                  <option value="gz_x500_vision">gz_x500_vision</option>
                  <option value="gz_x500_mono_cam">gz_x500_mono_cam</option>
                  <option value="gz_x500_mono_cam_down">gz_x500_mono_cam_down</option>
                  <option value="gz_x500_lidar_down">gz_x500_lidar_down</option>
                  <option value="gz_x500_lidar_front">gz_x500_lidar_front</option>
                  <option value="gz_x500_lidar_2d">gz_x500_lidar_2d</option>
                  <option value="gz_x500_gimbal">gz_x500_gimbal</option>
                </select>
              </Field>
              <Field label={t("wizard.field.gazeboWorld")} required error={errors.simulator_world} htmlFor="simulator_world" hint={selectedHint(SIMULATOR_WORLD_HINT_KEYS, form.simulator_world, t)}>
                <select id="simulator_world" value={form.simulator_world} onChange={(event) => update("simulator_world", event.target.value)}>
                  {Object.keys(SIMULATOR_WORLD_KEYS).map((world) => (
                    <option key={world} value={world}>{simulatorWorldLabel(world, t)}</option>
                  ))}
                </select>
              </Field>
              <Field label={t("wizard.field.headless")} htmlFor="simulator_headless" hint={t(form.simulator_headless ? "wizard.hint.headless.disabled" : "wizard.hint.headless.enabled")}>
                <BooleanSelect
                  id="simulator_headless"
                  value={form.simulator_headless}
                  onChange={(value) => update("simulator_headless", value)}
                  trueLabel={t("wizard.option.disabled")}
                  falseLabel={t("wizard.option.enabled")}
                />
              </Field>
              {form.tuning_mode !== "basic" ? (
                <>
                  <Field label={t("wizard.field.simulationSpeed")} required htmlFor="simulation_speed_factor" error={errors.simulation_speed_factor} hint={t("wizard.field.simulationSpeedHint")}>
                    <input id="simulation_speed_factor" type="number" min="0.1" max="100" step="0.1" placeholder="0.1–100" value={form.simulation_speed_factor} onChange={handleTextChange("simulation_speed_factor")} />
                  </Field>
                  <Field label={t("wizard.field.instanceId")} required htmlFor="instance_id" error={errors.instance_id} hint={t("wizard.instanceIdHint")}>
                    <input id="instance_id" type="number" min="0" max="255" step="1" placeholder="0–255" value={form.instance_id} onChange={handleTextChange("instance_id")} />
                  </Field>
                </>
              ) : null}
              </div>
            </section>

            <section className="stack-sm wizard-subsection" aria-labelledby="flight-setup-objective-title">
              <h3 id="flight-setup-objective-title">{t("wizard.section.objective")}</h3>
            <Field
              label={t("wizard.field.objectiveProfile")}
              htmlFor="objective_profile"
              error={errors.objective_profile}
              hint={t(OBJECTIVE_HINT_KEYS[form.objective_profile])}
            >
              <select
                id="objective_profile"
                value={form.objective_profile}
                onChange={(event) => applyObjectiveProfile(event.target.value as ObjectiveProfile)}
              >
                {OBJECTIVE_PROFILES
                  .filter((profile) => profile !== "custom" || form.tuning_mode !== "basic")
                  .map((profile) => (
                    <option value={profile} key={profile}>
                      {t(`wizard.objective.${profile}` as TranslationKey)}
                    </option>
                  ))}
              </select>
            </Field>
            <div className="form-grid objective-weight-grid">
                  <Field label={t("wizard.field.weightTracking")} htmlFor="objective_weight_tracking" error={errors.objective_weights} hint={t("wizard.hint.weight.tracking")}>
                    <input id="objective_weight_tracking" type="number" min="0" max="100" step="0.05" placeholder="0–100" value={form.objective_weight_tracking} disabled={form.tuning_mode === "basic"} onChange={handleObjectiveWeightChange("objective_weight_tracking")} />
                  </Field>
                  <Field label={t("wizard.field.weightSpeed")} htmlFor="objective_weight_speed" hint={t("wizard.hint.weight.speed")}>
                    <input id="objective_weight_speed" type="number" min="0" max="100" step="0.05" placeholder="0–100" value={form.objective_weight_speed} disabled={form.tuning_mode === "basic"} onChange={handleObjectiveWeightChange("objective_weight_speed")} />
                  </Field>
                  <Field label={t("wizard.field.weightSmoothness")} htmlFor="objective_weight_smoothness" hint={t("wizard.hint.weight.smoothness")}>
                    <input id="objective_weight_smoothness" type="number" min="0" max="100" step="0.05" placeholder="0–100" value={form.objective_weight_smoothness} disabled={form.tuning_mode === "basic"} onChange={handleObjectiveWeightChange("objective_weight_smoothness")} />
                  </Field>
                  <Field label={t("wizard.field.weightRobustness")} htmlFor="objective_weight_robustness" hint={t("wizard.hint.weight.robustness")}>
                    <input id="objective_weight_robustness" type="number" min="0" max="100" step="0.05" placeholder="0–100" value={form.objective_weight_robustness} disabled={form.tuning_mode === "basic"} onChange={handleObjectiveWeightChange("objective_weight_robustness")} />
                  </Field>
                </div>
                <div className="form-grid objective-tail-grid">
                  <Field label={t("wizard.field.robustAggregation")} htmlFor="robust_aggregation" error={errors.robust_aggregation} hint={t(AGGREGATION_HINT_KEYS[form.robust_aggregation])}>
                    <select id="robust_aggregation" value={form.robust_aggregation} disabled={form.tuning_mode !== "expert"} onChange={(event) => update("robust_aggregation", event.target.value as RobustAggregation)}>
                      <option value="mean">{t("wizard.aggregation.mean")}</option>
                      <option value="worst">{t("wizard.aggregation.worst")}</option>
                      <option value="cvar">{t("wizard.aggregation.cvar")}</option>
                      <option value="percentile">{t("wizard.aggregation.percentile")}</option>
                    </select>
                  </Field>
                  {form.robust_aggregation === "percentile" ? (
                    <Field label={t("wizard.field.percentile")} htmlFor="percentile" error={errors.percentile}>
                      <input id="percentile" type="number" min="1" max="100" step="1" placeholder="1–100" value={form.percentile} disabled={form.tuning_mode !== "expert"} onChange={handleTextChange("percentile")} />
                    </Field>
                  ) : (
                    <Field label={t("wizard.field.cvarAlpha")} htmlFor="cvar_alpha" error={errors.cvar_alpha}>
                      <input id="cvar_alpha" type="number" min="0" max="1" step="0.05" placeholder="0–1" value={form.cvar_alpha} disabled={form.tuning_mode !== "expert" || form.robust_aggregation !== "cvar"} onChange={handleTextChange("cvar_alpha")} />
                    </Field>
                  )}
                </div>
            </section>

            <section className="stack-sm wizard-subsection" aria-labelledby="flight-setup-track-title">
              <h3 id="flight-setup-track-title">{t("wizard.section.track")}</h3>
              <div className="form-grid">
                <Field label={t("wizard.field.trackType")} required htmlFor="track_type" error={errors.track_type} hint={t(TRACK_HINT_KEYS[form.track_type])}>
                  <select id="track_type" value={form.track_type} onChange={(event) => {
                    const next = event.target.value as TrackType;
                    update("track_type", next);
                    if (next === "custom" && form.reference_track_json.trim() === "") update("reference_track_json", CUSTOM_REFERENCE_TRACK_EXAMPLE);
                  }}>
                    {TRACK_TYPES.map((track) => {
                      const key = track === "u_turn" ? "wizard.track.uTurn" : `wizard.track.${track}`;
                      return <option key={track} value={track}>{t(key as TranslationKey)}</option>;
                    })}
                  </select>
                </Field>
                {form.track_type === "hover" ? (
                  <p className="form-hint wizard-full-row">{t(TRACK_HINT_KEYS.hover)}</p>
                ) : null}
                {form.track_type === "circle" ? <Field label={t("wizard.field.circleRadius")} htmlFor="circle_radius_m" error={errors.circle_radius_m} hint={t("wizard.hint.circleRadius")}><input id="circle_radius_m" type="number" min="0" max="100" step="0.1" placeholder="0–100" value={form.circle_radius_m} onChange={handleTextChange("circle_radius_m")} /></Field> : null}
                {form.track_type === "u_turn" ? <><Field label={t("wizard.field.uTurnStraight")} htmlFor="u_turn_straight_length_m" error={errors.u_turn_straight_length_m} hint={t("wizard.hint.uTurnStraight")}><input id="u_turn_straight_length_m" type="number" min="0" max="200" step="0.1" placeholder="0–200" value={form.u_turn_straight_length_m} onChange={handleTextChange("u_turn_straight_length_m")} /></Field><Field label={t("wizard.field.uTurnRadius")} htmlFor="u_turn_turn_radius_m" error={errors.u_turn_turn_radius_m} hint={t("wizard.hint.uTurnRadius")}><input id="u_turn_turn_radius_m" type="number" min="0" max="100" step="0.1" placeholder="0–100" value={form.u_turn_turn_radius_m} onChange={handleTextChange("u_turn_turn_radius_m")} /></Field></> : null}
                {form.track_type === "lemniscate" ? <Field label={t("wizard.field.lemniscateScale")} htmlFor="lemniscate_scale_m" error={errors.lemniscate_scale_m} hint={t("wizard.hint.lemniscateScale")}><input id="lemniscate_scale_m" type="number" min="0" max="100" step="0.1" placeholder="0–100" value={form.lemniscate_scale_m} onChange={handleTextChange("lemniscate_scale_m")} /></Field> : null}
                <Field label={t("wizard.field.startX")} required htmlFor="start_x" error={errors.start_x} hint={t("wizard.hint.startX")}><input id="start_x" type="number" step="0.1" value={form.start_x} onChange={handleTextChange("start_x")} /></Field>
                <Field label={t("wizard.field.startY")} required htmlFor="start_y" error={errors.start_y} hint={t("wizard.hint.startY")}><input id="start_y" type="number" step="0.1" value={form.start_y} onChange={handleTextChange("start_y")} /></Field>
                <Field label={t("wizard.field.altitude")} required htmlFor="altitude_m" error={errors.altitude_m} hint={t("wizard.field.altitudeHint")}><input id="altitude_m" type="number" min="1" max="20" step="0.1" placeholder="1–20" value={form.altitude_m} onChange={handleTextChange("altitude_m")} /></Field>
              </div>
              {form.track_type === "custom" ? (
                <>
                  <div className="generated-track-callout">
                    <span>{t("wizard.customTrackSummary", { count: customTrack.length })}</span>
                    <button ref={trackEditorTriggerRef} type="button" className="btn btn-primary btn-small" onClick={() => setShowTrackEditor(true)}>{t("wizard.editTrack")}</button>
                  </div>
                  {errors.reference_track_json ? <p className="form-error" role="alert">{errors.reference_track_json}</p> : null}
                  {showTrackEditor ? (
                    <div className="wizard-modal-backdrop" role="presentation" onMouseDown={(event) => {
                      if (event.target !== event.currentTarget) return;
                      setShowTrackJson(false);
                      setShowTrackEditor(false);
                      window.requestAnimationFrame(() => trackEditorTriggerRef.current?.focus());
                    }}>
                      <section className="wizard-modal wizard-track-modal" role="dialog" aria-modal="true" aria-labelledby="track-editor-title">
                        <header className="wizard-modal-header">
                          <h3 id="track-editor-title">{t("wizard.editTrack")}</h3>
                          <button
                            autoFocus
                            type="button"
                            className="btn btn-ghost wizard-modal-close"
                            aria-label={t("wizard.closeTrack")}
                            title={t("wizard.closeTrack")}
                            onClick={() => {
                              setShowTrackJson(false);
                              setShowTrackEditor(false);
                              window.requestAnimationFrame(() => trackEditorTriggerRef.current?.focus());
                            }}
                          >
                            <span aria-hidden="true">×</span>
                          </button>
                        </header>
                        <TrackEditor2D
                          points={customTrack}
                          defaultAltitude={Number(form.altitude_m) || 3}
                          onChange={(points) => update("reference_track_json", JSON.stringify(points, null, 2))}
                          dataPanelAction={(
                            <>
                              <button
                                ref={trackJsonTriggerRef}
                                type="button"
                                className="track-icon-button track-json-trigger"
                                onClick={() => setShowTrackJson(true)}
                                aria-label={t("wizard.jsonImport")}
                                title={t("wizard.jsonImport")}
                              >
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                  <path d="M7 3H4v18h3" />
                                  <path d="M17 3h3v18h-3" />
                                  <path d="M8 8h8m-3-3 3 3-3 3" />
                                  <path d="M16 16H8m3-3-3 3 3 3" />
                                </svg>
                              </button>
                              {showTrackJson ? (
                                <div className="wizard-modal-backdrop wizard-nested-modal-backdrop" role="presentation" onMouseDown={(event) => {
                                  if (event.target !== event.currentTarget) return;
                                  setShowTrackJson(false);
                                  window.requestAnimationFrame(() => trackJsonTriggerRef.current?.focus());
                                }}>
                                  <section className="wizard-modal wizard-json-modal" role="dialog" aria-modal="true" aria-labelledby="track-json-title">
                                    <header className="wizard-modal-header">
                                      <h3 id="track-json-title">{t("wizard.jsonImport")}</h3>
                                      <button
                                        autoFocus
                                        type="button"
                                        className="btn btn-ghost wizard-modal-close"
                                        aria-label={t("wizard.closeJson")}
                                        title={t("wizard.closeJson")}
                                        onClick={() => {
                                          setShowTrackJson(false);
                                          window.requestAnimationFrame(() => trackJsonTriggerRef.current?.focus());
                                        }}
                                      >
                                        <span aria-hidden="true">×</span>
                                      </button>
                                    </header>
                                    <Field label={t("wizard.field.referenceTrack")} required htmlFor="reference_track_json" error={errors.reference_track_json} hint={t("wizard.field.referenceTrackHint")}>
                                      <textarea id="reference_track_json" rows={12} value={form.reference_track_json} onChange={handleTextChange("reference_track_json")} />
                                    </Field>
                                  </section>
                                </div>
                              ) : null}
                            </>
                          )}
                        />
                      </section>
                    </div>
                  ) : null}
                </>
              ) : null}
            </section>
            </div>
          </SectionCard>
          </div>
        ) : null}

        {step === 1 ? (
          <div className="wizard-panel">
          <SectionCard title={t("wizard.section.parameters")}>
            <ParameterSelector
              catalog={catalog.parameters}
              mode={form.tuning_mode}
              selections={selections}
              errors={errors}
              onChange={setSelections}
            />
          </SectionCard>
          </div>
        ) : null}

        {step === 2 ? (
          <div className="wizard-panel">
          <SectionCard title={t("wizard.section.scenarios")}>
            <div className="scenario-case-selector" aria-describedby={errors.scenario_cases ? "scenario_cases_error" : undefined}>
              <h3>{t("wizard.caseMatrix")}</h3>
              <div className="scenario-case-grid">
                {([
                  ["nominal_search_enabled", t("wizard.case.nominalSearch")],
                  ["wind_search_enabled", t("wizard.case.windSearch")],
                  ["noise_search_enabled", t("wizard.case.noiseSearch")],
                  ["nominal_holdout_enabled", t("wizard.case.nominalHoldout")],
                  ["combined_holdout_enabled", t("wizard.case.combinedHoldout")],
                ] as const).map(([key, label]) => (
                  <div className="scenario-case-option" key={key}>
                    <label htmlFor={key}><strong>{label}</strong></label>
                    <BooleanSelect
                      id={key}
                      value={form[key]}
                      onChange={(value) => update(key, value)}
                      trueLabel={t("wizard.option.enabled")}
                      falseLabel={t("wizard.option.disabled")}
                    />
                  </div>
                ))}
              </div>
              {errors.scenario_cases ? <p id="scenario_cases_error" className="form-error">{errors.scenario_cases}</p> : null}
            </div>
            <div className="form-grid scenario-base-grid">
              {(["north", "east", "south", "west"] as const).map((direction) => {
                const key = `wind_${direction}` as const;
                const labelKeys = {
                  north: "wizard.field.windNorth",
                  east: "wizard.field.windEast",
                  south: "wizard.field.windSouth",
                  west: "wizard.field.windWest",
                } as const;
                return <Field key={key} label={t(labelKeys[direction])} required htmlFor={key} error={errors[key]} hint={t("wizard.field.windHint")}><input id={key} type="number" min="-10" max="10" step="0.1" placeholder="-10–10" value={form[key]} onChange={handleTextChange(key)} /></Field>;
              })}
              <Field label={t("wizard.field.sensorNoise")} required htmlFor="sensor_noise_level" error={errors.sensor_noise_level} hint={t(SENSOR_NOISE_HINT_KEYS[form.sensor_noise_level])}>
                <select id="sensor_noise_level" value={form.sensor_noise_level} onChange={(event) => update("sensor_noise_level", event.target.value as SensorNoiseLevel)}>
                  {SENSOR_NOISE_LEVELS.map((level) => <option key={level} value={level}>{t(`wizard.noise.${level}` as TranslationKey)}</option>)}
                </select>
              </Field>
              <Field label={t("wizard.field.searchSeeds")} required htmlFor="search_seeds" error={errors.search_seeds} hint={t("wizard.field.searchSeedsHint")}>
                <input id="search_seeds" value={form.search_seeds} onChange={handleTextChange("search_seeds")} />
              </Field>
              <Field label={t("wizard.field.holdoutSeeds")} required={form.nominal_holdout_enabled || form.combined_holdout_enabled} htmlFor="holdout_seeds" error={errors.holdout_seeds ?? errors.seed_overlap} hint={t("wizard.field.holdoutSeedsHint")}>
                <input id="holdout_seeds" value={form.holdout_seeds} onChange={handleTextChange("holdout_seeds")} />
              </Field>
              <Field label={t("wizard.field.commonRandomNumbers")} htmlFor="common_random_numbers" hint={t(form.common_random_numbers ? "wizard.hint.commonRandom.enabled" : "wizard.hint.commonRandom.disabled")}>
                <BooleanSelect id="common_random_numbers" value={form.common_random_numbers} onChange={(value) => update("common_random_numbers", value)} trueLabel={t("wizard.option.yes")} falseLabel={t("wizard.option.no")} />
              </Field>
            </div>
            <section className="scenario-inline-advanced" aria-labelledby="advanced-scenario-inline-title">
              <h3 id="advanced-scenario-inline-title">{t("wizard.advancedSettings")}</h3>
              <div className="scenario-advanced-group">
                <h4>{t("wizard.environmentEffects")}</h4>
                <div className="form-grid scenario-advanced-grid">
                  <Field label={t("wizard.scenarioPresets")} htmlFor="scenario_preset">
                    <select id="scenario_preset" value={form.scenario_preset} onChange={(event) => applyScenarioPreset(event.target.value as ScenarioPreset)}>
                      {(["nominal", "wind", "sensor", "stress"] as const).map((preset) => (
                        <option key={preset} value={preset}>{t(`wizard.scenarioPreset.${preset}` as TranslationKey)}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label={t("wizard.field.advancedScenario")} htmlFor="advanced_enabled"><BooleanSelect id="advanced_enabled" value={form.advanced_enabled} onChange={(value) => update("advanced_enabled", value)} trueLabel={t("wizard.option.enabled")} falseLabel={t("wizard.option.disabled")} /></Field>
                  <Field label={t("wizard.field.gustEnabled")} htmlFor="gust_enabled"><BooleanSelect id="gust_enabled" value={form.gust_enabled} disabled={!form.advanced_enabled} onChange={(value) => update("gust_enabled", value)} trueLabel={t("wizard.option.enabled")} falseLabel={t("wizard.option.disabled")} /></Field>
                  <Field label={t("wizard.field.gustMagnitude")} htmlFor="gust_magnitude_mps" error={errors.gust_magnitude_mps}><input id="gust_magnitude_mps" type="number" min="0" max="30" step="0.1" placeholder="0–30" disabled={!form.advanced_enabled || !form.gust_enabled} value={form.gust_magnitude_mps} onChange={handleTextChange("gust_magnitude_mps")} /></Field>
                  <Field label={t("wizard.field.gustDirection")} htmlFor="gust_direction_deg" error={errors.gust_direction_deg ?? preflightErrors.gust_direction_deg}><input id="gust_direction_deg" type="number" min="0" max="359" step="1" placeholder="0–359" disabled={!form.advanced_enabled || !form.gust_enabled} value={form.gust_direction_deg} onChange={handleTextChange("gust_direction_deg")} /></Field>
                  <Field label={t("wizard.field.gustPeriod")} htmlFor="gust_period_s" error={errors.gust_period_s}><input id="gust_period_s" type="number" min="0" max="300" step="0.1" placeholder="0–300" disabled={!form.advanced_enabled || !form.gust_enabled} value={form.gust_period_s} onChange={handleTextChange("gust_period_s")} /></Field>
                </div>
              </div>
              <div className="scenario-advanced-group">
                <h4>{t("wizard.sensorVehicleEffects")}</h4>
                <div className="form-grid scenario-advanced-grid">
                  <Field label={t("wizard.field.gpsNoise")} htmlFor="gps_noise_m" error={errors.gps_noise_m}><input id="gps_noise_m" type="number" min="0" max="100" step="0.1" placeholder="0–100" disabled={!form.advanced_enabled} value={form.gps_noise_m} onChange={handleTextChange("gps_noise_m")} /></Field>
                  <Field label={t("wizard.field.baroNoise")} htmlFor="baro_noise_m" error={errors.baro_noise_m}><input id="baro_noise_m" type="number" min="0" max="100" step="0.1" placeholder="0–100" disabled={!form.advanced_enabled} value={form.baro_noise_m} onChange={handleTextChange("baro_noise_m")} /></Field>
                  <Field label={t("wizard.field.imuNoiseScale")} htmlFor="imu_noise_scale" error={errors.imu_noise_scale}><input id="imu_noise_scale" type="number" min="0" max="10" step="0.1" placeholder="0–10" disabled={!form.advanced_enabled} value={form.imu_noise_scale} onChange={handleTextChange("imu_noise_scale")} /></Field>
                  <Field label={t("wizard.field.dropoutRate")} htmlFor="dropout_rate" error={errors.dropout_rate}><input id="dropout_rate" type="number" min="0" max="1" step="0.01" placeholder="0–1" disabled={!form.advanced_enabled} value={form.dropout_rate} onChange={handleTextChange("dropout_rate")} /></Field>
                  <Field label={t("wizard.field.batteryInitial")} htmlFor="battery_initial_percent" error={errors.battery_initial_percent}><input id="battery_initial_percent" type="number" min="0" max="100" step="1" placeholder="0–100" disabled={!form.advanced_enabled} value={form.battery_initial_percent} onChange={handleTextChange("battery_initial_percent")} /></Field>
                  <Field label={t("wizard.field.batteryVoltageSag")} htmlFor="battery_voltage_sag"><BooleanSelect id="battery_voltage_sag" value={form.battery_voltage_sag} disabled={!form.advanced_enabled} onChange={(value) => update("battery_voltage_sag", value)} trueLabel={t("wizard.option.enabled")} falseLabel={t("wizard.option.disabled")} /></Field>
                  <Field label={t("wizard.field.payloadMass")} htmlFor="mass_payload_kg" error={errors.mass_payload_kg}><input id="mass_payload_kg" type="number" min="0" max="20" step="0.1" placeholder="0–20" disabled={!form.advanced_enabled} value={form.mass_payload_kg} onChange={handleTextChange("mass_payload_kg")} /></Field>
                  <div className="scenario-obstacle-action">
                    <button ref={advancedScenarioTriggerRef} type="button" className="btn btn-ghost" onClick={() => setShowAdvancedScenario(true)}>{t("wizard.editObstacles")}</button>
                  </div>
                </div>
              </div>
            </section>
            {showAdvancedScenario ? (
              <div className="wizard-modal-backdrop" role="presentation" onMouseDown={(event) => {
                if (event.target !== event.currentTarget) return;
                setShowAdvancedScenario(false);
                window.requestAnimationFrame(() => advancedScenarioTriggerRef.current?.focus());
              }}>
                <section className="wizard-modal wizard-obstacle-modal" role="dialog" aria-modal="true" aria-labelledby="advanced-scenario-title">
                  <header className="wizard-modal-header">
                    <h3 id="advanced-scenario-title">{t("wizard.field.obstaclesJson")}</h3>
                    <button
                      autoFocus
                      type="button"
                      className="btn btn-ghost wizard-modal-close"
                      aria-label={t("wizard.closeAdvanced")}
                      title={t("wizard.closeAdvanced")}
                      onClick={() => {
                        setShowAdvancedScenario(false);
                        window.requestAnimationFrame(() => advancedScenarioTriggerRef.current?.focus());
                      }}
                    >
                      <span aria-hidden="true">×</span>
                    </button>
                  </header>
                  <div className="wizard-obstacle-modal-body">
                  <Field label={t("wizard.field.obstaclesJson")} htmlFor="obstacles_json" error={errors.obstacles_json} hint={t("wizard.field.obstaclesHint")}>
                    <textarea id="obstacles_json" rows={12} value={form.obstacles_json} onChange={handleTextChange("obstacles_json")} />
                  </Field>
                  <button type="button" className="btn btn-ghost btn-small" onClick={() => update("obstacles_json", OBSTACLES_JSON_EXAMPLE)}>{t("wizard.useObstacleExample")}</button>
                  </div>
                </section>
              </div>
            ) : null}
          </SectionCard>
          </div>
        ) : null}

        {step === 3 ? (
          <div className="wizard-panel">
          <SectionCard title={t("wizard.section.constraints")}>
            <div className="constraint-strategy-layout">
              <div className="constraint-input-column">
                <div className="form-grid constraints-grid">
                  <Field label={t("wizard.field.simulatorBackend")} required htmlFor="simulator_backend" error={errors.simulator_backend} hint={t(SIMULATOR_BACKEND_HINT_KEYS[form.simulator_backend])}>
                    <select id="simulator_backend" value={form.simulator_backend} onChange={(event) => update("simulator_backend", event.target.value as SimulatorBackend)}>{USER_SIMULATOR_BACKENDS.map((backend) => <option key={backend} value={backend}>{t(backend === "real_cli" ? "wizard.simulator.realCli" : "wizard.simulator.mock")}</option>)}</select>
                  </Field>
                  <Field
                    label={t("wizard.optimizerStrategy")}
                    required
                    htmlFor="optimizer_strategy"
                    error={errors.optimizer_strategy}
                    hint={optimizerStrategyDescription(form.optimizer_strategy, t)}
                  >
                    <select id="optimizer_strategy" value={form.optimizer_strategy} onChange={(event) => update("optimizer_strategy", event.target.value as OptimizerStrategy)}>
                      <optgroup label={t("wizard.optimizerHarnessGroup")}>
                        {HARNESS_OPTIMIZER_STRATEGIES.map((strategy) => (
                          <option key={strategy} value={strategy}>
                            {optimizerStrategyLabel(strategy, t)}
                          </option>
                        ))}
                      </optgroup>
                      <optgroup label={t("wizard.optimizerExperimentalGroup")}>
                        {EXPERIMENTAL_OPTIMIZER_STRATEGIES.map((strategy) => (
                          <option key={strategy} value={strategy}>
                            {optimizerStrategyLabel(strategy, t)}
                          </option>
                        ))}
                      </optgroup>
                      <optgroup label={t("wizard.optimizerLegacyGroup")}>
                        {LEGACY_OPTIMIZER_STRATEGIES.map((strategy) => (
                          <option key={strategy} value={strategy}>
                            {optimizerStrategyLabel(strategy, t)}
                          </option>
                        ))}
                      </optgroup>
                    </select>
                  </Field>
                  <Field label={t("wizard.field.maxIterations")} required htmlFor="max_iterations" error={errors.max_iterations} hint={t(form.optimizer_strategy === "none" ? "wizard.field.maxIterationsNoOptimizerHint" : "wizard.hint.maxIterations")}><input id="max_iterations" type="number" min="1" max="100" step="1" placeholder="1–100" value={form.max_iterations} onChange={handleTextChange("max_iterations")} /></Field>
                  <Field label={t("wizard.field.trialsPerCandidate")} required htmlFor="trials_per_candidate" error={errors.trials_per_candidate} hint={t("wizard.field.trialsPerCandidateHint")}><input id="trials_per_candidate" type="number" min="1" max="10" step="1" placeholder="1–10" value={form.trials_per_candidate} onChange={handleTextChange("trials_per_candidate")} /></Field>
                  <Field label={t("wizard.field.maxTotalTrials")} required htmlFor="max_total_trials" error={errors.max_total_trials} hint={t("wizard.field.maxTotalTrialsHint")}><input id="max_total_trials" type="number" min="1" max="10000" step="1" placeholder="1–10000" value={form.max_total_trials} onChange={handleTextChange("max_total_trials")} /></Field>
                  <Field label={t("wizard.field.targetRmse")} htmlFor="target_rmse" error={errors.target_rmse} hint={t("wizard.hint.targetRmse")}><input id="target_rmse" type="number" min="0" max="100" step="0.01" placeholder="0–100" value={form.target_rmse} onChange={handleTextChange("target_rmse")} /></Field>
                  <Field label={t("wizard.field.targetMaxError")} htmlFor="target_max_error" error={errors.target_max_error} hint={t("wizard.hint.targetMaxError")}><input id="target_max_error" type="number" min="0" max="100" step="0.01" placeholder="0–100" value={form.target_max_error} onChange={handleTextChange("target_max_error")} /></Field>
                  <Field label={t("wizard.field.minPassRate")} required htmlFor="min_pass_rate" error={errors.min_pass_rate} hint={t("wizard.hint.minPassRate")}><input id="min_pass_rate" type="number" min="0" max="1" step="0.05" placeholder="0–1" value={form.min_pass_rate} onChange={handleTextChange("min_pass_rate")} /></Field>
                </div>
                {form.simulator_backend === "real_cli" && !capabilitiesUnavailable && !realCliCapability?.ready ? (
                  <Alert
                    tone={capabilities?.simulators.authoritative ? "danger" : "warning"}
                    title={t("wizard.realCliTitle")}
                  >
                    {t("wizard.realCliText")}
                  </Alert>
                ) : null}
                {optimizerUsesModelAccess(form.optimizer_strategy) && !capabilitiesUnavailable && !modelOptimizerCapability?.ready ? (
                  <Alert
                    tone={capabilities?.optimizers.authoritative ? "danger" : "warning"}
                    title={t("wizard.gptPreflightTitle")}
                  >
                    {t("wizard.gptPreflightText")}
                  </Alert>
                ) : null}
                {capabilitiesUnavailable ? (
                  <Alert tone="warning" title={t("wizard.runtimePreflightUnavailableTitle")}>
                    {t("wizard.runtimePreflightUnavailableText")}
                  </Alert>
                ) : null}
              </div>
              <OptimizationStrategyCard
                strategy={form.optimizer_strategy}
                t={t}
                modelProvider={llmProviderLabel(form.llm_provider, t)}
                modelName={form.llm_model}
                modelConfigured={
                  form.llm_access_mode === "platform"
                  || form.llm_api_key.trim() !== ""
                }
              />
            </div>
            <section className="completion-policy-card" aria-labelledby="completion-policy-title">
              <div className="completion-policy-heading">
                <div>
                  <h3 id="completion-policy-title">{t("wizard.completionPolicy.title")}</h3>
                  <p>{t("wizard.completionPolicy.firstQualifiedBody")}</p>
                </div>
                <span className="completion-policy-badge">
                  {t("wizard.completionPolicy.firstQualifiedBadge")}
                </span>
              </div>
              <label className="completion-policy-toggle">
                <input
                  type="checkbox"
                  checked={form.continue_exploration_after_qualified}
                  onChange={(event) => update(
                    "continue_exploration_after_qualified",
                    event.target.checked,
                  )}
                />
                <span>
                  <strong>{t("wizard.completionPolicy.continueTitle")}</strong>
                  <small>{t("wizard.completionPolicy.continueBody")}</small>
                </span>
              </label>
              {form.continue_exploration_after_qualified ? (
                <div className="form-grid completion-policy-budget">
                  <Field label={t("wizard.completionPolicy.generations")} required htmlFor="exploration_additional_generations" error={errors.exploration_additional_generations}>
                    <input id="exploration_additional_generations" type="number" min="1" max="32" step="1" value={form.exploration_additional_generations} onChange={handleTextChange("exploration_additional_generations")} />
                  </Field>
                  <Field label={t("wizard.completionPolicy.trials")} required htmlFor="exploration_additional_trials" error={errors.exploration_additional_trials}>
                    <input id="exploration_additional_trials" type="number" min="2" max="5000" step="1" value={form.exploration_additional_trials} onChange={handleTextChange("exploration_additional_trials")} />
                  </Field>
                  <Field label={t("wizard.completionPolicy.providerTurns")} required htmlFor="exploration_additional_provider_turns" error={errors.exploration_additional_provider_turns}>
                    <input
                      id="exploration_additional_provider_turns"
                      type="number"
                      min="0"
                      max="128"
                      step="1"
                      disabled={!optimizerUsesModelAccess(form.optimizer_strategy)}
                      value={optimizerUsesModelAccess(form.optimizer_strategy) ? form.exploration_additional_provider_turns : "0"}
                      onChange={handleTextChange("exploration_additional_provider_turns")}
                    />
                  </Field>
                  <Field label={t("wizard.completionPolicy.minutes")} required htmlFor="exploration_additional_time_minutes" error={errors.exploration_additional_time_minutes}>
                    <input id="exploration_additional_time_minutes" type="number" min="1" max="1440" step="1" value={form.exploration_additional_time_minutes} onChange={handleTextChange("exploration_additional_time_minutes")} />
                  </Field>
                  <p className="completion-policy-warning">
                    {t("wizard.completionPolicy.confirmationWarning")}
                  </p>
                </div>
              ) : null}
            </section>
          </SectionCard>
          </div>
        ) : null}

        {step === 4 ? (
          <div className="wizard-panel">
          <SectionCard title={t("wizard.section.review")}>
            {preflightSteps.length === 0 ? (
              <div className="preflight-status" role="status"><span aria-hidden="true">✓</span>{t("wizard.preflightReadyTitle")}</div>
            ) : (
              <Alert tone="danger" title={t("wizard.preflightIssuesTitle")}>
                <div className="review-issue-links">
                  {preflightSteps.map((issueStep) => (
                    <button
                      key={issueStep}
                      type="button"
                      className="btn btn-ghost btn-small"
                      onClick={() => {
                        const issueKeys = Object.keys(preflightErrors).filter(
                          (key) => errorStep(key, catalog) === issueStep,
                        );
                        const firstIssueKey = issueKeys[0];
                        setErrors(preflightErrors);
                        setStep(issueStep);
                        if (firstIssueKey && issueStep === 2 && opensAdvancedScenarioDialog(firstIssueKey)) setShowAdvancedScenario(true);
                        if (firstIssueKey && issueStep === 0 && opensTrackDialog(firstIssueKey)) setShowTrackEditor(true);
                        if (firstIssueKey && issueStep === 3 && opensModelSettings(firstIssueKey)) openAppSettings();
                      }}
                    >
                      {t(WIZARD_STEPS[issueStep].key)} ({Object.keys(preflightErrors).filter((key) => errorStep(key, catalog) === issueStep).length})
                    </button>
                  ))}
                </div>
              </Alert>
            )}
            <div className="review-grid review-grid-detailed">
              <ReviewBlock title={t("wizard.reviewVehicle")}>
                <ReviewFact label={t("wizard.field.px4Version")} value={form.px4_version} />
                <ReviewFact label={t("wizard.field.firmwareCommit")} value={form.firmware_commit || t("wizard.review.notSet")} />
                <ReviewFact label={t("wizard.field.airframe")} value={form.airframe} />
                <ReviewFact label={t("wizard.field.gazeboModel")} value={form.simulator_model} />
                <ReviewFact label={t("wizard.field.gazeboWorld")} value={simulatorWorldLabel(form.simulator_world, t)} />
                <ReviewFact label={t("wizard.field.headless")} value={t(form.simulator_headless ? "wizard.option.disabled" : "wizard.option.enabled")} />
                <ReviewFact label={t("wizard.field.simulationSpeed")} value={`×${form.simulation_speed_factor}`} />
                <ReviewFact label={t("wizard.field.instanceId")} value={form.instance_id} />
                <ReviewFact label={t("wizard.field.trackType")} value={t(`wizard.track.${form.track_type}` as TranslationKey)} />
                <ReviewFact label={`${t("wizard.field.startX")} / ${t("wizard.field.startY")}`} value={`${form.start_x} / ${form.start_y}`} />
                <ReviewFact label={t("wizard.field.altitude")} value={form.altitude_m} />
              </ReviewBlock>
              <ReviewBlock title={t("wizard.reviewSearch")}>
                <ReviewFact label={t("wizard.aria.modeSelector")} value={t(`wizard.mode.${form.tuning_mode}` as TranslationKey)} />
                <ReviewFact label={t("wizard.field.objectiveProfile")} value={t(`wizard.objective.${form.objective_profile}` as TranslationKey)} />
                <ReviewFact label={t("wizard.selectedParameters")} value={t("wizard.review.parameterCount", { count: selectedCount })} />
                <ReviewFact label={t("wizard.field.weightTracking")} value={form.objective_weight_tracking} />
                <ReviewFact label={t("wizard.field.weightSpeed")} value={form.objective_weight_speed} />
                <ReviewFact label={t("wizard.field.weightSmoothness")} value={form.objective_weight_smoothness} />
                <ReviewFact label={t("wizard.field.weightRobustness")} value={form.objective_weight_robustness} />
                <ReviewFact label={t("wizard.field.robustAggregation")} value={t(`wizard.aggregation.${form.robust_aggregation}` as TranslationKey)} />
              </ReviewBlock>
              <ReviewBlock title={t("wizard.reviewScenarios")}>
                <ReviewFact label={t("wizard.scenarioPresets")} value={t(`wizard.scenarioPreset.${form.scenario_preset}` as TranslationKey)} />
                <ReviewFact label={t("wizard.case.nominalSearch")} value={t(form.nominal_search_enabled ? "wizard.option.enabled" : "wizard.option.disabled")} />
                <ReviewFact label={t("wizard.case.windSearch")} value={t(form.wind_search_enabled ? "wizard.option.enabled" : "wizard.option.disabled")} />
                <ReviewFact label={t("wizard.case.noiseSearch")} value={t(form.noise_search_enabled ? "wizard.option.enabled" : "wizard.option.disabled")} />
                <ReviewFact label={t("wizard.case.nominalHoldout")} value={t(form.nominal_holdout_enabled ? "wizard.option.enabled" : "wizard.option.disabled")} />
                <ReviewFact label={t("wizard.case.combinedHoldout")} value={t(form.combined_holdout_enabled ? "wizard.option.enabled" : "wizard.option.disabled")} />
                <ReviewFact label={t("wizard.field.sensorNoise")} value={t(`wizard.noise.${form.sensor_noise_level}` as TranslationKey)} />
                <ReviewFact label={t("wizard.review.windVector")} value={`N ${form.wind_north} · E ${form.wind_east} · S ${form.wind_south} · W ${form.wind_west}`} />
                <ReviewFact label={t("wizard.field.searchSeeds")} value={form.search_seeds} />
                <ReviewFact label={t("wizard.field.holdoutSeeds")} value={form.holdout_seeds} />
                <ReviewFact label={t("wizard.field.commonRandomNumbers")} value={t(form.common_random_numbers ? "wizard.option.yes" : "wizard.option.no")} />
                <ReviewFact label={t("wizard.field.advancedScenario")} value={t(form.advanced_enabled ? "wizard.option.enabled" : "wizard.option.disabled")} />
              </ReviewBlock>
              <ReviewBlock title={t("wizard.reviewBudget")}>
                <ReviewFact label={t("wizard.field.simulatorBackend")} value={t(form.simulator_backend === "real_cli" ? "wizard.simulator.realCli" : "wizard.simulator.mock")} />
                <ReviewFact label={t("wizard.optimizerStrategy")} value={optimizerStrategyLabel(form.optimizer_strategy, t)} />
                <ReviewFact label={t("wizard.field.maxIterations")} value={form.max_iterations} />
                <ReviewFact label={t("wizard.field.trialsPerCandidate")} value={form.trials_per_candidate} />
                <ReviewFact label={t("wizard.field.maxTotalTrials")} value={form.max_total_trials} />
                <ReviewFact label={t("wizard.review.scheduledLabel")} value={t("wizard.review.scheduledPlan", { scheduled: estimatedTrials, planned: trialPlan.plannedTrials })} />
                <ReviewFact label={t("wizard.field.targetRmse")} value={form.target_rmse || t("wizard.review.notSet")} />
                <ReviewFact label={t("wizard.field.targetMaxError")} value={form.target_max_error || t("wizard.review.notSet")} />
                <ReviewFact label={t("wizard.field.minPassRate")} value={form.min_pass_rate} />
                <ReviewFact label={t("wizard.completionPolicy.title")} value={t("wizard.completionPolicy.firstQualifiedBadge")} />
                <ReviewFact
                  label={t("wizard.completionPolicy.continueTitle")}
                  value={form.continue_exploration_after_qualified
                    ? t("wizard.completionPolicy.reviewBudget", {
                        generations: form.exploration_additional_generations,
                        trials: form.exploration_additional_trials,
                        turns: optimizerUsesModelAccess(form.optimizer_strategy)
                          ? form.exploration_additional_provider_turns
                          : "0",
                        minutes: form.exploration_additional_time_minutes,
                      })
                    : t("wizard.completionPolicy.notRequested")}
                />
              </ReviewBlock>
            </div>
            <section className="review-block review-parameter-card" aria-labelledby="selected-parameters-title">
              <div className="review-parameter-card-heading">
                <h3 id="selected-parameters-title">
                  <button
                    ref={parameterReviewTriggerRef}
                    type="button"
                    className="review-parameter-title-button"
                    aria-label={t("wizard.viewAllParameters")}
                    aria-haspopup="dialog"
                    aria-expanded={showParameterReview}
                    onClick={() => setShowParameterReview(true)}
                  >
                    {t("wizard.selectedParameters")}
                    <svg viewBox="0 0 20 20" aria-hidden="true">
                      <path d="M7 4h9v9M16 4 6 14M13 11v5H4V7h5" />
                    </svg>
                  </button>
                </h3>
                <span>{t("wizard.review.parameterCount", { count: selectedParameterRows.length })}</span>
              </div>
              <div
                ref={reviewParameterPreviewRef}
                className="review-parameter-chips review-parameter-preview"
                aria-hidden="true"
                onWheel={handleReviewParameterWheel}
              >
                {selectedParameterRows.map((parameter) => (
                  <code key={parameter.name}>
                    <strong>{parameter.name}</strong>
                    <span>{parameter.search_min} – {parameter.search_max}</span>
                  </code>
                ))}
              </div>
            </section>
            {showParameterReview ? (
              <div
                className="wizard-modal-backdrop"
                role="presentation"
                onMouseDown={(event) => {
                  if (event.target !== event.currentTarget) return;
                  setShowParameterReview(false);
                  window.requestAnimationFrame(() => parameterReviewTriggerRef.current?.focus());
                }}
              >
                <section
                  className="wizard-modal wizard-parameter-review-modal"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="selected-parameters-dialog-title"
                >
                  <header className="wizard-modal-header">
                    <div>
                      <h3 id="selected-parameters-dialog-title">{t("wizard.selectedParameters")}</h3>
                      <span>{t("wizard.review.parameterCount", { count: selectedParameterRows.length })}</span>
                    </div>
                    <button
                      autoFocus
                      type="button"
                      className="btn btn-ghost wizard-modal-close"
                      aria-label={t("wizard.closeParameterReview")}
                      title={t("wizard.closeParameterReview")}
                      onClick={() => {
                        setShowParameterReview(false);
                        window.requestAnimationFrame(() => parameterReviewTriggerRef.current?.focus());
                      }}
                    >
                      <span aria-hidden="true">×</span>
                    </button>
                  </header>
                  <div className="review-parameter-modal-grid">
                    {selectedParameterRows.map((parameter) => (
                      <code key={parameter.name}>
                        <strong>{parameter.name}</strong>
                        <span>{parameter.search_min} – {parameter.search_max}</span>
                      </code>
                    ))}
                  </div>
                </section>
              </div>
            ) : null}
          </SectionCard>
          </div>
        ) : null}

        <div className="wizard-actions">
          {step > 0 ? <button type="button" className="btn btn-ghost" disabled={submitting} onClick={previousStep}>{t("wizard.back")}</button> : null}
          {step < 4 ? <button type="button" className="btn btn-primary" disabled={submitting || currentStepHasErrors} onClick={nextStep}>{t("wizard.next")}</button> : null}
          {step === 4 ? (
            <>
              <button className="btn btn-primary" type="submit" disabled={submitting}>
                {submitting
                  ? t("wizard.creating")
                  : publicDemoConsole
                    ? "Save editable draft"
                    : t("wizard.create")}
              </button>
              {publicDemoConsole ? (
                <button
                  className="btn btn-primary"
                  type="button"
                  disabled
                  title="Execution is available only in an installed DroneDream edition with its validated runtime and safety gates."
                  data-execution-authority="false"
                >
                  Run experiment in installed app
                </button>
              ) : null}
            </>
          ) : null}
        </div>
      </form>
    </section>
  );
}

function ReviewBlock({ title, children }: { title: string; children: ReactNode }) {
  return <section className="review-block"><h3>{title}</h3><dl className="review-facts">{children}</dl></section>;
}

function ReviewFact({ label, value }: { label: string; value: ReactNode }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

interface BooleanSelectProps {
  id: string;
  value: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
  trueLabel: string;
  falseLabel: string;
}

function BooleanSelect({
  id,
  value,
  disabled = false,
  onChange,
  trueLabel,
  falseLabel,
}: BooleanSelectProps) {
  return (
    <select
      id={id}
      value={value ? "true" : "false"}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value === "true")}
    >
      <option value="true">{trueLabel}</option>
      <option value="false">{falseLabel}</option>
    </select>
  );
}

interface FieldProps {
  label: string;
  htmlFor: string;
  required?: boolean;
  error?: string;
  hint?: string;
  children: ReactNode;
}

function Field({ label, htmlFor, required, error, children }: FieldProps) {
  return (
    <div className={`form-field${error ? " form-field-error" : ""}`}>
      <label htmlFor={htmlFor} className={required ? "form-field-required" : undefined}>{label}</label>
      {children}
      {error ? <span className="form-error" role="alert">{error}</span> : null}
    </div>
  );
}

function OptimizationStrategyCard({
  strategy,
  t,
  modelProvider,
  modelName,
  modelConfigured,
}: {
  strategy: OptimizerStrategy;
  t: Translate;
  modelProvider: string;
  modelName: string;
  modelConfigured: boolean;
}) {
  const presentation = optimizerStrategyCard(strategy, t);
  const flowDetails = [
    t("wizard.strategyCard.flowDetail1"),
    t("wizard.strategyCard.flowDetail2"),
    t("wizard.strategyCard.flowDetail3"),
    t("wizard.strategyCard.flowDetail4"),
  ];
  const modelStatus = !modelConfigured
    ? t("wizard.strategyCard.modelMissing")
    : modelName.trim()
      ? t("wizard.strategyCard.modelReady", { provider: modelProvider, model: modelName })
      : t("wizard.strategyCard.modelDefault", { provider: modelProvider });

  return (
    <section
      className="optimization-strategy-card"
      aria-label={t("wizard.pipeline.aria")}
    >
      <header className="optimization-strategy-heading">
        <h3>{presentation.label}</h3>
        <p>{presentation.description}</p>
      </header>
      <div className="optimization-strategy-flow" aria-label={t("wizard.strategyCard.flowTitle")}>
        {presentation.flow.map((stage, index) => (
          <div className="optimization-strategy-step" key={stage}>
            <span aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{stage}</strong>
              <p>{flowDetails[index]}</p>
            </div>
          </div>
        ))}
      </div>
      {optimizerUsesModelAccess(strategy) ? (
        <div className={`optimization-model-status${modelConfigured ? " configured" : ""}`}>
          <span>{t("wizard.strategyCard.modelAccess")}</span>
          <strong>{modelStatus}</strong>
        </div>
      ) : null}
      <div className="optimization-strategy-copy">
        <p>{presentation.detail}</p>
      </div>
    </section>
  );
}
