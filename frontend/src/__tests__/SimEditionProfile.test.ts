import { describe, expect, it } from "vitest";

import {
  SIM_EDITION,
  assertSimCapability,
  lockDistributionSelectionToSim,
  simCapabilityDecision,
} from "../editions/sim/profile";

describe("DroneDream · SIM edition profile", () => {
  it("allows only the explicit simulation capability whitelist", () => {
    for (const capability of SIM_EDITION.allowedCapabilities) {
      expect(simCapabilityDecision(capability)).toBe("allow");
      expect(() => assertSimCapability(capability)).not.toThrow();
    }

    for (const capability of SIM_EDITION.forbiddenCapabilities) {
      expect(simCapabilityDecision(capability)).toBe("deny");
      expect(() => assertSimCapability(capability)).toThrow(
        `DroneDream · SIM denies capability: ${capability}`,
      );
    }
  });

  it("denies unknown capabilities by default", () => {
    expect(simCapabilityDecision("hardware.new-command")).toBe("deny");
    expect(simCapabilityDecision("lab.mode.enter")).toBe("deny");
    expect(simCapabilityDecision("field.mode.enter")).toBe("deny");
  });

  it("removes hardware identity from a valid Field distribution draft", () => {
    expect(lockDistributionSelectionToSim({
      schemaVersion: 1,
      editionId: "field",
      region: "cn",
      vehiclePackId: "amovlab-mfp450-pixhawk6c",
      controllerKey: "Holybro::Pixhawk 6C",
      optionalModules: ["qgroundcontrol-external"],
    })).toEqual({
      schemaVersion: 1,
      editionId: "sim",
      region: "cn",
      vehiclePackId: "px4-gazebo-x500-reference",
      controllerKey: null,
      optionalModules: [],
    });
  });
});
