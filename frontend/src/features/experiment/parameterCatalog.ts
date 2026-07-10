import type {
  ParameterCatalogApiResponse,
  ParameterCatalogResponse,
  ParameterRisk,
  PX4ParameterDefinition,
  StudyParameterSelection,
  TuningMode,
} from "../../types/api";

const LEGACY_KEYS: Record<string, PX4ParameterDefinition["legacy_key"]> = {
  MPC_XY_P: "kp_xy",
  MPC_XY_VEL_D_ACC: "kd_xy",
  MPC_XY_VEL_I_ACC: "ki_xy",
  MPC_XY_VEL_MAX: "vel_limit",
  MPC_ACC_HOR: "accel_limit",
};

const ALL_MULTICOPTERS = ["multicopter", "x500"];

interface BuiltinParameterOptions {
  unit?: string;
  risk?: ParameterRisk;
  valueType?: PX4ParameterDefinition["value_type"];
  requiresReboot?: boolean;
  dependencies?: string[];
}

function builtinParameter(
  name: string,
  label: string,
  group: string,
  description: string,
  hard: [number, number],
  safe: [number, number],
  defaultValue: number,
  step: number,
  options: BuiltinParameterOptions = {},
): PX4ParameterDefinition {
  return {
    name,
    label,
    group,
    description,
    unit: options.unit || null,
    value_type: options.valueType ?? "float",
    default_value: defaultValue,
    absolute_min: hard[0],
    absolute_max: hard[1],
    safe_min: safe[0],
    safe_max: safe[1],
    step,
    scale: "linear",
    risk: options.risk ?? "medium",
    requires_reboot: options.requiresReboot ?? false,
    dependencies: options.dependencies ?? [],
    supported_airframes: ALL_MULTICOPTERS,
    legacy_key: LEGACY_KEYS[name] ?? null,
  };
}

// Full offline fallback for the same 28-parameter PX4 snapshot exposed by the
// backend. This keeps the wizard useful when the read-only catalog endpoint is
// temporarily unavailable; the server still validates the submitted ranges.
export const BUILTIN_PARAMETER_CATALOG: ParameterCatalogResponse = {
  catalog_version: "dronedream.px4.multicopter.2026-07-r1",
  px4_version: "v1.16",
  source: "builtin",
  parameters: [
    builtinParameter("MPC_XY_P", "Horizontal position P", "xy_position_velocity", "Corrective horizontal velocity per metre of position error.", [0, 2], [0.6, 1.3], 0.95, 0.1, { dependencies: ["MPC_XY_VEL_P_ACC"] }),
    builtinParameter("MPC_XY_VEL_P_ACC", "Horizontal velocity P", "xy_position_velocity", "Corrective acceleration per horizontal velocity error.", [1.2, 5], [1.2, 2.8], 1.8, 0.1),
    builtinParameter("MPC_XY_VEL_I_ACC", "Horizontal velocity I", "xy_position_velocity", "Integral correction for steady horizontal disturbances.", [0, 60], [0.1, 1], 0.4, 0.02, { risk: "high", dependencies: ["MPC_XY_VEL_P_ACC"] }),
    builtinParameter("MPC_XY_VEL_D_ACC", "Horizontal velocity D", "xy_position_velocity", "Damping from horizontal velocity-error derivative.", [0.1, 2], [0.1, 0.5], 0.2, 0.02, { risk: "high", dependencies: ["MPC_XY_VEL_P_ACC"] }),
    builtinParameter("MPC_Z_P", "Vertical position P", "z_position_velocity", "Corrective climb rate per metre of altitude error.", [0.1, 1.5], [0.6, 1.3], 1, 0.1, { dependencies: ["MPC_Z_VEL_P_ACC"] }),
    builtinParameter("MPC_Z_VEL_P_ACC", "Vertical velocity P", "z_position_velocity", "Corrective vertical acceleration per climb-rate error.", [2, 15], [2.5, 8], 4, 0.1),
    builtinParameter("MPC_Z_VEL_I_ACC", "Vertical velocity I", "z_position_velocity", "Integral correction for sustained vertical error.", [0.2, 3], [0.5, 2.5], 2, 0.1, { risk: "high", dependencies: ["MPC_Z_VEL_P_ACC"] }),
    builtinParameter("MPC_Z_VEL_D_ACC", "Vertical velocity D", "z_position_velocity", "Damping from vertical velocity-error derivative.", [0, 2], [0, 0.5], 0, 0.02, { risk: "high", dependencies: ["MPC_Z_VEL_P_ACC"] }),
    builtinParameter("MC_ROLL_P", "Roll attitude P", "attitude", "Desired roll rate per radian of roll attitude error.", [0, 12], [2, 8], 4, 0.1, { risk: "high", dependencies: ["MC_PITCH_P"] }),
    builtinParameter("MC_PITCH_P", "Pitch attitude P", "attitude", "Desired pitch rate per radian of pitch attitude error.", [0, 12], [2, 8], 4, 0.1, { risk: "high", dependencies: ["MC_ROLL_P"] }),
    builtinParameter("MC_YAW_P", "Yaw attitude P", "attitude", "Desired yaw rate per radian of yaw attitude error.", [0, 5], [1, 4], 2.8, 0.1, { risk: "high", dependencies: ["MC_YAWRATE_P"] }),
    builtinParameter("MC_ROLLRATE_P", "Roll rate P", "angular_rate", "Proportional torque command for roll-rate error.", [0.01, 0.5], [0.08, 0.25], 0.15, 0.01, { risk: "high" }),
    builtinParameter("MC_ROLLRATE_I", "Roll rate I", "angular_rate", "Integral correction for persistent roll-rate error.", [0, 1], [0.05, 0.4], 0.2, 0.01, { risk: "high", dependencies: ["MC_ROLLRATE_P"] }),
    builtinParameter("MC_ROLLRATE_D", "Roll rate D", "angular_rate", "Derivative damping for fast roll oscillations.", [0, 0.01], [0.001, 0.006], 0.003, 0.0005, { risk: "high", dependencies: ["MC_ROLLRATE_P"] }),
    builtinParameter("MC_PITCHRATE_P", "Pitch rate P", "angular_rate", "Proportional torque command for pitch-rate error.", [0.01, 0.6], [0.08, 0.3], 0.15, 0.01, { risk: "high" }),
    builtinParameter("MC_PITCHRATE_I", "Pitch rate I", "angular_rate", "Integral correction for persistent pitch-rate error.", [0, 1], [0.05, 0.4], 0.2, 0.01, { risk: "high", dependencies: ["MC_PITCHRATE_P"] }),
    builtinParameter("MC_PITCHRATE_D", "Pitch rate D", "angular_rate", "Derivative damping for fast pitch oscillations.", [0, 0.01], [0.001, 0.006], 0.003, 0.0005, { risk: "high", dependencies: ["MC_PITCHRATE_P"] }),
    builtinParameter("MC_YAWRATE_P", "Yaw rate P", "angular_rate", "Proportional torque command for yaw-rate error.", [0, 0.6], [0.05, 0.35], 0.2, 0.01, { risk: "high" }),
    builtinParameter("MC_YAWRATE_I", "Yaw rate I", "angular_rate", "Integral correction for persistent yaw-rate error.", [0, 0.5], [0.02, 0.25], 0.1, 0.01, { risk: "high", dependencies: ["MC_YAWRATE_P"] }),
    builtinParameter("MPC_XY_VEL_MAX", "Maximum horizontal velocity", "motion_limits", "Absolute velocity ceiling for horizontal controlled modes.", [0, 20], [1, 12], 12, 1, { unit: "m/s" }),
    builtinParameter("MPC_Z_VEL_MAX_UP", "Maximum ascent velocity", "motion_limits", "Absolute climb-rate ceiling.", [0.5, 8], [1, 5], 3, 0.1, { unit: "m/s" }),
    builtinParameter("MPC_Z_VEL_MAX_DN", "Maximum descent velocity", "motion_limits", "Absolute descent-rate ceiling.", [0.5, 4], [0.5, 2.5], 1.5, 0.1, { unit: "m/s" }),
    builtinParameter("MPC_ACC_HOR", "Horizontal acceleration", "motion_limits", "Commanded horizontal acceleration in autonomous modes.", [2, 15], [2, 8], 3, 1, { unit: "m/s²", dependencies: ["MPC_ACC_HOR_MAX"] }),
    builtinParameter("MPC_ACC_HOR_MAX", "Maximum horizontal acceleration", "motion_limits", "Upper horizontal acceleration limit where applicable.", [2, 15], [3, 10], 5, 1, { unit: "m/s²" }),
    builtinParameter("MPC_JERK_AUTO", "Autonomous jerk limit", "motion_limits", "Maximum acceleration slew in autonomous modes.", [1, 80], [2, 20], 4, 1, { unit: "m/s³" }),
    builtinParameter("MPC_TILTMAX_AIR", "Maximum in-air tilt", "motion_limits", "Maximum tilt used by velocity and acceleration controlled flight modes.", [20, 89], [25, 60], 45, 1, { unit: "deg", risk: "high" }),
    builtinParameter("MC_AIRMODE", "Multicopter air-mode", "motion_limits", "Mixer control-authority policy at very low and high throttle (0, 1, or 2).", [0, 2], [0, 2], 0, 1, { valueType: "integer", risk: "high" }),
    builtinParameter("IMU_GYRO_CUTOFF", "Gyroscope low-pass cutoff", "filters", "Second-order low-pass cutoff for gyro data sent to the controllers.", [0, 1000], [20, 80], 40, 1, { unit: "Hz", risk: "high", requiresReboot: true, dependencies: ["MC_ROLLRATE_D"] }),
  ],
};

const MODE_PRESETS: Record<TuningMode, string[]> = {
  basic: ["MPC_XY_P", "MPC_XY_VEL_MAX", "MPC_ACC_HOR"],
  advanced: [
    "MPC_XY_P",
    "MPC_XY_VEL_P_ACC",
    "MPC_XY_VEL_I_ACC",
    "MPC_XY_VEL_D_ACC",
    "MPC_XY_VEL_MAX",
    "MPC_ACC_HOR",
  ],
  expert: [
    "MPC_XY_P",
    "MPC_XY_VEL_P_ACC",
    "MPC_XY_VEL_I_ACC",
    "MPC_XY_VEL_D_ACC",
    "MPC_XY_VEL_MAX",
    "MPC_ACC_HOR",
  ],
};

export type ParameterSelectionMap = Record<
  string,
  StudyParameterSelection & { selected: boolean }
>;

export function createParameterSelections(
  catalog: PX4ParameterDefinition[],
  mode: TuningMode,
): ParameterSelectionMap {
  const selected = new Set(MODE_PRESETS[mode]);
  return Object.fromEntries(
    catalog.map((parameter) => [
      parameter.name,
      {
        name: parameter.name,
        baseline: parameter.default_value,
        search_min: parameter.safe_min,
        search_max: parameter.safe_max,
        scale: parameter.scale,
        selected: selected.has(parameter.name),
      },
    ]),
  ) as ParameterSelectionMap;
}

export function normalizeCatalog(
  response: ParameterCatalogResponse | null | undefined,
): ParameterCatalogResponse {
  if (!response || !Array.isArray(response.parameters) || response.parameters.length === 0) {
    return BUILTIN_PARAMETER_CATALOG;
  }
  const valid = response.parameters.filter(
    (item) =>
      item &&
      typeof item.name === "string" &&
      Number.isFinite(item.default_value) &&
      Number.isFinite(item.safe_min) &&
      Number.isFinite(item.safe_max),
  );
  return valid.length === 0
    ? BUILTIN_PARAMETER_CATALOG
    : { ...response, parameters: valid };
}

export function normalizeApiCatalog(
  response: ParameterCatalogApiResponse,
): ParameterCatalogResponse {
  const parameters: PX4ParameterDefinition[] = response.parameters.map((item) => ({
    name: item.name,
    label: item.label.en,
    localized_label: item.label,
    group: item.group,
    description: item.description.en,
    localized_description: item.description,
    unit: item.unit || null,
    // The catalog wire format uses PX4's `int`; Job.parameter_space uses the
    // schema value `integer`. This is especially important for MC_AIRMODE.
    value_type: item.type === "int" || item.type === "integer" ? "integer" : "float",
    default_value: item.default,
    absolute_min: item.hard_bounds.min,
    absolute_max: item.hard_bounds.max,
    safe_min: item.safe_bounds.min,
    safe_max: item.safe_bounds.max,
    step: item.step,
    scale: item.safe_bounds.min > 0 && item.safe_bounds.max / item.safe_bounds.min >= 100
      ? "log"
      : "linear",
    risk: item.risk,
    requires_reboot: item.requires_reboot,
    dependencies: item.dependencies.map((dependency) => dependency.parameter),
    supported_airframes: ALL_MULTICOPTERS,
    legacy_key: LEGACY_KEYS[item.name] ?? null,
  }));
  return normalizeCatalog({
    catalog_version: response.catalog_version,
    px4_version: response.px4_version,
    source: "backend",
    parameters,
  });
}

export function selectedParameters(
  selections: ParameterSelectionMap,
): StudyParameterSelection[] {
  return Object.values(selections)
    .filter((selection) => selection.selected)
    .map((selection) => ({
      name: selection.name,
      baseline: selection.baseline,
      search_min: selection.search_min,
      search_max: selection.search_max,
      scale: selection.scale,
    }));
}

export function groupCatalog(
  catalog: PX4ParameterDefinition[],
): Array<[string, PX4ParameterDefinition[]]> {
  const groups = new Map<string, PX4ParameterDefinition[]>();
  for (const parameter of catalog) {
    groups.set(parameter.group, [...(groups.get(parameter.group) ?? []), parameter]);
  }
  return [...groups.entries()];
}
