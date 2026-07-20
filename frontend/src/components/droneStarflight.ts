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

type Point3 = { x: number; y: number; z: number };

const REMOTE_ARC_START: Point3 = { x: 0.5, y: 0.2, z: -5.5 };
const REMOTE_ARC_CONTROL: Point3 = { x: -6.25, y: 0.2, z: -9 };
const REMOTE_ARC_END: Point3 = { x: -8, y: -0.6, z: -4.5 };
// Dense arc-length sampling keeps the remote half-orbit visually uniform even
// on high-refresh displays, where a coarse lookup table can expose tiny speed
// changes between adjacent Bézier segments.
const REMOTE_ARC_SAMPLES = 512;

function clamp(value: number) {
  if (!Number.isFinite(value)) return value === Number.POSITIVE_INFINITY ? 1 : 0;
  return Math.min(1, Math.max(0, value));
}

function smoothStep(value: number) {
  const clamped = clamp(value);
  return clamped * clamped * (3 - 2 * clamped);
}

function smootherStep(value: number) {
  const clamped = clamp(value);
  return clamped * clamped * clamped * (clamped * (clamped * 6 - 15) + 10);
}

function quadraticBezier(start: number, control: number, end: number, phase: number) {
  const inverse = 1 - phase;
  return inverse * inverse * start + 2 * inverse * phase * control + phase * phase * end;
}

function remoteArcPoint(phase: number): Point3 {
  return {
    x: quadraticBezier(REMOTE_ARC_START.x, REMOTE_ARC_CONTROL.x, REMOTE_ARC_END.x, phase),
    y: quadraticBezier(REMOTE_ARC_START.y, REMOTE_ARC_CONTROL.y, REMOTE_ARC_END.y, phase),
    z: quadraticBezier(REMOTE_ARC_START.z, REMOTE_ARC_CONTROL.z, REMOTE_ARC_END.z, phase),
  };
}

function pointDistance(first: Point3, second: Point3) {
  return Math.hypot(second.x - first.x, second.y - first.y, second.z - first.z);
}

const remoteArcLengths = (() => {
  const lengths = [0];
  let previous = remoteArcPoint(0);
  for (let index = 1; index <= REMOTE_ARC_SAMPLES; index += 1) {
    const point = remoteArcPoint(index / REMOTE_ARC_SAMPLES);
    lengths.push(lengths[index - 1] + pointDistance(previous, point));
    previous = point;
  }
  return lengths;
})();

function remoteArcPhaseAtDistance(rawDistanceProgress: number) {
  const distanceProgress = clamp(rawDistanceProgress);
  const totalLength = remoteArcLengths[REMOTE_ARC_SAMPLES];
  const targetLength = totalLength * distanceProgress;
  let low = 0;
  let high = REMOTE_ARC_SAMPLES;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (remoteArcLengths[middle] < targetLength) low = middle + 1;
    else high = middle;
  }
  const upperIndex = Math.max(1, low);
  const lowerIndex = upperIndex - 1;
  const lowerLength = remoteArcLengths[lowerIndex];
  const segmentLength = remoteArcLengths[upperIndex] - lowerLength;
  const segmentProgress = segmentLength > 0
    ? (targetLength - lowerLength) / segmentLength
    : 0;
  return (lowerIndex + segmentProgress) / REMOTE_ARC_SAMPLES;
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
    const timeProgress = (progress - outboundEnd) / (returnStart - outboundEnd);
    const distanceProgress = smootherStep(timeProgress);
    const phase = remoteArcPhaseAtDistance(distanceProgress);
    const point = remoteArcPoint(phase);
    const angle = distanceProgress * Math.PI;
    return {
      ...point,
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
