import type { TrackPoint, TrackType } from "../types/api";

export interface TrackGeometryConfig {
  circle_radius_m: number;
  u_turn_straight_length_m: number;
  u_turn_turn_radius_m: number;
  lemniscate_scale_m: number;
}

/**
 * Build a local experiment preview in metres, not actuator commands or a qualified route.
 * Invalid/incomplete form data produces no polyline instead of invented geometry.
 */
export function generateReferenceTrack(
  trackType: Exclude<TrackType, "custom">,
  startX: number,
  startY: number,
  altitudeM: number,
  geometry: TrackGeometryConfig,
): TrackPoint[] {
  if (![startX, startY, altitudeM].every(Number.isFinite)) return [];
  if (!["hover", "circle", "u_turn", "lemniscate"].includes(trackType)) return [];
  const requiredLengths = trackType === "circle" ? [geometry.circle_radius_m]
    : trackType === "u_turn" ? [geometry.u_turn_straight_length_m, geometry.u_turn_turn_radius_m]
      : trackType === "lemniscate" ? [geometry.lemniscate_scale_m] : [];
  if (!requiredLengths.every((length) => Number.isFinite(length) && length > 0)) return [];
  const points: TrackPoint[] = [];

  if (trackType === "hover") {
    // Sampling count is a display contract; these points themselves have no timestamps.
    const sampleCount = 101;
    for (let i = 0; i < sampleCount; i += 1) {
      points.push({
        x: startX,
        y: startY,
        z: altitudeM,
      });
    }
    return finiteTrack(points);
  }

  if (trackType === "circle") {
    // startX/startY denote the circle's centre, not its first perimeter point.
    const radius = geometry.circle_radius_m;
    const n = 180;
    for (let i = 0; i <= n; i += 1) {
      const theta = 2 * Math.PI * (i / n);
      points.push({
        x: startX + radius * Math.cos(theta),
        y: startY + radius * Math.sin(theta),
        z: altitudeM,
      });
    }
    return finiteTrack(points);
  }

  if (trackType === "u_turn") {
    // Two straight lanes meet a semicircle with a common tangent; seam samples repeat.
    const laneHalf = geometry.u_turn_straight_length_m / 2;
    const turnRadius = geometry.u_turn_turn_radius_m;
    const nStraight = 60;
    const nArc = 60;

    for (let i = 0; i <= nStraight; i += 1) {
      points.push({
        x: startX - laneHalf + (2 * laneHalf * i) / nStraight,
        y: startY,
        z: altitudeM,
      });
    }
    for (let i = 0; i <= nArc; i += 1) {
      const theta = -Math.PI / 2 + (Math.PI * i) / nArc;
      points.push({
        x: startX + laneHalf + turnRadius * Math.cos(theta),
        y: startY + turnRadius + turnRadius * Math.sin(theta),
        z: altitudeM,
      });
    }
    for (let i = 0; i <= nStraight; i += 1) {
      points.push({
        x: startX + laneHalf - (2 * laneHalf * i) / nStraight,
        y: startY + 2 * turnRadius,
        z: altitudeM,
      });
    }
    return finiteTrack(points);
  }

  // The explicitly selected Bernoulli figure-eight closes after one 2π parameter cycle.
  const a = geometry.lemniscate_scale_m;
  const n = 220;
  for (let i = 0; i <= n; i += 1) {
    const t = 2 * Math.PI * (i / n);
    const denom = 1 + Math.sin(t) ** 2;
    points.push({
      x: startX + (a * Math.cos(t)) / denom,
      y: startY + (a * Math.sin(t) * Math.cos(t)) / denom,
      z: altitudeM,
    });
  }
  return finiteTrack(points);
}

/** Finite inputs can still overflow during addition; never display a partial invalid route. */
function finiteTrack(points: TrackPoint[]): TrackPoint[] {
  return points.every(({ x, y, z }) => [x, y, z].every(Number.isFinite)) ? points : [];
}
