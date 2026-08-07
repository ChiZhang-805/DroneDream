import { describe, expect, it, vi } from "vitest";

import {
  buildVehiclePackDraft,
  canonicalJson,
  generateGazeboSdf,
  sha256Text,
  verifyVehiclePackDraft,
} from "../features/vehicleStudio/pack";
import {
  createVehicleModelDraft,
  validateVehicleModel,
} from "../features/vehicleStudio/model";
import {
  loadVehicleModels,
  nextVehicleRevision,
  removeVehicleModel,
  restoreVehicleRevision,
  saveVehicleModel,
} from "../features/vehicleStudio/storage";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
  };
}

describe("Universal Vehicle Studio contract", () => {
  it("creates a valid custom vehicle and deterministic generated simulation geometry", () => {
    vi.spyOn(crypto, "randomUUID")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000001")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000002")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000003")
      .mockReturnValueOnce("00000000-0000-4000-8000-000000000004");
    const draft = createVehicleModelDraft(new Date("2026-08-07T00:00:00.000Z"));
    expect(validateVehicleModel(draft)).toEqual([]);
    const sdf = generateGazeboSdf(draft);
    expect(sdf).toContain('<sdf version="1.10">');
    expect(sdf.match(/<link name="rotor_/g)).toHaveLength(4);
    expect(sdf.match(/type="fixed"/g)).toHaveLength(4);
    expect(sdf).toContain('<model name="custom-quadrotor">');
    vi.restoreAllMocks();
  });

  it("blocks unsafe or incomplete model drafts before export", async () => {
    const draft = createVehicleModelDraft();
    draft.body.massKg = 20;
    draft.sensors = draft.sensors.map((sensor) => ({ ...sensor, enabled: false }));
    draft.targetEditions = [];
    const codes = validateVehicleModel(draft).map((issue) => issue.code);
    expect(codes).toContain("insufficient-thrust-margin");
    expect(codes).toContain("imu-required");
    expect(codes).toContain("target-required");
    await expect(buildVehiclePackDraft(draft)).rejects.toThrow(/validation issue/);
  });

  it("exports and verifies a hash-bound draft without granting execution authority", async () => {
    const draft = createVehicleModelDraft();
    draft.targetEditions = ["field", "sim", "lab"];
    const envelope = await buildVehiclePackDraft(draft);
    const verified = await verifyVehiclePackDraft(envelope);
    expect(verified.payload.packId).toMatch(/^custom-custom-quadrotor-[0-9a-f]{8}$/);
    expect(verified.payload.targetEditions).toEqual(["field", "lab", "sim"]);
    expect(verified.payload.authority).toEqual({
      draftOnly: true,
      signed: false,
      validated: false,
      frontendIsAuthority: false,
      grantsSimulationExecution: false,
      grantsHardwareAuthority: false,
    });
    expect(verified.payload.artifacts.map((item) => item.path)).toEqual([
      "model/vehicle-model.json",
      "model/model.sdf",
    ]);
  });

  it("rejects payload, artifact, compatibility, target, authority, and unknown-field tampering", async () => {
    const envelope = await buildVehiclePackDraft(createVehicleModelDraft());
    const variants: unknown[] = [];

    const artifactTamper = structuredClone(envelope);
    artifactTamper.payload.artifacts[1].content += "<!-- tampered -->";
    variants.push(artifactTamper);

    const authorityTamper = structuredClone(envelope);
    (authorityTamper.payload.authority as { grantsHardwareAuthority: boolean })
      .grantsHardwareAuthority = true;
    variants.push(authorityTamper);

    const compatibilityTamper = structuredClone(envelope);
    compatibilityTamper.payload.compatibility.controllerModel = "Different controller";
    variants.push(compatibilityTamper);

    const targetTamper = structuredClone(envelope);
    targetTamper.payload.targetEditions = ["field"];
    variants.push(targetTamper);

    const unknownField = structuredClone(envelope) as unknown as Record<string, unknown>;
    unknownField.elevated = true;
    variants.push(unknownField);

    for (const variant of variants) {
      await expect(verifyVehiclePackDraft(variant)).rejects.toThrow();
    }
  });

  it("rejects self-consistent envelopes whose identity or artifacts drift from the model", async () => {
    const rehash = async (envelope: Awaited<ReturnType<typeof buildVehiclePackDraft>>) => {
      for (const item of envelope.payload.artifacts) item.sha256 = await sha256Text(item.content);
      envelope.integrity.payloadSha256 = await sha256Text(canonicalJson(envelope.payload));
      return envelope;
    };
    const identityDrift = structuredClone(await buildVehiclePackDraft(createVehicleModelDraft()));
    identityDrift.payload.packId = `custom-forged-${identityDrift.payload.model.draftId.slice(0, 8)}`;
    await expect(verifyVehiclePackDraft(await rehash(identityDrift))).rejects.toThrow(/name or version/);

    const artifactDrift = structuredClone(await buildVehiclePackDraft(createVehicleModelDraft()));
    artifactDrift.payload.artifacts.find((item) => item.path === "model/model.sdf")!.content += "<!-- alternate model -->";
    await expect(verifyVehiclePackDraft(await rehash(artifactDrift))).rejects.toThrow(/drifted/);
  });

  it("keeps local revisions owner-scoped and restores history as a new revision", () => {
    const storage = memoryStorage();
    const original = createVehicleModelDraft(new Date("2026-08-07T01:00:00.000Z"));
    saveVehicleModel("owner-a", original, storage);
    const second = nextVehicleRevision(original, new Date("2026-08-07T02:00:00.000Z"));
    second.name = "Revision two";
    const models = saveVehicleModel("owner-a", second, storage);

    expect(models[0].revisions.map((item) => item.revision)).toEqual([2, 1]);
    expect(loadVehicleModels("owner-b", storage)).toEqual([]);

    const restored = restoreVehicleRevision(original, 2, new Date("2026-08-07T03:00:00.000Z"));
    expect(restored.revision).toBe(3);
    expect(restored.draftId).toBe(original.draftId);
    expect(restored.updatedAt).toBe("2026-08-07T03:00:00.000Z");
    expect(removeVehicleModel("owner-a", original.draftId, storage)).toEqual([]);
  });

  it("drops malformed local records instead of allowing them to crash the editor", () => {
    const storage = memoryStorage();
    storage.setItem("dronedream:vehicle-studio:v1:owner-a", JSON.stringify([
      { draftId: "broken", revisions: [{ schemaVersion: 1 }] },
      { draftId: "empty", revisions: [] },
    ]));
    expect(loadVehicleModels("owner-a", storage)).toEqual([]);
  });
});
