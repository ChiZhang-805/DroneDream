import { describe, expect, it } from "vitest";

import fakeReceipt from "../__fixtures__/sim-qualification-receipt.fake.json";
import {
  LabEvidencePreviewError,
  MAX_LAB_EVIDENCE_BYTES,
  parseLabEvidencePreview,
} from "../evidencePreview";

describe("Lab evidence preview", () => {
  it("previews bounded simulation evidence without granting authority", () => {
    const preview = parseLabEvidencePreview(
      "qualification.json",
      JSON.stringify(fakeReceipt),
    );

    expect(preview.sourceEdition).toBe("sim");
    expect(preview.vehiclePackId).toBe("px4-gazebo-x500-reference");
    expect(preview.parameters).toEqual([
      { name: "MPC_XY_P", value: 0.95, unit: "ratio" },
      { name: "MPC_Z_P", value: 1.1, unit: "ratio" },
    ]);
    expect(preview.previewOnly).toBe(true);
    expect(preview.authorityDecision).toBe("deny");
  });

  it("rejects unsupported sources and malformed parameter candidates", () => {
    expect(() => parseLabEvidencePreview("receipt.json", JSON.stringify({
      ...fakeReceipt,
      source: { ...fakeReceipt.source, editionId: "field" },
    }))).toThrowError(LabEvidencePreviewError);

    expect(() => parseLabEvidencePreview("receipt.json", JSON.stringify({
      ...fakeReceipt,
      parameterCandidate: {
        ...fakeReceipt.parameterCandidate,
        parameters: [{ name: "bad-name", value: 1 }],
      },
    }))).toThrow(/name is unsupported/);
  });

  it("rejects oversized or non-JSON evidence before preview", () => {
    expect(() => parseLabEvidencePreview("receipt.json", "x".repeat(
      MAX_LAB_EVIDENCE_BYTES + 1,
    ))).toThrow(/256 KiB/);
    expect(() => parseLabEvidencePreview("receipt.json", "not-json"))
      .toThrow(/not valid JSON/);
  });
});
