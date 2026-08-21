import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  buildVehiclePreviewGeometry,
  previewPositionToModel,
} from "../features/vehicleStudio/preview";
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
  calculateVehicleDiagnostics,
  createVehicleModelDraft,
  scaleVehicleModelMass,
  validateVehicleModel,
} from "../features/vehicleStudio/model";
import {
  cacheVehicleModels,
  loadVehicleModels,
  nextVehicleRevision,
  removeVehicleModel,
  restoreVehicleRevision,
  saveVehicleModel,
  vehicleModelStorageScope,
} from "../features/vehicleStudio/storage";
import {
  mergeVehicleModelStores,
  vehicleModelBoundaryFor,
} from "../features/vehicleStudio/cloudStorage";

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
    removeItem: (key: string) => { values.delete(key); },
  };
}

describe("Product-scoped Vehicle Studio contract", () => {
  it("renders independently authored Chinese modeling and option copy", () => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    render(createElement(I18nProvider, null, createElement(VehicleStudio)));

    expect(screen.getByRole("heading", { name: "无人机建模工作台" })).toBeVisible();
    expect(screen.getByRole("button", { name: "AI 协同设计" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "装配" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: /Carbon center frame/i })).toBeVisible();
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
    const hiddenCone = draft.components.find((component) => component.kind === "fuselage")!;
    hiddenCone.visible = false;
    hiddenCone.geometry.primitive = "cone";
    const sdf = generateGazeboSdf(draft);
    expect(sdf).toContain('<sdf version="1.10">');
    expect(sdf.match(/<link name="part_/g)).toHaveLength(draft.components.length);
    expect(sdf.match(/type="fixed"/g)).toHaveLength(draft.components.length);
    expect(sdf).toContain("carbon-center-frame");
    expect(sdf).toContain("motor-1");
    expect(sdf).toContain("aerodynamic-canopy");
    expect(sdf).toContain("<cone>");
    expect(sdf).not.toContain("<cylinder><radius>0.1</radius><length>0.34</length></cylinder>");
    expect(sdf).toContain('<model name="custom-quadrotor">');
    vi.restoreAllMocks();
  });

  it("scales the physical assembly when an AI brief requests a total vehicle mass", () => {
    const draft = createVehicleModelDraft();
    const original = structuredClone(draft);
    const originalMasses = draft.components.map((component) =>
      component.mass.mode === "density" ? component.mass.densityKgM3 : component.mass.massKg);

    const scaled = scaleVehicleModelMass(draft, 3.2);

    expect(calculateVehicleDiagnostics(scaled).totalMassKg).toBeCloseTo(3.2, 10);
    expect(scaled.body.massKg).toBeCloseTo(3.2, 10);
    expect(scaled.components.some((component, index) => {
      const value = component.mass.mode === "density" ? component.mass.densityKgM3 : component.mass.massKg;
      return value !== originalMasses[index];
    })).toBe(true);
    expect(draft).toEqual(original);
  });

  it("exports a solid cone with cone inertia instead of cylinder inertia", () => {
    const draft = createVehicleModelDraft();
    const cone = structuredClone(draft.components.find((component) => component.kind === "fuselage")!);
    cone.id = "solid-cone";
    cone.name = "Solid cone";
    cone.parentId = null;
    cone.geometry.primitive = "cone";
    cone.geometry.radiusM = 0.2;
    cone.geometry.lengthM = 0.6;
    cone.geometry.meshUri = "";
    cone.transform.scale = { x: 1, y: 1, z: 1 };
    cone.mass = { mode: "explicit", massKg: 2, densityKgM3: 1_000 };
    draft.components = [cone];
    draft.constraints = [];

    const sdf = generateGazeboSdf(draft);
    expect(sdf).toContain("<ixx>0.039</ixx><iyy>0.039</iyy><izz>0.024</izz>");
  });

  it("keeps an external mesh visual separate from primitive collision physics", () => {
    const draft = createVehicleModelDraft();
    const fuselage = draft.components.find((component) => component.kind === "fuselage")!;
    fuselage.geometry.meshUri = "model://custom/fuselage.glb";

    const sdf = generateGazeboSdf(draft);

    expect(sdf).toContain("<collision name=\"collision\"><geometry><box><size>0.34 0.2 0.09</size></box>");
    expect(sdf).toContain("<visual name=\"visual\"><geometry><mesh><uri>model://custom/fuselage.glb</uri>");
  });

  it("rejects primitive scales that cannot be represented by the physical export", () => {
    const draft = createVehicleModelDraft();
    const motor = draft.components.find((component) => component.kind === "motor")!;
    motor.transform.scale = { x: 1.5, y: 1, z: 1 };

    expect(validateVehicleModel(draft).map((issue) => issue.code))
      .toContain("incompatible-primitive-scale");
  });

  it("normalizes preview transforms through both expansion and scene scale", () => {
    expect(previewPositionToModel({ x: 18, y: -9, z: 4.5 }, 1.5, 3)).toEqual({
      x: 4,
      y: -2,
      z: 1,
    });
    expect(() => previewPositionToModel({ x: 1, y: 1, z: 1 }, 1, 0)).toThrow(/positive/);
  });

  it("blocks unsafe or incomplete model drafts before export", async () => {
    const draft = scaleVehicleModelMass(createVehicleModelDraft(), 20);
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
    const originalBodyMass = draft.body.massKg;
    const pending = buildVehiclePackDraft(draft);
    draft.name = "Mutated while hashing";
    draft.body.massKg = 900;
    const envelope = await pending;
    expect(envelope.payload.model.name).toBe(originalName);
    expect(envelope.payload.model.body.massKg).toBe(originalBodyMass);
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

  it("partitions local model caches by the complete tenant boundary", () => {
    const storage = memoryStorage();
    const draft = createVehicleModelDraft(new Date("2026-08-14T04:00:00.000Z"));
    const personalScope = vehicleModelStorageScope({
      userId: "owner-a",
      tenantId: "tenant-a",
      organizationId: null,
      workspaceId: "console-universal",
      edition: "universal",
    });
    const organizationScope = vehicleModelStorageScope({
      userId: "owner-a",
      tenantId: "tenant-b",
      organizationId: "organization-b",
      workspaceId: "console-universal",
      edition: "universal",
    });
    const simScope = vehicleModelStorageScope({
      userId: "owner-a",
      tenantId: "tenant-a",
      organizationId: null,
      workspaceId: "console-sim",
      edition: "sim",
    });

    saveVehicleModel(personalScope, draft, storage);

    expect(loadVehicleModels(personalScope, storage)).toHaveLength(1);
    expect(loadVehicleModels(organizationScope, storage)).toEqual([]);
    expect(loadVehicleModels(simScope, storage)).toEqual([]);
  });

  it("migrates a legacy personal Universal cache exactly once without crossing a tenant boundary", () => {
    const storage = memoryStorage();
    const draft = createVehicleModelDraft(new Date("2026-08-14T04:30:00.000Z"));
    const legacyKey = "dronedream:vehicle-studio:v1:owner-a";
    storage.setItem(legacyKey, JSON.stringify([{ draftId: draft.draftId, revisions: [draft] }]));
    const personalScope = vehicleModelStorageScope({
      userId: "owner-a",
      tenantId: "owner-a",
      organizationId: null,
      workspaceId: "console-universal",
      edition: "universal",
    });
    const organizationScope = vehicleModelStorageScope({
      userId: "owner-a",
      tenantId: "organization-b",
      organizationId: "organization-b",
      workspaceId: "console-universal",
      edition: "universal",
    });

    expect(loadVehicleModels(organizationScope, storage)).toEqual([]);
    expect(storage.getItem(legacyKey)).not.toBeNull();
    expect(loadVehicleModels(personalScope, storage)).toHaveLength(1);
    expect(storage.getItem(legacyKey)).toBeNull();
    expect(loadVehicleModels(personalScope, storage)).toHaveLength(1);
  });

  it("builds only complete Universal cloud boundaries", () => {
    const userId = "00000000-0000-4000-8000-000000000001";
    expect(vehicleModelBoundaryFor(userId, userId, null)).toEqual({
      userId,
      tenantId: userId,
      organizationId: null,
      workspaceId: "console-universal",
      edition: "universal",
    });
    expect(vehicleModelBoundaryFor(userId, userId, null, "autonomy")).toEqual({
      userId,
      tenantId: userId,
      organizationId: null,
      workspaceId: "console-autonomy",
      edition: "autonomy",
    });
    expect(vehicleModelBoundaryFor("local", userId, null)).toBeNull();
    expect(vehicleModelBoundaryFor(userId, "another-user", null)).toBeNull();
  });

  it("merges local and cloud revision chains without crossing draft identities", () => {
    const draft = createVehicleModelDraft(new Date("2026-08-14T01:00:00.000Z"));
    const localSecond = nextVehicleRevision(draft, new Date("2026-08-14T03:00:00.000Z"));
    localSecond.name = "Newest local assembly";
    const cloudSecond = nextVehicleRevision(draft, new Date("2026-08-14T02:00:00.000Z"));
    cloudSecond.name = "Older cloud assembly";
    const merged = mergeVehicleModelStores(
      [{ draftId: draft.draftId, revisions: [localSecond] }],
      [{ draftId: draft.draftId, revisions: [cloudSecond, draft] }],
    );

    expect(merged).toHaveLength(1);
    expect(merged[0].revisions.map((revision) => revision.revision)).toEqual([2, 1]);
    expect(merged[0].revisions[0].name).toBe("Newest local assembly");
  });

  it("refuses to cache a revision under another draft identity", () => {
    const storage = memoryStorage();
    const draft = createVehicleModelDraft();
    expect(() => cacheVehicleModels("owner-a", [{
      draftId: "00000000-0000-4000-8000-000000000099",
      revisions: [draft],
    }], storage)).toThrow(/crossed its draft boundary/);
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
