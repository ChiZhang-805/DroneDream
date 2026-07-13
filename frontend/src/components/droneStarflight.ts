export const DRONE_STARFLIGHT_DURATION_SECONDS = 11.4;

export type DroneStarflightPose = {
  x: number;
  y: number;
  z: number;
  scale: number;
  yaw: number;
  pitch: number;
  roll: number;
};

function clamp(value: number) {
  return Math.min(1, Math.max(0, value));
}

function smoothStep(value: number) {
  const clamped = clamp(value);
  return clamped * clamped * (3 - 2 * clamped);
}

export function getDroneStarflightPose(rawProgress: number): DroneStarflightPose {
  const progress = clamp(rawProgress);
  const outboundEnd = 0.28;
  const orbitEnd = 0.74;

  if (progress <= outboundEnd) {
    const phase = smoothStep(progress / outboundEnd);
    return {
      x: Math.sin(phase * Math.PI) * 0.34,
      y: phase * 1.25,
      z: phase * -7.4,
      scale: 1 - phase * 0.5,
      yaw: phase * -0.9,
      pitch: Math.sin(phase * Math.PI) * -0.12,
      roll: Math.sin(phase * Math.PI) * 0.08,
    };
  }

  if (progress <= orbitEnd) {
    const phase = (progress - outboundEnd) / (orbitEnd - outboundEnd);
    const angle = phase * Math.PI * 2;
    return {
      x: Math.sin(angle) * 1.75,
      y: 1.25 + Math.sin(angle * 2) * 0.22,
      z: -5.9 - Math.cos(angle) * 1.5,
      scale: 0.5 + Math.sin(angle) * 0.025,
      yaw: -0.9 - angle,
      pitch: Math.cos(angle) * 0.085,
      roll: Math.sin(angle) * 0.14,
    };
  }

  const phase = smoothStep((progress - orbitEnd) / (1 - orbitEnd));
  return {
    x: -Math.sin(phase * Math.PI) * 0.34,
    y: (1 - phase) * 1.25,
    z: (1 - phase) * -7.4,
    scale: 0.5 + phase * 0.5,
    yaw: (1 - phase) * -0.9,
    pitch: Math.sin(phase * Math.PI) * 0.1,
    roll: Math.sin(phase * Math.PI) * -0.07,
  };
}
