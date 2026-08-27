import { describe, expect, it } from "vitest";

import {
  CITY_TRAFFIC_MINIMUM_CENTER_GAP,
  CITY_TRAFFIC_ROUTE_LENGTH,
  advanceCityTraffic,
  createCityTrafficVehicles,
  getCityTrafficSignalPhase,
  getCityTrafficWorldPosition,
  type CityTrafficVehicleState,
} from "../components/cityTraffic";

function forwardDistance(from: number, to: number) {
  return ((to - from) % CITY_TRAFFIC_ROUTE_LENGTH + CITY_TRAFFIC_ROUTE_LENGTH) %
    CITY_TRAFFIC_ROUTE_LENGTH;
}

function groupByLane(vehicles: CityTrafficVehicleState[]) {
  const lanes = new Map<string, CityTrafficVehicleState[]>();
  for (const vehicle of vehicles) {
    const key = `${vehicle.axis}:${vehicle.direction}:${vehicle.lane}`;
    const lane = lanes.get(key);
    if (lane) lane.push(vehicle);
    else lanes.set(key, [vehicle]);
  }
  return lanes;
}

describe("night-city traffic", () => {
  it("uses deterministic, separated vehicles on four physical lanes", () => {
    const first = createCityTrafficVehicles();
    const second = createCityTrafficVehicles();

    expect(first).toEqual(second);
    expect(first).toHaveLength(12);
    expect(groupByLane(first)).toHaveLength(4);
  });

  it("provides an all-red junction clearance between conflicting axes", () => {
    expect(getCityTrafficSignalPhase(0)).toBe("x-green");
    expect(getCityTrafficSignalPhase(6.5)).toBe("all-red-after-x");
    expect(getCityTrafficSignalPhase(9.7)).toBe("z-green");
    expect(getCityTrafficSignalPhase(16.2)).toBe("all-red-after-z");
  });

  it("preserves safe lane gaps and prevents cross-traffic overlap for ten minutes", () => {
    const vehicles = createCityTrafficVehicles();
    let elapsedSeconds = 0;
    let minimumObservedLaneGap = Number.POSITIVE_INFINITY;
    let crossTrafficOverlapDetected = false;

    for (let step = 0; step < 36_000; step += 1) {
      elapsedSeconds = advanceCityTraffic(vehicles, elapsedSeconds, 1 / 60);

      for (const lane of groupByLane(vehicles).values()) {
        lane.sort((first, second) => first.distance - second.distance);
        for (let index = 0; index < lane.length; index += 1) {
          const vehicle = lane[index];
          const leader = lane[(index + 1) % lane.length];
          minimumObservedLaneGap = Math.min(
            minimumObservedLaneGap,
            forwardDistance(vehicle.distance, leader.distance),
          );
        }
      }

      const horizontal = vehicles.filter((vehicle) => vehicle.axis === "x");
      const vertical = vehicles.filter((vehicle) => vehicle.axis === "z");
      for (const first of horizontal) {
        const firstPosition = getCityTrafficWorldPosition(first);
        for (const second of vertical) {
          const secondPosition = getCityTrafficWorldPosition(second);
          const overlapsProtectedFootprint =
            Math.abs(firstPosition.x - secondPosition.x) < 0.38 &&
            Math.abs(firstPosition.z - secondPosition.z) < 0.38;
          crossTrafficOverlapDetected ||= overlapsProtectedFootprint;
        }
      }
    }

    expect(minimumObservedLaneGap)
      .toBeGreaterThanOrEqual(CITY_TRAFFIC_MINIMUM_CENTER_GAP - 1e-8);
    expect(crossTrafficOverlapDetected).toBe(false);
  });
});
