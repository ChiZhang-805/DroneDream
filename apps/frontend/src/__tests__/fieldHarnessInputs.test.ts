import { describe, expect, it } from "vitest";

import type { FieldHarnessJobRequest } from "../desktop/bridge";
import { validateFieldHarnessRequest } from "../desktop/fieldHarnessRequest";

function request(): FieldHarnessJobRequest {
  // Synthetic independent hashes exercise request shape only, not measured-data authenticity.
  return {
    jobName: "Evidence", objective: "Reduce tracking error", deviceObservationId: "observed",
    vehiclePackId: "pack", controllerId: "controller", firmwareVersion: "firmware", adapterId: "adapter",
    observationSha256: "a".repeat(64), snapshotSha256: "b".repeat(64),
    targetScore: 0.5, maxIterations: 4,
    parameterBounds: { P: { min: 1, max: 5, maxStep: 0.2 } },
    trials: [0, 1, 2].map((index) => ({
      trialId: `trial-${index}`, telemetrySha256: String(index).repeat(64), parameters: { P: 3 },
      independentHoldout: index === 2,
      metrics: { trackingError: 0.2, overshootPercent: 3, controlEffort: 0.4,
        constraintViolations: 0, emergencyInterventions: 0 },
    })),
  };
}

describe("Recorded Field request validation", () => {
  it("accepts bounded trials with one distinct final holdout", () => {
    expect(() => validateFieldHarnessRequest(request())).not.toThrow();
  });

  it("does not call reused telemetry an independent holdout", () => {
    const value = request();
    value.trials[2].telemetrySha256 = value.trials[0].telemetrySha256;
    expect(() => validateFieldHarnessRequest(value)).toThrow("independent");
  });

  it("rejects duplicate trial identities", () => {
    const value = request();
    value.trials[1].trialId = value.trials[0].trialId;
    expect(() => validateFieldHarnessRequest(value)).toThrow("identity");
  });

  it("rejects an overflowing parameter span even when its endpoints are finite", () => {
    const value = request();
    value.parameterBounds.P = { min: -Number.MAX_VALUE, max: Number.MAX_VALUE, maxStep: 1 };
    expect(() => validateFieldHarnessRequest(value)).toThrow("bound");
  });

  it.each([
    { jobName: "测".repeat(27) }, { jobName: "name\nwith control" },
    { deviceObservationId: "a".repeat(161) },
    { parameterBounds: { P: { min: -1_000_001, max: 5, maxStep: 0.2 } } },
    { parameterBounds: { P: { min: 1, max: 5, maxStep: 0.000_000_1 } } },
  ])("matches native string/numeric limits: %j", (drift) => {
    expect(() => validateFieldHarnessRequest({ ...request(), ...drift })).toThrow();
  });

  it("does not silently exceed the operator's training budget", () => {
    const value = request();
    value.maxIterations = 2;
    value.trials.splice(1, 0, { ...value.trials[0], trialId: "extra" });
    expect(() => validateFieldHarnessRequest(value)).toThrow("contract");
  });

  it.each(["constraintViolations", "emergencyInterventions"] as const)(
    "matches the native unsigned 16-bit counter: %s", (name) => {
      const value = request();
      value.trials[0].metrics[name] = 65_536;
      expect(() => validateFieldHarnessRequest(value)).toThrow("metrics");
    },
  );

  it.each([null, {}, [], { ...request(), trials: null }, { ...request(), parameterBounds: null }])(
    "rejects malformed roots without a TypeError: %j", (value) => {
      expect(() => validateFieldHarnessRequest(value as never)).toThrow("contract");
    },
  );

  it.each(["false", 0, null, undefined])("requires a literal holdout boolean: %j", (bad) => {
    const value = request();
    value.trials[0] = { ...value.trials[0], independentHoldout: bad } as never;
    expect(() => validateFieldHarnessRequest(value)).toThrow("identity");
  });
});
