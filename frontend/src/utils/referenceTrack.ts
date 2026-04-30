import type { TrackPoint, TrackType } from "../types/api";

export interface TrackGeometryConfig {
  circle_radius_m: number;
  u_turn_straight_length_m: number;
  u_turn_turn_radius_m: number;
  lemniscate_scale_m: number;
}

export const DEFAULT_TRACK_GEOMETRY: TrackGeometryConfig = {
  circle_radius_m: 5.0,
  u_turn_straight_length_m: 10.0,
  u_turn_turn_radius_m: 3.0,
  lemniscate_scale_m: 4.0,
};

export function generateReferenceTrack(
  trackType: Exclude<TrackType, "custom">,
  startX: number,
  startY: number,
  altitudeM: number,
  geometry: TrackGeometryConfig,
): TrackPoint[] {
  const points: TrackPoint[] = [];

  if (trackType === "circle") {
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
    return points;
  }

  if (trackType === "u_turn") {
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
    return points;
  }

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
  return points;
}
