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

const BUILTIN_PARAMETER_ZH: Record<string, { label: string; description: string }> = {
  MPC_XY_P: { label: "水平位置 P", description: "根据水平位置误差生成修正水平速度。" },
  MPC_XY_VEL_P_ACC: { label: "水平速度 P", description: "根据水平速度误差生成修正加速度。" },
  MPC_XY_VEL_I_ACC: { label: "水平速度 I", description: "补偿持续存在的水平扰动。" },
  MPC_XY_VEL_D_ACC: { label: "水平速度 D", description: "利用水平速度误差变化率增加阻尼。" },
  MPC_Z_P: { label: "垂直位置 P", description: "根据高度误差生成修正升降速度。" },
  MPC_Z_VEL_P_ACC: { label: "垂直速度 P", description: "根据升降速度误差生成修正垂直加速度。" },
  MPC_Z_VEL_I_ACC: { label: "垂直速度 I", description: "补偿持续存在的垂直误差。" },
  MPC_Z_VEL_D_ACC: { label: "垂直速度 D", description: "利用垂直速度误差变化率增加阻尼。" },
  MC_ROLL_P: { label: "横滚姿态 P", description: "根据横滚姿态误差生成期望横滚角速度。" },
  MC_PITCH_P: { label: "俯仰姿态 P", description: "根据俯仰姿态误差生成期望俯仰角速度。" },
  MC_YAW_P: { label: "偏航姿态 P", description: "根据偏航姿态误差生成期望偏航角速度。" },
  MC_ROLLRATE_P: { label: "横滚角速度 P", description: "根据横滚角速度误差生成比例力矩指令。" },
  MC_ROLLRATE_I: { label: "横滚角速度 I", description: "补偿持续存在的横滚角速度误差。" },
  MC_ROLLRATE_D: { label: "横滚角速度 D", description: "抑制快速横滚振荡。" },
  MC_PITCHRATE_P: { label: "俯仰角速度 P", description: "根据俯仰角速度误差生成比例力矩指令。" },
  MC_PITCHRATE_I: { label: "俯仰角速度 I", description: "补偿持续存在的俯仰角速度误差。" },
  MC_PITCHRATE_D: { label: "俯仰角速度 D", description: "抑制快速俯仰振荡。" },
  MC_YAWRATE_P: { label: "偏航角速度 P", description: "根据偏航角速度误差生成比例力矩指令。" },
  MC_YAWRATE_I: { label: "偏航角速度 I", description: "补偿持续存在的偏航角速度误差。" },
  MPC_XY_VEL_MAX: { label: "最大水平速度", description: "限制水平受控飞行模式的绝对速度。" },
  MPC_Z_VEL_MAX_UP: { label: "最大上升速度", description: "限制飞行器的最大爬升速度。" },
  MPC_Z_VEL_MAX_DN: { label: "最大下降速度", description: "限制飞行器的最大下降速度。" },
  MPC_ACC_HOR: { label: "水平加速度", description: "设置自主飞行模式中的指令水平加速度。" },
  MPC_ACC_HOR_MAX: { label: "最大水平加速度", description: "设置适用场景下的水平加速度上限。" },
  MPC_JERK_AUTO: { label: "自主飞行加加速度上限", description: "限制自主飞行模式中的加速度变化率。" },
  MPC_TILTMAX_AIR: { label: "空中最大倾角", description: "限制速度和加速度控制飞行中的最大倾角。" },
  MC_AIRMODE: { label: "多旋翼空中模式", description: "设置低油门和高油门附近的混控权限策略。" },
  IMU_GYRO_CUTOFF: { label: "陀螺仪低通截止频率", description: "设置发送给控制器的陀螺仪二阶低通截止频率。" },
};

interface BuiltinParameterOptions {
  unit?: string;
  risk?: ParameterRisk;
  valueType?: PX4ParameterDefinition["value_type"];
  requiresReboot?: boolean;
  dependencies?: string[];
  applyPolicy?: PX4ParameterDefinition["apply_policy"];
  preconditions?: string[];
  riskNote?: PX4ParameterDefinition["risk_note"];
  choices?: PX4ParameterDefinition["choices"];
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
  const chinese = BUILTIN_PARAMETER_ZH[name];
  return {
    name,
    label,
    group,
    description,
    localized_label: { en: label, "zh-CN": chinese?.label ?? name },
    localized_description: { en: description, "zh-CN": chinese?.description ?? "" },
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
    apply_policy: options.applyPolicy ?? (options.requiresReboot ? "reboot" : "disarmed"),
    preconditions: options.preconditions ?? [],
    risk_note: options.riskNote ?? null,
    choices: options.choices ?? [],
    legacy_key: LEGACY_KEYS[name] ?? null,
  };
}

// Curated 28-parameter offline core subset. The backend r2 catalog exposes a
// broader 45-parameter set when reachable; the server always performs the
// authoritative version, applicability, coupling, and range validation.
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
    builtinParameter("MC_AIRMODE", "Multicopter air-mode", "motion_limits", "Mixer control-authority policy at very low and high throttle (0, 1, or 2).", [0, 2], [0, 2], 0, 1, {
      valueType: "integer",
      risk: "high",
      choices: [
        { value: 0, label: { en: "Disabled", "zh-CN": "关闭" } },
        { value: 1, label: { en: "Roll/pitch", "zh-CN": "横滚/俯仰" } },
        { value: 2, label: { en: "Roll/pitch/yaw", "zh-CN": "横滚/俯仰/偏航" } },
      ],
      riskNote: {
        en: "Changing air-mode changes mixer authority close to actuator saturation.",
        "zh-CN": "修改空中模式会改变执行器接近饱和时的混控权限。",
      },
    }),
    builtinParameter("IMU_GYRO_CUTOFF", "Gyroscope low-pass cutoff", "filters", "Second-order low-pass cutoff for gyro data sent to the controllers.", [0, 1000], [20, 80], 40, 1, { unit: "Hz", risk: "high", requiresReboot: true, dependencies: ["MC_ROLLRATE_D"] }),
  ],
};

const MODE_PRESETS: Record<TuningMode, string[]> = {
  basic: ["MPC_XY_P", "MPC_XY_VEL_MAX", "MPC_ACC_HOR", "MPC_ACC_HOR_MAX"],
  advanced: [
    "MPC_XY_P",
    "MPC_XY_VEL_P_ACC",
    "MPC_XY_VEL_I_ACC",
    "MPC_XY_VEL_D_ACC",
    "MPC_XY_VEL_MAX",
    "MPC_ACC_HOR",
    "MPC_ACC_HOR_MAX",
  ],
  expert: [
    "MPC_XY_P",
    "MPC_XY_VEL_P_ACC",
    "MPC_XY_VEL_I_ACC",
    "MPC_XY_VEL_D_ACC",
    "MPC_XY_VEL_MAX",
    "MPC_ACC_HOR",
    "MPC_ACC_HOR_MAX",
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
  const names = new Set<string>();
  const valid = response.parameters.filter((item) => {
    if (
      !item ||
      typeof item.name !== "string" ||
      !/^[A-Z][A-Z0-9_]{0,63}$/u.test(item.name) ||
      names.has(item.name) ||
      typeof item.label !== "string" ||
      typeof item.description !== "string" ||
      typeof item.group !== "string" ||
      item.group.trim() === "" ||
      !["float", "integer"].includes(item.value_type) ||
      !["linear", "log"].includes(item.scale) ||
      !["low", "medium", "high"].includes(item.risk) ||
      !Number.isFinite(item.default_value) ||
      !Number.isFinite(item.absolute_min) ||
      !Number.isFinite(item.absolute_max) ||
      !Number.isFinite(item.safe_min) ||
      !Number.isFinite(item.safe_max) ||
      !Number.isFinite(item.step) ||
      item.absolute_min >= item.absolute_max ||
      item.safe_min >= item.safe_max ||
      item.safe_min < item.absolute_min ||
      item.safe_max > item.absolute_max ||
      item.default_value < item.absolute_min ||
      item.default_value > item.absolute_max ||
      item.default_value < item.safe_min ||
      item.default_value > item.safe_max ||
      item.step <= 0 ||
      (item.scale === "log" && item.safe_min <= 0) ||
      (item.value_type === "integer" && ![
        item.default_value,
        item.absolute_min,
        item.absolute_max,
        item.safe_min,
        item.safe_max,
        item.step,
      ].every(Number.isInteger)) ||
      !Array.isArray(item.dependencies) ||
      item.dependencies.some((dependency) => typeof dependency !== "string")
    ) {
      return false;
    }
    names.add(item.name);
    return true;
  });
  return valid.length === 0
    ? BUILTIN_PARAMETER_CATALOG
    : { ...response, parameters: valid };
}

export function normalizeApiCatalog(
  response: ParameterCatalogApiResponse,
): ParameterCatalogResponse {
  const parameters: PX4ParameterDefinition[] = (
    Array.isArray(response.parameters) ? response.parameters : []
  ).flatMap((item) => {
    try {
      const dependencies = Array.isArray(item.dependencies)
        ? item.dependencies
            .map((dependency) => dependency?.parameter)
            .filter((name): name is string => typeof name === "string" && name !== item.name)
        : [];
      const label = {
        en: typeof item.label?.en === "string" && item.label.en.trim() !== ""
          ? item.label.en.trim()
          : item.name,
        "zh-CN": typeof item.label?.["zh-CN"] === "string" && item.label["zh-CN"].trim() !== ""
          ? item.label["zh-CN"].trim()
          : item.name,
      };
      const description = {
        en: typeof item.description?.en === "string" ? item.description.en.trim() : "",
        "zh-CN": typeof item.description?.["zh-CN"] === "string"
          ? item.description["zh-CN"].trim()
          : "",
      };
      const stringArray = (value: unknown): string[] => Array.isArray(value)
        ? [...new Set(value
            .filter((entry): entry is string => typeof entry === "string")
            .map((entry) => entry.trim())
            .filter(Boolean))]
        : [];
      const compatibility = item.compatibility && typeof item.compatibility === "object"
        ? {
            px4_versions: stringArray(item.compatibility.px4_versions),
            vehicle_types: stringArray(item.compatibility.vehicle_types),
            airframe_families: stringArray(item.compatibility.airframe_families),
          }
        : undefined;
      const choices = Array.isArray(item.choices)
        ? item.choices.flatMap((choice) => {
            if (!choice || !Number.isFinite(choice.value) || !choice.label) return [];
            const choiceLabel = typeof choice.label.en === "string" && choice.label.en.trim() !== ""
              ? {
                  en: choice.label.en.trim(),
                  "zh-CN": typeof choice.label["zh-CN"] === "string" && choice.label["zh-CN"].trim() !== ""
                    ? choice.label["zh-CN"].trim()
                    : String(choice.value),
                }
              : null;
            return choiceLabel ? [{ value: choice.value, label: choiceLabel }] : [];
          })
        : [];
      const riskNote = item.risk_note && typeof item.risk_note.en === "string"
        ? {
            en: item.risk_note.en,
            "zh-CN": typeof item.risk_note["zh-CN"] === "string"
              ? item.risk_note["zh-CN"]
              : "",
          }
        : null;
      return [{
        name: item.name,
        label: label.en,
        localized_label: label,
        group: item.group,
        description: description.en,
        localized_description: description,
        unit: typeof item.unit === "string" && item.unit !== "" ? item.unit : null,
        // The catalog wire format uses PX4's `int`; Job.parameter_space uses the
        // schema value `integer`. This is especially important for MC_AIRMODE.
        value_type: item.type === "int" || item.type === "integer" ? "integer" as const : "float" as const,
        default_value: item.default,
        absolute_min: item.hard_bounds.min,
        absolute_max: item.hard_bounds.max,
        safe_min: item.safe_bounds.min,
        safe_max: item.safe_bounds.max,
        step: item.step,
        scale: item.safe_bounds.min > 0 && item.safe_bounds.max / item.safe_bounds.min >= 100
          ? "log" as const
          : "linear" as const,
        risk: item.risk,
        requires_reboot: Boolean(item.requires_reboot),
        dependencies: [...new Set(dependencies)],
        supported_airframes: compatibility?.airframe_families.length
          ? compatibility.airframe_families
          : ALL_MULTICOPTERS,
        control_loop: typeof item.control_loop === "string" ? item.control_loop : undefined,
        axes: stringArray(item.axes),
        tuning_stage: Number.isFinite(item.tuning_stage) ? item.tuning_stage : undefined,
        expertise: ["guided", "advanced", "expert"].includes(item.expertise ?? "")
          ? item.expertise
          : undefined,
        apply_policy: ["live", "disarmed", "reboot"].includes(item.apply_policy ?? "")
          ? item.apply_policy
          : undefined,
        compatibility,
        application_interfaces: stringArray(item.application_interfaces),
        recommended_metrics: stringArray(item.recommended_metrics),
        evidence_signals: stringArray(item.evidence_signals),
        flight_modes: stringArray(item.flight_modes),
        preconditions: stringArray(item.preconditions),
        risk_note: riskNote,
        source_url: typeof item.source_url === "string" && item.source_url.trim() !== ""
          ? item.source_url
          : null,
        bounds_source: item.bounds_source === "px4" || item.bounds_source === "px4_and_dronedream_guardrail"
          ? item.bounds_source
          : undefined,
        choices,
        legacy_key: LEGACY_KEYS[item.name] ?? null,
      }];
    } catch {
      // Treat the catalog endpoint as untrusted input. A malformed row must not
      // crash the entire experiment wizard; valid rows remain usable and an
      // entirely invalid response falls back to the bundled snapshot.
      return [];
    }
  });
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
