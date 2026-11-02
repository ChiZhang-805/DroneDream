import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  evaluateLabCalibrationCycle,
  type LabCalibrationCycleRequest,
} from "../../desktop/bridge";

const request: LabCalibrationCycleRequest = {
  schemaVersion: 1,
  jobId: "lab-job-001",
  cycleOrdinal: 1,
  commonCoreCommit: "e374d3f8d96b1265fcdb06864208b676566e94d9",
  editionManifestSha256: "1".repeat(64),
  vehiclePackId: "px4-gazebo-x500-reference",
  controllerIdentity: "px4-autopilot",
  firmwareIdentity: "px4-v1.16.0",
  simulationReceiptSha256: "2".repeat(64),
  realObservationReceiptSha256: "3".repeat(64),
  parameterCandidateSha256: "4".repeat(64),
  objectiveContractSha256: "5".repeat(64),
  constraintContractSha256: "6".repeat(64),
  holdoutContractSha256: "7".repeat(64),
  metricNormalizationReceiptSha256: "8".repeat(64),
  objective: "tracking",
  tolerancePercent: 10,
  cycleBudget: 4,
  simulation: { trackingRmseM: 0.2, maxErrorM: 0.4, energyWh: 20, overshootCount: 2 },
  realObservation: { trackingRmseM: 0.3, maxErrorM: 0.5, energyWh: 24, overshootCount: 3 },
  independentHoldoutPassed: false,
};

function receipt() {
  return {
    schemaVersion: 1,
    kind: "dronedream-lab-sim-real-calibration-receipt",
    editionId: "lab",
    productSource: "a".repeat(40),
    requestSha256: "b".repeat(64),
    objectiveContractSha256: "5".repeat(64),
    constraintContractSha256: "6".repeat(64),
    holdoutContractSha256: "7".repeat(64),
    metricNormalizationReceiptSha256: "8".repeat(64),
    aggregateGapPercent: 24,
    gapWithinTolerance: false,
    nextAction: "revise-model-and-resimulate",
    qualificationDecision: "deny",
    trusted: false,
    blockers: ["lab.registry.zero-validated-packs"],
    validatedVehiclePackCount: 0,
    providerRequests: 0,
    deviceOpenAttempts: 0,
    hardwareWriteAttempts: 0,
    armAttempts: 0,
    flightAttempts: 0,
    hardwareAuthority: false,
    receiptSha256: "c".repeat(64),
  };
}

describe("Lab native calibration bridge", () => {
  beforeEach(() => {
    delete window.__TAURI__;
  });

  it("accepts a source-bound denied receipt", async () => {
    const invoke = vi.fn(async () => receipt());
    window.__TAURI__ = { core: { invoke } };

    await expect(evaluateLabCalibrationCycle(request)).resolves.toMatchObject({
      editionId: "lab",
      qualificationDecision: "deny",
      validatedVehiclePackCount: 0,
      hardwareAuthority: false,
    });
    expect(invoke).toHaveBeenCalledWith("evaluate_lab_calibration_cycle", { request });
  });

  it("rejects any native authority or execution drift", async () => {
    const invoke = vi.fn(async () => ({ ...receipt(), hardwareWriteAttempts: 1 }));
    window.__TAURI__ = { core: { invoke } };

    await expect(evaluateLabCalibrationCycle(request)).rejects.toThrow(
      /hardwareWriteAttempts/,
    );
  });

  it("rejects an incomplete evidence-binding hash", async () => {
    const invoke = vi.fn(async () => ({
      ...receipt(),
      holdoutContractSha256: "missing",
    }));
    window.__TAURI__ = { core: { invoke } };

    await expect(evaluateLabCalibrationCycle(request)).rejects.toThrow(
      /source or hash is invalid/,
    );
  });
});
