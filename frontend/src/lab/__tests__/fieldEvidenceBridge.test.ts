import { describe, expect, it } from "vitest";

import fieldFixture from "../__fixtures__/field-harness-receipt.fake.json";
import simFixture from "../__fixtures__/sim-qualification-bridge.fake.json";
import { parseLabEvidencePreview } from "../evidencePreview";
import {
  FIELD_PRODUCT_SOURCE,
  FieldEvidenceBridgeError,
  canonicalizeJson,
  evaluateSimFieldBridge,
  parseFieldHarnessReceipt,
  sha256Text,
} from "../fieldEvidenceBridge";

function fieldSource(value: unknown = fieldFixture): string {
  return JSON.stringify(value);
}

async function rehashReceipt(value: typeof fieldFixture): Promise<typeof fieldFixture> {
  const receipt = structuredClone(value);
  receipt.receiptSha256 = "";
  receipt.receiptSha256 = await sha256Text(canonicalizeJson(receipt));
  return receipt;
}

describe("Lab Field evidence bridge", () => {
  it("verifies the exact Field receipt, JCS, selected candidate, and holdout", async () => {
    const receipt = await parseFieldHarnessReceipt("field.json", fieldSource());

    expect(receipt.sourceCommit).toBe(FIELD_PRODUCT_SOURCE);
    expect(receipt.receiptIntegrityVerified).toBe(true);
    expect(receipt.selectedCandidateSha256).toBe(
      "d4bb303ead211a98d99d03e69399fe8f604d640ffe837b974c9533065e5ebf23",
    );
    expect(receipt.holdoutTrialId).toBe("field-holdout-001");
    expect(receipt.recordedEvidencePassed).toBe(true);
    expect(receipt.hardwareValid).toBe(false);
    expect(receipt.hardwareAuthority).toBe(false);
    expect(receipt.hardwareActionsPerformed).toBe(0);
  });

  it("joins matching SIM and Field identities but keeps calibration and authority denied", async () => {
    const simulation = parseLabEvidencePreview("sim.json", JSON.stringify(simFixture));
    const field = await parseFieldHarnessReceipt("field.json", fieldSource());
    const decision = evaluateSimFieldBridge(simulation, field);

    expect(decision.state).toBe("awaiting-sim-donor-and-metrics");
    expect(decision.identityMatched).toBe(false);
    expect(decision.candidateLineageMatched).toBe(true);
    expect(decision.calibrationReady).toBe(false);
    expect(decision.qualificationDecision).toBe("deny");
    expect(decision.hardwareAuthority).toBe(false);
    expect(decision.blockers).toContain("lab.sim-donor.not-accepted");
    expect(decision.blockers).toContain("lab.job-binding.missing");
    expect(decision.blockers).toContain("lab.metric-normalization-receipt.missing");
    expect(decision.bindings.fieldSnapshotSha256).toBe(field.snapshotSha256);
  });

  it("denies candidate, Vehicle Pack, common-core, and replay mismatches", async () => {
    const field = await parseFieldHarnessReceipt("field.json", fieldSource());
    const simulation = parseLabEvidencePreview("sim.json", JSON.stringify(simFixture));

    const candidateMismatch = {
      ...simulation,
      parameterCandidateHash: "0".repeat(64),
    };
    expect(evaluateSimFieldBridge(candidateMismatch, field).blockers)
      .toContain("lab.parameter-candidate.mismatch");

    const packMismatch = { ...simulation, vehiclePackId: "another-pack" };
    expect(evaluateSimFieldBridge(packMismatch, field).blockers)
      .toContain("lab.vehicle-pack.mismatch");

    const coreMismatch = { ...simulation, commonCoreCommit: "0".repeat(40) };
    expect(evaluateSimFieldBridge(coreMismatch, field).blockers)
      .toContain("lab.common-core.mismatch");

    expect(evaluateSimFieldBridge(simulation, field, new Set([field.receiptSha256])).blockers)
      .toContain("lab.field-evidence.replay-denied");
  });

  it("rejects source drift, JCS tampering, unsafe actions, invalid holdout, and sensitive fields", async () => {
    await expect(parseFieldHarnessReceipt("field.json", fieldSource({
      ...fieldFixture,
      sourceCommit: "0".repeat(40),
    }))).rejects.toThrow(/accepted product source/);

    await expect(parseFieldHarnessReceipt("field.json", fieldSource({
      ...fieldFixture,
      jobName: "tampered but otherwise valid",
    }))).rejects.toThrow(/JCS integrity/);

    await expect(parseFieldHarnessReceipt("field.json", fieldSource({
      ...fieldFixture,
      hardwareWriteAttempts: 1,
    }))).rejects.toThrow(/execution attempt/);

    const invalidHoldout = structuredClone(fieldFixture);
    invalidHoldout.trials[2].parameters = structuredClone(invalidHoldout.trials[1].parameters);
    invalidHoldout.trials[2].candidateSha256 = invalidHoldout.trials[1].candidateSha256;
    await expect(parseFieldHarnessReceipt("field.json", fieldSource(invalidHoldout)))
      .rejects.toThrow(/holdout or best-candidate ordering/);

    await expect(parseFieldHarnessReceipt("field.json", fieldSource({
      ...fieldFixture,
      apiKey: "must-never-be-read",
    }))).rejects.toThrow(/Sensitive field/);
  });

  it("rejects JCS-valid receipts with impossible Field scoring or budget semantics", async () => {
    const impossibleScore = structuredClone(fieldFixture);
    impossibleScore.trials[0].score = 0.31;
    await expect(parseFieldHarnessReceipt(
      "field.json",
      fieldSource(await rehashReceipt(impossibleScore)),
    )).rejects.toThrow(/trial semantics are invalid/);

    const impossibleBudget = structuredClone(fieldFixture);
    impossibleBudget.budget.remainingIterations = 1;
    await expect(parseFieldHarnessReceipt(
      "field.json",
      fieldSource(await rehashReceipt(impossibleBudget)),
    )).rejects.toThrow(/trial budget is invalid/);
  });

  it("reports missing evidence without creating a partial allow state", async () => {
    const field = await parseFieldHarnessReceipt("field.json", fieldSource());
    expect(evaluateSimFieldBridge(null, field)).toMatchObject({
      state: "waiting-for-evidence",
      identityMatched: false,
      candidateLineageMatched: false,
      calibrationReady: false,
      qualificationDecision: "deny",
      hardwareAuthority: false,
      blockers: ["lab.sim-evidence.missing"],
    });
  });

  it("uses a dedicated typed error for malformed receipts", async () => {
    await expect(parseFieldHarnessReceipt("field.json", "{}"))
      .rejects.toBeInstanceOf(FieldEvidenceBridgeError);
  });
});
