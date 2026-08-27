export const DRONE_STARFLIGHT_DURATION_SECONDS = 18;

export type DroneStarflightPose = {
  x: number;
  y: number;
  z: number;
  scale: number;
  yaw: number;
  pitch: number;
  roll: number;
};

type CityFlightWaypoint = {
  at: number;
  x: number;
  y: number;
  z: number;
  scale: number;
};

/* The path follows known open corridors in buildNightCity: the two east-west
   avenues, the central north-south avenue, the stadium apron, and the river.
   It therefore reads as a low city flight without clipping through a tower. */
const CITY_FLIGHT_PATH: CityFlightWaypoint[] = [
  { at: 0, x: 0, y: 0, z: 0, scale: 1 },
  { at: 0.08, x: 0, y: 0.48, z: 1.6, scale: 0.52 },
  { at: 0.16, x: -4.4, y: 0.4, z: 1.6, scale: 0.32 },
  { at: 0.24, x: -10.2, y: 0.36, z: 1.6, scale: 0.25 },
  { at: 0.32, x: -10.2, y: 0.56, z: -3.1, scale: 0.22 },
  { at: 0.4, x: -6.2, y: 0.42, z: -6.2, scale: 0.24 },
  { at: 0.48, x: 0, y: 0.36, z: -6.2, scale: 0.2 },
  { at: 0.56, x: 6.15, y: 0.62, z: -6.2, scale: 0.18 },
  { at: 0.64, x: 6.15, y: 0.48, z: 1.6, scale: 0.27 },
  { at: 0.71, x: 11, y: 0.42, z: 1.6, scale: 0.31 },
  { at: 0.78, x: 6.15, y: 0.5, z: 1.6, scale: 0.27 },
  { at: 0.83, x: 0, y: 0.5, z: 1.6, scale: 0.34 },
  { at: 0.89, x: 0, y: 0.58, z: 8.2, scale: 0.4 },
  { at: 0.94, x: 0, y: 0.52, z: 1.6, scale: 0.52 },
  { at: 1, x: 0, y: 0, z: 0, scale: 1 },
];

function clamp(value: number) {
  if (!Number.isFinite(value)) return value === Number.POSITIVE_INFINITY ? 1 : 0;
  return Math.min(1, Math.max(0, value));
}

function smoothStep(value: number) {
  const clamped = clamp(value);
  return clamped * clamped * (3 - 2 * clamped);
}

function interpolate(progress: number) {
  const clamped = clamp(progress);
  let index = 0;
  while (
    index < CITY_FLIGHT_PATH.length - 2 &&
    clamped > CITY_FLIGHT_PATH[index + 1].at
  ) {
    index += 1;
  }
  const start = CITY_FLIGHT_PATH[index];
  const finish = CITY_FLIGHT_PATH[index + 1];
  const local = smoothStep((clamped - start.at) / Math.max(finish.at - start.at, 0.0001));
  const mix = (from: number, to: number) => from + (to - from) * local;
  return {
    x: mix(start.x, finish.x),
    y: mix(start.y, finish.y),
    z: mix(start.z, finish.z),
    scale: mix(start.scale, finish.scale),
  };
}

export function getDroneStarflightPose(rawProgress: number): DroneStarflightPose {
  const progress = clamp(rawProgress);
  const position = interpolate(progress);
  if (progress === 0 || progress === 1) {
    return { ...position, yaw: 0, pitch: 0, roll: 0 };
  }

  const before = interpolate(progress - 0.004);
  const after = interpolate(progress + 0.004);
  const deltaX = after.x - before.x;
  const deltaY = after.y - before.y;
  const deltaZ = after.z - before.z;
  const heading = Math.atan2(deltaX, deltaZ);
  const takeoffBlend = smoothStep(progress / 0.06);
  const landingBlend = smoothStep((1 - progress) / 0.06);
  const flightBlend = takeoffBlend * landingBlend;

  return {
    ...position,
    yaw: heading * flightBlend,
    pitch: Math.max(-0.13, Math.min(0.13, -deltaY * 1.8)) * flightBlend,
    roll: -Math.sin(progress * Math.PI * 9) * 0.1 * flightBlend,
  };
}
