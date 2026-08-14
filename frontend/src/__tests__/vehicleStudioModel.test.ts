import { describe, expect, it } from "vitest";

import {
  calculateVehicleDiagnostics,
  createVehicleModelFromBrief,
  radialArrayVehicleComponent,
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
});
