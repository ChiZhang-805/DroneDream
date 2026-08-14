import { describe, expect, it } from "vitest";

import {
  calculateVehicleDiagnostics,
  createVehicleModelDraft,
  createVehicleModelFromBrief,
  evaluateVehicleConstraints,
  migrateVehicleModelDraft,
  mirrorVehicleComponent,
  radialArrayVehicleComponent,
  rebuildVehicleRotorArchitecture,
  setVehicleComponentLocked,
  solveVehicleConstraints,
  validateVehicleModel,
} from "../features/vehicleStudio/model";
import { assertVehicleModelShape } from "../features/vehicleStudio/pack";
import {
  applyVehicleCatalogEntry,
  applyVehicleMaterialPreset,
} from "../features/vehicleStudio/catalog";

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

  it("derives mass and thrust from physical components instead of stale summaries", () => {
    const draft = createVehicleModelDraft();
    const baseline = calculateVehicleDiagnostics(draft);
    draft.body.massKg = baseline.totalMassKg * 10;
    expect(calculateVehicleDiagnostics(draft).thrustToWeight).toBeCloseTo(baseline.thrustToWeight, 10);

    const removedMotor = draft.components.find((component) => component.kind === "motor")!;
    draft.components = draft.components.filter((component) => component.id !== removedMotor.id);
    const afterRemoval = calculateVehicleDiagnostics(draft);
    const codes = validateVehicleModel(draft).map((issue) => issue.code);

    expect(afterRemoval.thrustToWeight).toBeLessThan(baseline.thrustToWeight);
    expect(codes).toContain("motor-count-mismatch");
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

  it("evaluates balance constraints from only their referenced components", () => {
    const draft = createVehicleModelDraft();
    const frame = draft.components.find((component) => component.kind === "frame")!;
    const camera = draft.components.find((component) => component.kind === "camera-gimbal")!;
    camera.transform.positionM.x = 4;
    draft.constraints = [{ id: crypto.randomUUID(), type: "balance", componentIds: [frame.id], axis: "y", value: .001, enabled: true }];

    expect(evaluateVehicleConstraints(draft)[0].status).toBe("satisfied");
  });

  it("keeps constraint validation tolerance independent from a coarse design grid", () => {
    const draft = createVehicleModelDraft();
    const props = draft.components.filter((component) => component.kind === "propeller");
    const clearance = calculateVehicleDiagnostics(draft).minimumRotorClearanceM;
    draft.designParameters.gridM = .1;
    draft.constraints = [{ id: crypto.randomUUID(), type: "clearance", componentIds: props.map((component) => component.id), axis: "y", value: clearance + .01, enabled: true }];

    expect(evaluateVehicleConstraints(draft)[0].status).toBe("violated");
  });

  it("evaluates and solves every mirrored rotation axis as well as position", () => {
    const draft = createVehicleModelDraft();
    const camera = draft.components.find((component) => component.kind === "camera-gimbal")!;
    camera.transform.rotationDeg = { x: 11, y: 18, z: 23 };
    const mirrored = mirrorVehicleComponent(draft, camera.id, "x");
    const mirrorConstraint = mirrored.constraints.find((constraint) => constraint.type === "mirror")!;
    const mirroredCamera = mirrored.components.find((component) => component.id === mirrorConstraint.componentIds[1])!;
    expect(mirroredCamera.transform.rotationDeg).toEqual({ x: 11, y: -18, z: -23 });
    mirroredCamera.transform.rotationDeg.z = 9;

    expect(evaluateVehicleConstraints(mirrored).find((evaluation) => evaluation.constraintId === mirrorConstraint.id)?.status).toBe("violated");
    const solved = solveVehicleConstraints(mirrored);
    expect(evaluateVehicleConstraints(solved.draft).find((evaluation) => evaluation.constraintId === mirrorConstraint.id)?.status).toBe("satisfied");
    expect(solved.draft.components.find((component) => component.id === mirrorConstraint.componentIds[1])?.transform.rotationDeg).toEqual({ x: 11, y: -18, z: -23 });
  });

  it("keeps propulsion fleet presets atomic when a member is locked", () => {
    const draft = createVehicleModelDraft();
    const motors = draft.components.filter((component) => component.kind === "motor");
    motors[0].locked = true;
    const motorMasses = motors.map((motor) => motor.mass.massKg);
    const maximumThrustPerMotorN = draft.propulsion.maximumThrustPerMotorN;
    const result = applyVehicleCatalogEntry(draft, "motor-2814");

    expect(result.affectedCount).toBe(0);
    expect(result.draft.propulsion.maximumThrustPerMotorN).toBe(maximumThrustPerMotorN);
    expect(result.draft.components.filter((component) => component.kind === "motor").map((motor) => motor.mass.massKg)).toEqual(motorMasses);
  });

  it("does not replace a locked singleton through the component catalog", () => {
    const draft = createVehicleModelDraft();
    const battery = draft.components.find((component) => component.kind === "battery")!;
    battery.locked = true;
    const result = applyVehicleCatalogEntry(draft, "battery-6s-10");

    expect(result.affectedCount).toBe(0);
    expect(result.draft).toBe(draft);
    expect(result.draft.propulsion.batteryCapacityMah).toBe(draft.propulsion.batteryCapacityMah);
    expect(result.draft.components.find((component) => component.id === battery.id)?.mass.massKg).toBe(battery.mass.massKg);
  });

  it("can leave a physical material preset without retaining density mode", () => {
    const draft = createVehicleModelDraft();
    const frame = draft.components.find((component) => component.kind === "frame")!;
    const materialized = applyVehicleMaterialPreset(draft, frame.id, "aluminum-6061");
    const customized = applyVehicleMaterialPreset(materialized, frame.id, "");
    const customizedFrame = customized.components.find((component) => component.id === frame.id)!;

    expect(customizedFrame.mass.mode).toBe("explicit");
    expect(customizedFrame.tags.some((tag) => tag.startsWith("material:"))).toBe(false);
    expect(customizedFrame.mass.massKg).toBeGreaterThan(0);
  });
});
