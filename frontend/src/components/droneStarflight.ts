export const DRONE_STARFLIGHT_DURATION_SECONDS = 12;

export type DroneStarflightPose = {
  x: number;
  y: number;
  z: number;
  scale: number;
  yaw: number;
  pitch: number;
  roll: number;
};

const CITY_ORBIT_ENTRY = { x: 3.9, y: 0.95, z: -3.5 };
const CITY_ORBIT_RADIUS_X = 3.9;
const CITY_ORBIT_RADIUS_Z = 2.7;

function clamp(value: number) {
  if (!Number.isFinite(value)) return value === Number.POSITIVE_INFINITY ? 1 : 0;
  return Math.min(1, Math.max(0, value));
}

function smoothStep(value: number) {
  const clamped = clamp(value);
  return clamped * clamped * (3 - 2 * clamped);
}

export function getDroneStarflightPose(rawProgress: number): DroneStarflightPose {
  const progress = clamp(rawProgress);
  const outboundEnd = 0.2;
  const returnStart = 0.82;

  if (progress <= outboundEnd) {
    const phase = smoothStep(progress / outboundEnd);
    return {
      x: CITY_ORBIT_ENTRY.x * phase,
      y: CITY_ORBIT_ENTRY.y * phase,
      z: CITY_ORBIT_ENTRY.z * phase,
      scale: 1 - phase * 0.38,
      yaw: phase * -Math.PI / 2,
      pitch: Math.sin(phase * Math.PI) * -0.1,
      roll: -0.16 * Math.sin(phase * Math.PI / 2),
    };
  }

  if (progress <= returnStart) {
    const orbitProgress = (progress - outboundEnd) / (returnStart - outboundEnd);
    const angle = smoothStep(orbitProgress) * Math.PI * 2;
    return {
      x: Math.cos(angle) * CITY_ORBIT_RADIUS_X,
      y: CITY_ORBIT_ENTRY.y + Math.sin(angle * 2) * 0.2,
      z: CITY_ORBIT_ENTRY.z + Math.sin(angle) * CITY_ORBIT_RADIUS_Z,
      scale: 0.62 - Math.sin(angle) * 0.055,
      yaw: -Math.PI / 2 - angle,
      pitch: Math.sin(angle * 2) * 0.055,
      roll: -0.16 * Math.cos(angle),
    };
  }

  const phase = smoothStep((progress - returnStart) / (1 - returnStart));
  return {
    x: CITY_ORBIT_ENTRY.x * (1 - phase),
    y: CITY_ORBIT_ENTRY.y * (1 - phase),
    z: CITY_ORBIT_ENTRY.z * (1 - phase),
    scale: 0.62 + phase * 0.38,
    yaw: -Math.PI * 2.5 * (1 - phase),
    pitch: Math.sin(phase * Math.PI) * 0.1,
    roll: -0.16 * Math.cos(phase * Math.PI / 2),
  };
}
