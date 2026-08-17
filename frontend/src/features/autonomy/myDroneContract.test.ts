import { describe, expect, it } from "vitest";

import { MY_DRONE_CONTRACT } from "./myDroneModel";
import { defaultAutonomyWorkspace, normalizeAutonomyWorkspace } from "./workspaceStore";

describe("My Drone qualified PX4 Gazebo contract", () => {
  it("keeps displayed mass, thrust, payload, and adapter aligned with the workspace", () => {
    const aircraft = defaultAutonomyWorkspace(new Date("2026-08-18T00:00:00.000Z")).aircraft;

    expect(aircraft.controlInterface).toBe("mavsdk");
    expect(aircraft.dryMassKg).toBeCloseTo(MY_DRONE_CONTRACT.dryMassKg, 12);
    expect(aircraft.maximumTakeoffMassKg).toBeCloseTo(MY_DRONE_CONTRACT.maximumTakeoffMassKg, 12);
    expect(aircraft.maximumThrustN).toBeCloseTo(MY_DRONE_CONTRACT.maximumThrustN, 8);
    expect(aircraft.maximumPickupPayloadKg).toBe(MY_DRONE_CONTRACT.maximumPickupPayloadKg);
    expect(MY_DRONE_CONTRACT.qualifiedPayload.sizeM).toEqual({ x: 0.16, y: 0.06, z: 0.16 });
    expect(aircraft.sensors).toEqual(["gps"]);
    expect(aircraft.sensorMounts.map((sensor) => sensor.kind)).toEqual(["gps"]);
    expect(aircraft.dryMassKg + aircraft.maximumPickupPayloadKg).toBeCloseTo(
      aircraft.maximumTakeoffMassKg,
      12,
    );
    const loadedThrustToWeight = aircraft.maximumThrustN
      / (aircraft.maximumTakeoffMassKg * 9.80665);
    expect(loadedThrustToWeight).toBeGreaterThanOrEqual(
      MY_DRONE_CONTRACT.minimumQualifiedThrustToWeight,
    );
  });

  it("migrates only the exact stale bundled X500 physics tuple and invalidates its receipt", () => {
    const stale = defaultAutonomyWorkspace(new Date("2026-08-17T00:00:00.000Z"));
    stale.aircraft = {
      ...stale.aircraft,
      status: "validated-unsigned",
      qualificationReceiptId: "receipt-stale-physics",
      qualificationContentHash: "a".repeat(64),
      controlInterface: "px4-ros2",
      computePlatform: "Jetson Orin NX",
      dryMassKg: 1.86,
      maximumTakeoffMassKg: 2.8,
      maximumThrustN: 44,
      maximumPickupPayloadKg: 0.35,
    };

    const migrated = normalizeAutonomyWorkspace(stale);

    expect(migrated.aircraft.controlInterface).toBe("mavsdk");
    expect(migrated.aircraft.dryMassKg).toBeCloseTo(2.0643076923076924, 12);
    expect(migrated.aircraft.maximumPickupPayloadKg).toBe(0.1);
    expect(migrated.aircraft.status).toBe("draft");
    expect(migrated.aircraft.qualificationReceiptId).toBeNull();
    expect(migrated.aircraft.qualificationContentHash).toBeNull();
  });

  it("removes sensors that were never present in the qualified bundled SDF", () => {
    const stale = defaultAutonomyWorkspace(new Date("2026-08-17T00:00:00.000Z"));
    stale.aircraft = {
      ...stale.aircraft,
      status: "validated-unsigned",
      qualificationReceiptId: "receipt-stale-sensors",
      qualificationContentHash: "a".repeat(64),
      sensors: ["rgb", "depth", "gps", "vio"],
      sensorMounts: [
        ...stale.aircraft.sensorMounts,
        { id: "front-depth", kind: "depth", calibrated: true, calibrationStatus: "verified", positionM: { x: 0.155, y: 0, z: -0.055 }, rollPitchYawDeg: { x: 0, y: -8, z: 0 }, rateHz: 30, calibrationAgeDays: 0 },
      ],
    };

    const migrated = normalizeAutonomyWorkspace(stale);

    expect(migrated.aircraft.sensors).toEqual(["gps"]);
    expect(migrated.aircraft.sensorMounts.map((sensor) => sensor.kind)).toEqual(["gps"]);
    expect(migrated.aircraft.status).toBe("draft");
    expect(migrated.aircraft.qualificationReceiptId).toBeNull();
  });
});
