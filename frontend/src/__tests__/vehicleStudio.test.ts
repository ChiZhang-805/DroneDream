import { render, screen, within } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { buildVehiclePreviewGeometry } from "../features/vehicleStudio/preview";
import { I18nProvider } from "../i18n/I18nProvider";
import { VehicleStudio } from "../pages/VehicleStudio";
import {
  buildVehiclePackDraft,
  canonicalJson,
  generateGazeboSdf,
  inspectVehiclePackDraftForEdition,
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

vi.mock("../features/auth/AuthContext", () => ({
  useAuth: () => ({ account: { id: "vehicle-studio-test-owner" } }),
}));

vi.mock("../components/VehicleModelPreview3D", () => ({
  VehicleModelPreview3D: () => createElement("div", { "data-testid": "vehicle-preview" }),
}));

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
  };
}

describe("Universal Vehicle Studio contract", () => {
  it("renders independently authored Chinese modeling and option copy", () => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    render(createElement(I18nProvider, null, createElement(VehicleStudio)));

    expect(screen.getByRole("heading", { name: "无人机建模工作室" })).toBeVisible();
    const vehicleClass = screen.getByRole("combobox", { name: "机型类别" });
    expect(within(vehicleClass).getByRole("option", { name: "小型多旋翼" }))
      .toBeInTheDocument();
    expect(within(vehicleClass).getByRole("option", { name: "中型多旋翼" }))
      .toBeInTheDocument();
    expect(within(vehicleClass).getByRole("option", { name: "研究级多旋翼" }))
      .toBeInTheDocument();
  });

  it("builds normalized three-dimensional geometry for every supported rotor layout", () => {
    for (const motorCount of [4, 6, 8] as const) {
      const draft = createVehicleModelDraft();
      draft.propulsion.motorCount = motorCount;
      const geometry = buildVehiclePreviewGeometry(draft);
      expect(geometry.rotors).toHaveLength(motorCount);
      expect(Math.max(...geometry.rotors.map((rotor) => Math.hypot(rotor.x, rotor.z))))
        .toBeLessThan(2.35);
      expect(geometry.body.x).toBeGreaterThan(0);
      expect(geometry.body.y).toBeGreaterThan(0);
      expect(geometry.body.z).toBeGreaterThan(0);
    }
  });

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

  it("freezes a model snapshot before asynchronous artifact hashing", async () => {
    const draft = createVehicleModelDraft();
    const originalName = draft.name;
    const pending = buildVehiclePackDraft(draft);
    draft.name = "Mutated while hashing";
    draft.body.massKg = 900;
    const envelope = await pending;
    expect(envelope.payload.model.name).toBe(originalName);
    expect(envelope.payload.model.body.massKg).toBe(1.5);
    await expect(verifyVehiclePackDraft(envelope)).resolves.toBeDefined();
  });

  it("provides a fail-closed receiver inspection for the addressed Edition only", async () => {
    const draft = createVehicleModelDraft();
    draft.targetEditions = ["sim", "lab"];
    const envelope = await buildVehiclePackDraft(draft);
    await expect(inspectVehiclePackDraftForEdition(envelope, "sim")).resolves.toMatchObject({
      targetEdition: "sim",
      decision: "verified-draft-only",
      receiverInspectionIsAuthority: false,
      promotionAllowed: false,
      grantsSimulationExecution: false,
      grantsHardwareAuthority: false,
    });
    await expect(inspectVehiclePackDraftForEdition(envelope, "field"))
      .rejects.toThrow(/not addressed/);
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

  it("bounds repeated model fields and imported artifact size", async () => {
    const duplicateSensors = createVehicleModelDraft();
    duplicateSensors.sensors.push({ ...duplicateSensors.sensors[0] });
    expect(validateVehicleModel(duplicateSensors).map((issue) => issue.code))
      .toContain("duplicate-sensor");
    await expect(buildVehiclePackDraft(duplicateSensors)).rejects.toThrow(/validation issue/);

    const oversized = await buildVehiclePackDraft(createVehicleModelDraft());
    oversized.payload.artifacts[1].content = "x".repeat(1_048_577);
    oversized.payload.artifacts[1].sha256 = await sha256Text(oversized.payload.artifacts[1].content);
    oversized.integrity.payloadSha256 = await sha256Text(canonicalJson(oversized.payload));
    await expect(verifyVehiclePackDraft(oversized)).rejects.toThrow(/identity is invalid/);
  });

  it("allows redundant sensor types while rejecting duplicate sensor identities and extreme geometry", async () => {
    const redundantImu = createVehicleModelDraft();
    redundantImu.sensors.push({
      id: crypto.randomUUID(),
      type: "imu",
      model: "Backup IMU",
      enabled: true,
    });
    expect(validateVehicleModel(redundantImu)).toEqual([]);

    const duplicateId = structuredClone(redundantImu);
    duplicateId.sensors[3].id = duplicateId.sensors[0].id;
    expect(validateVehicleModel(duplicateId).map((issue) => issue.code))
      .toContain("duplicate-sensor");

    const extreme = createVehicleModelDraft();
    extreme.body.lengthM = 1e200;
    expect(validateVehicleModel(extreme).map((issue) => issue.code))
      .toContain("bounded-positive-number");
    await expect(buildVehiclePackDraft(extreme)).rejects.toThrow(/validation issue/);
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

  it("caps each owner's model library instead of growing local storage without a bound", () => {
    const storage = memoryStorage();
    for (let index = 0; index < 55; index += 1) {
      const draft = createVehicleModelDraft();
      draft.draftId = `${index.toString(16).padStart(8, "0")}-0000-4000-8000-000000000000`;
      saveVehicleModel("owner-a", draft, storage);
    }
    expect(loadVehicleModels("owner-a", storage)).toHaveLength(50);
  });

  it("bounds, sorts, and de-duplicates untrusted local revision records on load", () => {
    const storage = memoryStorage();
    const draft = createVehicleModelDraft();
    const older = structuredClone(draft);
    older.revision = 1;
    const newer = structuredClone(draft);
    newer.revision = 2;
    storage.setItem("dronedream:vehicle-studio:v1:owner-a", JSON.stringify([
      null,
      { draftId: draft.draftId, revisions: [older, newer] },
      { draftId: draft.draftId, revisions: [older, older] },
    ]));
    const loaded = loadVehicleModels("owner-a", storage);
    expect(loaded).toHaveLength(1);
    expect(loaded[0].revisions.map((revision) => revision.revision)).toEqual([2, 1]);
  });
});
