import { describe, expect, it } from "vitest";

import {
  applyStarterExperienceTemplate,
  STARTER_EXPERIENCE_CATALOG_VERSION,
  STARTER_EXPERIENCE_TEMPLATES,
} from "../features/experiment/experienceTemplates";
import { EXPERIMENT_FORM_DEFAULTS } from "../features/experiment/formState";

describe("starter experience templates", () => {
  it("publishes immutable, uniquely versioned templates", () => {
    expect(STARTER_EXPERIENCE_CATALOG_VERSION).toBe(1);
    expect(STARTER_EXPERIENCE_TEMPLATES.map((template) => template.key)).toEqual([
      "hover-basics@1",
      "first-circle@1",
      "light-wind-circle@1",
    ]);
    expect(new Set(STARTER_EXPERIENCE_TEMPLATES.map((template) => template.key)).size).toBe(3);
    expect(Object.isFrozen(STARTER_EXPERIENCE_TEMPLATES)).toBe(true);
    expect(STARTER_EXPERIENCE_TEMPLATES.every((template) => Object.isFrozen(template.patch))).toBe(
      true,
    );
  });

  it("applies only an allowlisted patch while preserving unrelated draft fields", () => {
    const current = {
      ...EXPERIMENT_FORM_DEFAULTS,
      display_name: "keep-this-name",
      firmware_commit: "abc123",
      llm_api_key: "never-touched-by-template",
    };
    const template = STARTER_EXPERIENCE_TEMPLATES[0];

    const result = applyStarterExperienceTemplate(current, template);

    expect(result).not.toBe(current);
    expect(result.display_name).toBe("keep-this-name");
    expect(result.firmware_commit).toBe("abc123");
    expect(result.llm_api_key).toBe("never-touched-by-template");
    expect(result.track_type).toBe("hover");
    expect(result.start_x).toBe("0");
    expect(result.start_y).toBe("0");
    expect(result.altitude_m).toBe("3");
  });

  it("keeps the windy beginner experience deterministic and explicit", () => {
    const result = applyStarterExperienceTemplate(
      EXPERIMENT_FORM_DEFAULTS,
      STARTER_EXPERIENCE_TEMPLATES[2],
    );

    expect(result.track_type).toBe("circle");
    expect(result.circle_radius_m).toBe("5");
    expect(result.wind_north).toBe("2");
    expect(result.wind_search_enabled).toBe(true);
    expect(result.scenario_preset).toBe("wind");
    expect(result.simulator_backend).toBe("mock");
    expect(result.gust_enabled).toBe(false);
    expect(result.advanced_enabled).toBe(false);
    expect(result.obstacles_json).toBe("[]");
    expect(result.search_seeds).toBe("101, 202, 303");
    expect(result.optimizer_strategy).toBe("optimizer_portfolio");
  });
});
