import { describe, expect, it } from "vitest";

import {
  calculateVehicleDiagnostics,
  createVehicleModelDraft,
  createVehicleModelFromBrief,
  migrateVehicleModelDraft,
  radialArrayVehicleComponent,
  rebuildVehicleRotorArchitecture,
  setVehicleComponentLocked,
  validateVehicleModel,
} from "../features/vehicleStudio/model";
import { assertVehicleModelShape } from "../features/vehicleStudio/pack";

describe("Vehicle Studio engineering generator", () => {
  it("turns a payload brief into an editable redundant assembly", () => {
    const { draft, decisions } = createVehicleModelFromBrief({
      name: "Octa cargo demonstrator",
      mission: "payload",
      payloadKg: 2.4,
      targetFlightMinutes: 22,
      operatingEnvironment: "outdoor",
    }, new Date("2026-08-14T00:00:00.000Z"));

    expect(draft.propulsion.motorCount).toBe(8);
    expect(draft.components.filter((component) => component.kind === "arm")).toHaveLength(8);
    expect(draft.components.filter((component) => component.kind === "motor")).toHaveLength(8);
    expect(draft.components.filter((component) => component.kind === "propeller")).toHaveLength(8);
    expect(draft.components.some((component) => component.kind === "payload" && component.mass.massKg === 2.4)).toBe(true);
    expect(draft.components.every((component) => component.source === "ai")).toBe(true);
    expect(draft.constraints.some((constraint) => constraint.type === "radial-array")).toBe(true);
    expect(calculateVehicleDiagnostics(draft).minimumRotorClearanceM).toBeGreaterThanOrEqual(.017);
    expect(validateVehicleModel(draft).some((issue) => issue.code === "rotor-disk-intersection")).toBe(false);
    expect(decisions).toHaveLength(4);
  });

  it("adds mission sensors and computes engineering diagnostics", () => {
    const { draft } = createVehicleModelFromBrief({
      name: "Inspection mapper",
      mission: "inspection",
      motorCount: 6,
      camera: true,
      lidar: true,
      targetFlightMinutes: 28,
      operatingEnvironment: "windy",
    });
    const diagnostics = calculateVehicleDiagnostics(draft);

    expect(draft.components.some((component) => component.kind === "camera-gimbal")).toBe(true);
    expect(draft.components.some((component) => component.kind === "sensor" && component.tags.includes("lidar"))).toBe(true);
    expect(diagnostics.componentCount).toBeGreaterThan(25);
    expect(diagnostics.totalMassKg).toBeGreaterThan(0);
    expect(diagnostics.batteryEnergyWh).toBeGreaterThan(0);
    expect(diagnostics.rotorDiskAreaM2).toBeGreaterThan(0);
    expect(validateVehicleModel(draft).filter((issue) => issue.code === "unsupported-schema")).toHaveLength(0);
  });

  it("keeps hidden viewport parts in physical engineering diagnostics", () => {
    const { draft } = createVehicleModelFromBrief({
      name: "Visibility invariant rig",
      mission: "inspection",
      motorCount: 4,
      payloadKg: 1.2,
    });
    const before = calculateVehicleDiagnostics(draft);
    draft.components[0].visible = false;
    const after = calculateVehicleDiagnostics(draft);

    expect(after.visibleComponentCount).toBe(before.visibleComponentCount - 1);
    expect(after.totalMassKg).toBeCloseTo(before.totalMassKg, 10);
    expect(after.centerOfMassM).toEqual(before.centerOfMassM);
    expect(after.projectedAreaM2).toBeCloseTo(before.projectedAreaM2, 10);
  });

  it("keeps explicit architecture choices instead of collapsing to a generic quadrotor", () => {
    const { draft } = createVehicleModelFromBrief({
      name: "Indoor agile platform",
      mission: "agility",
      motorCount: 4,
      camera: false,
      lidar: false,
      operatingEnvironment: "indoor",
    });

    expect(draft.propulsion.motorCount).toBe(4);
    expect(draft.components.some((component) => component.kind === "camera-gimbal")).toBe(false);
    expect(draft.sensors.find((sensor) => sensor.type === "gps")?.enabled).toBe(false);
    expect(draft.components.length).toBeGreaterThan(15);
  });

  it("keeps existing assembly identities valid when a constrained part becomes a radial array", () => {
    const { draft } = createVehicleModelFromBrief({
      name: "Constraint continuity rig",
      mission: "inspection",
      motorCount: 6,
      camera: true,
      lidar: true,
    });
    const referencedId = draft.constraints.flatMap((constraint) => constraint.componentIds)
      .find((id) => draft.components.some((component) => component.id === id));
    expect(referencedId).toBeTruthy();

    const arrayed = radialArrayVehicleComponent(draft, referencedId!, 4);

    expect(arrayed.components.some((component) => component.id === referencedId)).toBe(true);
    expect(() => assertVehicleModelShape(arrayed)).not.toThrow();
  });

  it("rebuilds the editable rotor assembly when an assistant changes propulsion", () => {
    const { draft } = createVehicleModelFromBrief({
      name: "Assistant architecture rig",
      mission: "agility",
      motorCount: 4,
    });
    const originalRotorIds = new Set(draft.components
      .filter((component) => ["arm", "motor", "propeller"].includes(component.kind))
      .map((component) => component.id));

    const rebuilt = rebuildVehicleRotorArchitecture(draft, {
      motorCount: 6,
      armLengthM: .48,
      propellerDiameterM: .31,
    }, new Date("2026-08-14T05:00:00.000Z"));

    expect(rebuilt.propulsion).toMatchObject({
      motorCount: 6,
      armLengthM: .48,
      propellerDiameterM: .31,
    });
    expect(rebuilt.components.filter((component) => component.kind === "arm")).toHaveLength(6);
    expect(rebuilt.components.filter((component) => component.kind === "motor")).toHaveLength(6);
    expect(rebuilt.components.filter((component) => component.kind === "propeller")).toHaveLength(6);
    expect(rebuilt.components.some((component) => originalRotorIds.has(component.id))).toBe(false);
    expect(rebuilt.components.some((component) => component.kind === "camera-gimbal")).toBe(true);
    expect(rebuilt.constraints.every((constraint) => constraint.componentIds.every((id) => (
      rebuilt.components.some((component) => component.id === id)
    )))).toBe(true);
    expect(rebuilt.updatedAt).toBe("2026-08-14T05:00:00.000Z");
    expect(() => assertVehicleModelShape(rebuilt)).not.toThrow();
  });

  it("preserves the exact legacy total mass when migrating a lightweight model", () => {
    const draft = createVehicleModelDraft(new Date("2026-08-14T00:00:00.000Z"));
    const legacyMassKg = .25;
    const legacy = {
      schemaVersion: 1,
      draftId: draft.draftId,
      revision: draft.revision,
      name: draft.name,
      manufacturer: draft.manufacturer,
      vehicleClass: draft.vehicleClass,
      body: { ...draft.body, massKg: legacyMassKg },
      propulsion: draft.propulsion,
      sensors: draft.sensors,
      autopilot: draft.autopilot,
      controlTarget: draft.controlTarget,
      targetEditions: draft.targetEditions,
      notes: draft.notes,
      createdAt: draft.createdAt,
      updatedAt: draft.updatedAt,
    };

    const migrated = migrateVehicleModelDraft(legacy);
    const migratedMassKg = migrated.components.reduce((sum, component) => sum + component.mass.massKg, 0);

    expect(migratedMassKg).toBeCloseTo(legacyMassKg, 12);
    expect(migrated.components.every((component) => component.mass.massKg > 0)).toBe(true);
  });

  it("allows an assembly component to be unlocked through the lock operation", () => {
    const draft = createVehicleModelDraft();
    const componentId = draft.components[0].id;

    const locked = setVehicleComponentLocked(draft, componentId, true);
    const unlocked = setVehicleComponentLocked(locked, componentId, false);

    expect(locked.components.find((component) => component.id === componentId)?.locked).toBe(true);
    expect(unlocked.components.find((component) => component.id === componentId)?.locked).toBe(false);
  });
});
