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

function quadraticBezier(start: number, control: number, end: number, phase: number) {
  const inverse = 1 - phase;
  return inverse * inverse * start + 2 * inverse * phase * control + phase * phase * end;
}

export function getDroneStarflightPose(rawProgress: number): DroneStarflightPose {
  const progress = clamp(rawProgress);
  const outboundEnd = 0.22;
  const returnStart = 0.78;

  if (progress <= outboundEnd) {
    const phase = smoothStep(progress / outboundEnd);
    return {
      x: phase * 0.5,
      y: phase * 0.2,
      z: phase * -5.5,
      scale: 1 - phase * 0.43,
      yaw: phase * -0.82,
      pitch: Math.sin(phase * Math.PI) * -0.12,
      roll: Math.sin(phase * Math.PI) * 0.11,
    };
  }

  if (progress <= returnStart) {
    const phase = (progress - outboundEnd) / (returnStart - outboundEnd);
    const angle = phase * Math.PI;
    return {
      x: quadraticBezier(0.5, -6.25, -8, phase),
      y: quadraticBezier(0.2, 0.2, -0.6, phase),
      z: quadraticBezier(-5.5, -9, -4.5, phase),
      scale: 0.57 - Math.sin(angle) * 0.07,
      yaw: -0.82 - angle,
      pitch: Math.sin(angle) * 0.1,
      roll: Math.sin(angle * 2) * 0.13,
    };
  }

  const phase = smoothStep((progress - returnStart) / (1 - returnStart));
  return {
    x: -8 * (1 - phase),
    y: -0.6 * (1 - phase),
    z: -4.5 * (1 - phase),
    scale: 0.57 + phase * 0.43,
    yaw: (1 - phase) * (Math.PI - 0.82),
    pitch: Math.sin(phase * Math.PI) * 0.1,
    roll: Math.sin(phase * Math.PI) * -0.11,
  };
}
