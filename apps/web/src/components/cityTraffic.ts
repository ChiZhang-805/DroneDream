export type CityTrafficAxis = "x" | "z";

export type CityTrafficDirection = 1 | -1;

export type CityTrafficVehicleState = {
  id: string;
  axis: CityTrafficAxis;
  direction: CityTrafficDirection;
  lane: number;
  distance: number;
  speed: number;
  stopDistance: number;
};

export type CityTrafficSignalPhase =
  | "x-green"
  | "all-red-after-x"
  | "z-green"
  | "all-red-after-z";

export const CITY_TRAFFIC_ROUTE_HALF_LENGTH = 14;
export const CITY_TRAFFIC_ROUTE_LENGTH = CITY_TRAFFIC_ROUTE_HALF_LENGTH * 2;
export const CITY_TRAFFIC_MINIMUM_CENTER_GAP = 0.92;

const CITY_TRAFFIC_GREEN_SECONDS = 6.4;
const CITY_TRAFFIC_ALL_RED_SECONDS = 3.2;
const CITY_TRAFFIC_CYCLE_SECONDS =
  (CITY_TRAFFIC_GREEN_SECONDS + CITY_TRAFFIC_ALL_RED_SECONDS) * 2;
const CITY_TRAFFIC_BRAKING_DISTANCE = 1.8;

type CityTrafficVehicleTemplate = Omit<CityTrafficVehicleState, "id" | "distance"> & {
  initialDistances: readonly number[];
};

// The launch scene has one east-west avenue and one north-south avenue with
// moving traffic. Every lane uses a single cruise speed so the initial spacing
// is preserved until a queue forms at a red light. The north/south stop lines
// are asymmetric because their shared intersection is centred at z=1.6.
const CITY_TRAFFIC_TEMPLATES: readonly CityTrafficVehicleTemplate[] = [
  {
    axis: "x",
    direction: 1,
    lane: 1.3,
    speed: 1.14,
    stopDistance: 12.9,
    initialDistances: [1, 7.5, 21],
  },
  {
    axis: "x",
    direction: -1,
    lane: 1.9,
    speed: 1.08,
    stopDistance: 12.9,
    initialDistances: [3.5, 10, 23.5],
  },
  {
    axis: "z",
    direction: 1,
    lane: -0.28,
    speed: 1.1,
    stopDistance: 14.5,
    initialDistances: [2, 8.5, 21.5],
  },
  {
    axis: "z",
    direction: -1,
    lane: 0.28,
    speed: 1.05,
    stopDistance: 11.3,
    initialDistances: [4, 9.5, 22.5],
  },
] as const;

function positiveModulo(value: number, modulus: number) {
  return ((value % modulus) + modulus) % modulus;
}

function forwardDistance(from: number, to: number) {
  return positiveModulo(to - from, CITY_TRAFFIC_ROUTE_LENGTH);
}

function laneKey(vehicle: CityTrafficVehicleState) {
  return `${vehicle.axis}:${vehicle.direction}:${vehicle.lane}`;
}

export function createCityTrafficVehicles(): CityTrafficVehicleState[] {
  return CITY_TRAFFIC_TEMPLATES.flatMap((template) =>
    template.initialDistances.map((distance, index) => ({
      id: `${template.axis}-${template.direction === 1 ? "forward" : "reverse"}-${index}`,
      axis: template.axis,
      direction: template.direction,
      lane: template.lane,
      distance,
      speed: template.speed,
      stopDistance: template.stopDistance,
    })),
  );
}

export function getCityTrafficSignalPhase(elapsedSeconds: number): CityTrafficSignalPhase {
  const phase = positiveModulo(elapsedSeconds, CITY_TRAFFIC_CYCLE_SECONDS);
  if (phase < CITY_TRAFFIC_GREEN_SECONDS) return "x-green";
  if (phase < CITY_TRAFFIC_GREEN_SECONDS + CITY_TRAFFIC_ALL_RED_SECONDS) {
    return "all-red-after-x";
  }
  if (phase < CITY_TRAFFIC_GREEN_SECONDS * 2 + CITY_TRAFFIC_ALL_RED_SECONDS) {
    return "z-green";
  }
  return "all-red-after-z";
}

export function cityTrafficAxisHasGreen(
  axis: CityTrafficAxis,
  elapsedSeconds: number,
) {
  return getCityTrafficSignalPhase(elapsedSeconds) === `${axis}-green`;
}

export function getCityTrafficWorldPosition(vehicle: CityTrafficVehicleState) {
  const coordinate = vehicle.direction === 1
    ? -CITY_TRAFFIC_ROUTE_HALF_LENGTH + vehicle.distance
    : CITY_TRAFFIC_ROUTE_HALF_LENGTH - vehicle.distance;
  return vehicle.axis === "x"
    ? { x: coordinate, z: vehicle.lane }
    : { x: vehicle.lane, z: coordinate };
}

/**
 * Advances the miniature traffic simulation without allowing a vehicle to
 * cross a red stop line or close the centre-to-centre gap to the next vehicle
 * in its lane. Signal changes include a 3.2 second all-red interval, which is
 * longer than the slowest vehicle needs to clear the protected junction.
 */
export function advanceCityTraffic<T extends CityTrafficVehicleState>(
  vehicles: T[],
  elapsedSeconds: number,
  deltaSeconds: number,
) {
  const safeDelta = Math.max(0, Math.min(deltaSeconds, 0.1));
  if (safeDelta === 0 || vehicles.length === 0) return elapsedSeconds;

  const nextElapsedSeconds = elapsedSeconds + safeDelta;
  const lanes = new Map<string, T[]>();
  for (const vehicle of vehicles) {
    const key = laneKey(vehicle);
    const lane = lanes.get(key);
    if (lane) lane.push(vehicle);
    else lanes.set(key, [vehicle]);
  }

  const nextDistances = new Map<string, number>();
  for (const lane of lanes.values()) {
    lane.sort((first, second) => first.distance - second.distance);
    for (let index = 0; index < lane.length; index += 1) {
      const vehicle = lane[index];
      const leader = lane[(index + 1) % lane.length];
      let movement = vehicle.speed * safeDelta;

      const leaderGap = forwardDistance(vehicle.distance, leader.distance);
      movement = Math.min(
        movement,
        Math.max(0, leaderGap - CITY_TRAFFIC_MINIMUM_CENTER_GAP),
      );

      if (!cityTrafficAxisHasGreen(vehicle.axis, nextElapsedSeconds)) {
        const stopLineDistance = forwardDistance(vehicle.distance, vehicle.stopDistance);
        if (stopLineDistance <= CITY_TRAFFIC_BRAKING_DISTANCE) {
          const brakingRatio = Math.min(
            1,
            stopLineDistance / CITY_TRAFFIC_BRAKING_DISTANCE,
          );
          movement = Math.min(movement, vehicle.speed * brakingRatio * safeDelta);
          movement = Math.min(movement, stopLineDistance);
        }
      }

      nextDistances.set(
        vehicle.id,
        positiveModulo(vehicle.distance + movement, CITY_TRAFFIC_ROUTE_LENGTH),
      );
    }
  }

  for (const vehicle of vehicles) {
    vehicle.distance = nextDistances.get(vehicle.id) ?? vehicle.distance;
  }
  return nextElapsedSeconds;
}
