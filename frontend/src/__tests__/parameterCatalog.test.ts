import { describe, expect, it } from "vitest";

import {
  BUILTIN_PARAMETER_CATALOG,
  createParameterSelections,
  normalizeApiCatalog,
  selectedParameters,
} from "../features/experiment/parameterCatalog";

describe("parameter catalog compatibility", () => {
  it("normalizes the backend catalog into the wizard view model", () => {
    const result = normalizeApiCatalog({
      catalog_version: "px4-v1",
      source: "PX4 snapshot",
      px4_version: "v1.16",
      supported_px4_versions: ["v1.16"],
      vehicle_type: "multicopter",
      parameter_count: 2,
      parameters: [
        {
          name: "MPC_XY_P",
          type: "float",
          unit: "1/s",
          hard_bounds: { min: 0, max: 2 },
          safe_bounds: { min: 0.6, max: 1.3 },
          step: 0.1,
          default: 0.95,
          group: "xy_position_velocity",
          risk: "medium",
          requires_reboot: false,
          label: { en: "Horizontal position P", "zh-CN": "水平位置 P" },
          description: { en: "Position gain", "zh-CN": "位置增益" },
          dependencies: [
            {
              kind: "recommended_with",
              parameter: "MPC_XY_VEL_P_ACC",
              description: { en: "Tune together", "zh-CN": "联动调节" },
            },
          ],
        },
        {
          name: "MC_AIRMODE",
          type: "int",
          unit: "",
          hard_bounds: { min: 0, max: 2 },
          safe_bounds: { min: 0, max: 2 },
          step: 1,
          default: 0,
          group: "motion_limits",
          risk: "high",
          requires_reboot: false,
          label: { en: "Multicopter air-mode", "zh-CN": "多旋翼空中模式" },
          description: { en: "Mixer policy", "zh-CN": "混控策略" },
          dependencies: [],
        },
      ],
    });

    expect(result.source).toBe("backend");
    expect(result.catalog_version).toBe("px4-v1");
    expect(result.parameters[0]).toMatchObject({
      name: "MPC_XY_P",
      label: "Horizontal position P",
      safe_min: 0.6,
      safe_max: 1.3,
      legacy_key: "kp_xy",
      dependencies: ["MPC_XY_VEL_P_ACC"],
      localized_label: { en: "Horizontal position P", "zh-CN": "水平位置 P" },
    });
    expect(result.parameters[1]).toMatchObject({
      name: "MC_AIRMODE",
      value_type: "integer",
      step: 1,
    });
  });

  it("creates mode presets and emits only checked dimensions", () => {
    expect(BUILTIN_PARAMETER_CATALOG.parameters).toHaveLength(28);
    expect(
      BUILTIN_PARAMETER_CATALOG.parameters.find((item) => item.name === "MC_AIRMODE"),
    ).toMatchObject({ value_type: "integer", safe_min: 0, safe_max: 2 });
    const selections = createParameterSelections(
      BUILTIN_PARAMETER_CATALOG.parameters,
      "basic",
    );
    const selected = selectedParameters(selections);
    expect(selected.map((item) => item.name)).toEqual([
      "MPC_XY_P",
      "MPC_XY_VEL_MAX",
      "MPC_ACC_HOR",
    ]);
    expect(selected[0]).not.toHaveProperty("selected");
  });
});
