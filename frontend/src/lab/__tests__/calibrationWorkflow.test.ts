import { describe, expect, it } from "vitest";

import fixture from "../__fixtures__/calibration-input.fake.json";
import {
  LabCalibrationInputError,
  analyzeLabCalibration,
  buildLabCalibrationDraftReceipt,
  parseLabCalibrationInput,
  serializeLabCalibrationDraftReceipt,
} from "../calibrationWorkflow";

describe("Lab calibration workflow", () => {
  it("binds sim and real evidence into one fail-closed job", () => {
    const input = parseLabCalibrationInput("cycle.json", JSON.stringify(fixture));
    const analysis = analyzeLabCalibration(input, "tracking", 15, 4);

    expect(input.jobId).toBe("lab_job_fixture_001");
    expect(input.editionManifestSha256).toBe(
      "96953004774b7044129c491d3ff251213d4c7bf09d188d3d3c00724343aebf3c",
    );
    expect(input.grantsHardwareAuthority).toBe(false);
    expect(analysis.aggregateGapPercent).toBeGreaterThan(15);
    expect(analysis.nextAction).toBe("revise-model-and-resimulate");
    expect(analysis.qualificationDecision).toBe("deny");
    expect(analysis.grantsHardwareAuthority).toBe(false);
    expect(analysis.stages.find((stage) => stage.id === "independent-holdout")?.status)
      .toBe("blocked");
  });

  it("allows holdout readiness but never qualification when gaps are within tolerance", () => {
    const closeFixture = {
      ...fixture,
      realObservation: {
        trackingRmseM: 0.121,
        maxErrorM: 0.312,
        energyWh: 18.5,
        overshootCount: 1,
      },
    };
    const input = parseLabCalibrationInput("cycle.json", JSON.stringify(closeFixture));
    const analysis = analyzeLabCalibration(input, "robustness", 5, 6);

    expect(analysis.gapWithinTolerance).toBe(true);
    expect(analysis.nextAction).toBe("await-independent-holdout");
    expect(analysis.qualificationReason).toBe("zero-validated-vehicle-packs");
    expect(analysis.stages.find((stage) => stage.id === "independent-holdout")?.status)
      .toBe("ready");
    expect(analysis.stages.find((stage) => stage.id === "field-handoff")?.status)
      .toBe("blocked");
  });

  it("exports a canonical draft that explicitly denies authority", () => {
    const input = parseLabCalibrationInput("cycle.json", JSON.stringify(fixture));
    const analysis = analyzeLabCalibration(input, "tracking", 15, 4);
    const receipt = buildLabCalibrationDraftReceipt(input, analysis);
    const serialized = serializeLabCalibrationDraftReceipt(input, analysis);

    expect(receipt).toMatchObject({
      trusted: false,
      source: { editionManifestSha256: input.editionManifestSha256 },
      qualification: { decision: "deny", validatedVehiclePackCount: 0 },
      authority: { presentationOnly: true, grantsHardwareAuthority: false },
    });
    expect(serialized.endsWith("\n")).toBe(true);
    expect(serializeLabCalibrationDraftReceipt(input, analysis)).toBe(serialized);
  });

  it("rejects sensitive fields, authority escalation, invalid hashes, and unsafe budgets", () => {
    expect(() => parseLabCalibrationInput("cycle.json", JSON.stringify({
      ...fixture,
      apiKey: "must-not-be-read",
    }))).toThrow(/Sensitive field/);

    expect(() => parseLabCalibrationInput("cycle.json", JSON.stringify({
      ...fixture,
      authority: { decision: "allow", grantsHardwareAuthority: true },
    }))).toThrow(/must not grant authority/);

    expect(() => parseLabCalibrationInput("cycle.json", JSON.stringify({
      ...fixture,
      evidence: { ...fixture.evidence, simulationReceiptHash: "bad" },
    }))).toThrow(/SHA-256/);

    expect(() => parseLabCalibrationInput("cycle.json", JSON.stringify({
      ...fixture,
      undeclaredEvidence: "not-supported",
    }))).toThrow(/fields do not match/);

    expect(() => parseLabCalibrationInput("cycle.json", JSON.stringify({
      ...fixture,
      source: {
        kind: fixture.source.kind,
        commonCoreCommit: fixture.source.commonCoreCommit,
      },
    }))).toThrow(/fields do not match/);

    const input = parseLabCalibrationInput("cycle.json", JSON.stringify(fixture));
    expect(() => analyzeLabCalibration(input, "tracking", 0, 4))
      .toThrow(LabCalibrationInputError);
    expect(() => analyzeLabCalibration(input, "tracking", 15, 13))
      .toThrow(/between 1 and 12/);
  });
});
