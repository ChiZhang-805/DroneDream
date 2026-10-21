import { describe, expect, it } from "vitest";

import { runFieldTuningDemo } from "../desktop/bridge";
import { isFieldTuningDemoRequest } from "../desktop/fieldTuningRequest";
import { evaluateFieldSafety, FIELD_HARDWARE_ACTIONS } from "../field/safety";
import { runFieldBrowserFixture } from "../field/tuning";

const valid = { objective: "Inspect attitude response", maxIterations: 5, targetScore: 0.55 };

describe("Field request boundaries", () => {
  it.each([
    null, {}, { ...valid, objective: false }, { ...valid, objective: " " },
    { ...valid, maxIterations: 1 }, { ...valid, maxIterations: 9 },
    { ...valid, maxIterations: 2.5 }, { ...valid, maxIterations: "5" },
    { ...valid, targetScore: NaN }, { ...valid, targetScore: Infinity },
    { ...valid, targetScore: "0.55" }, { ...valid, targetScore: 0.1 },
    { ...valid, objective: "测".repeat(41) },
  ])("rejects malformed requests before fixture allocation or native dispatch: %j", async (request) => {
    expect(isFieldTuningDemoRequest(request)).toBe(false);
    expect(() => runFieldBrowserFixture(request as never)).toThrow("bounded contract");
    await expect(runFieldTuningDemo(request as never)).rejects.toThrow("bounded contract");
  });

  it("keeps bounded fixtures explicitly synthetic and without hardware actions", () => {
    const result = runFieldBrowserFixture(valid);
    expect(result.candidates).toHaveLength(5);
    expect(result.budget.hardwareTrials).toBe(0);
    expect(result.budget.providerRequests).toBe(0);
    expect(result.executionMode).toBe("fixture-only-no-device-io");
    expect(result.qualification.hardwareValid).toBe(false);
    expect(result.hardwareActionsPerformed).toEqual([]);
  });

  it.each([null, undefined, {}, { state: "toString" }, { state: "offline", quorum: null }])(
    "keeps malformed observations denied without throwing: %j", (observation) => {
      const decision = evaluateFieldSafety(observation as never);
      expect(decision.actions).toEqual(Object.fromEntries(FIELD_HARDWARE_ACTIONS.map((key) => [key, false])));
      expect(decision.threeLayerQuorum).toBe("missing");
      expect(decision.blockers).not.toContain(undefined);
    },
  );
});
