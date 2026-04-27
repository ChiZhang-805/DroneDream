export interface ReplayPoint {
  t: number;
  x: number;
  y: number;
  z: number;
}

interface ProjectionBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  minZ: number;
  maxZ: number;
}

interface ViewBoxProjection {
  linePoints: string;
  markerX: (idx: number) => number;
  markerY: (idx: number) => number;
}

const VIEWBOX_SIZE = 100;
const VIEWBOX_PADDING = 8;

export function normalizePoint(raw: unknown, idx: number): ReplayPoint | null {
  if (!raw || typeof raw !== "object") return null;
  const sample = raw as Record<string, unknown>;
  const x = Number(sample.x);
  const y = Number(sample.y);
  const z = Number(sample.z ?? 0);
  const t = Number(sample.t ?? idx);

  if (![x, y, z, t].every(Number.isFinite)) return null;
  return { x, y, z, t };
}

export function extractPoints(payload: unknown): ReplayPoint[] {
  if (!payload || typeof payload !== "object") return [];

  const root = payload as Record<string, unknown>;
  const candidates: unknown[] = [
    root.samples,
    root.points,
    root.trajectory,
    root.path,
    root.reference_track,
  ];

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) continue;
    const parsed = candidate
      .map((item, idx) => normalizePoint(item, idx))
      .filter((item): item is ReplayPoint => item !== null);
    if (parsed.length > 0) return parsed;
  }

  return [];
}

export function extractReferencePoints(payload: unknown): ReplayPoint[] {
  if (!payload || typeof payload !== "object") return [];

  const root = payload as Record<string, unknown>;
  if (!Array.isArray(root.reference_track)) return [];

  return root.reference_track
    .map((item, idx) => normalizePoint(item, idx))
    .filter((item): item is ReplayPoint => item !== null);
}

function getProjectionBounds(points: ReplayPoint[]): ProjectionBounds {
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const zs = points.map((point) => point.z);

  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
    minZ: Math.min(...zs),
    maxZ: Math.max(...zs),
  };
}

function mapToViewBox(
  projected: Array<{ x: number; y: number }>,
): ViewBoxProjection {
  const xs = projected.map((point) => point.x);
  const ys = projected.map((point) => point.y);

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  const width = maxX - minX || 1;
  const height = maxY - minY || 1;

  const mapX = (x: number) =>
    ((x - minX) / width) * (VIEWBOX_SIZE - VIEWBOX_PADDING * 2) + VIEWBOX_PADDING;
  const mapY = (y: number) =>
    VIEWBOX_SIZE -
    (((y - minY) / height) * (VIEWBOX_SIZE - VIEWBOX_PADDING * 2) + VIEWBOX_PADDING);

  return {
    linePoints: projected.map((point) => `${mapX(point.x)},${mapY(point.y)}`).join(" "),
    markerX: (idx: number) => mapX(projected[idx]?.x ?? projected[0].x),
    markerY: (idx: number) => mapY(projected[idx]?.y ?? projected[0].y),
  };
}

export function to2DViewBoxCoordinates(points: ReplayPoint[]): ViewBoxProjection {
  return mapToViewBox(points.map((point) => ({ x: point.x, y: point.y })));
}

export function to3DViewBoxCoordinates(
  points: ReplayPoint[],
  bounds?: ProjectionBounds,
): ViewBoxProjection {
  const projectionBounds = bounds ?? getProjectionBounds(points);

  const rangeX = projectionBounds.maxX - projectionBounds.minX || 1;
  const rangeY = projectionBounds.maxY - projectionBounds.minY || 1;
  const rangeZ = projectionBounds.maxZ - projectionBounds.minZ || 1;

  const projected = points.map((point) => {
    const nx = (point.x - projectionBounds.minX) / rangeX;
    const ny = (point.y - projectionBounds.minY) / rangeY;
    const nz = (point.z - projectionBounds.minZ) / rangeZ;

    const isoX = (nx - ny) * 0.866;
    const isoY = (nx + ny) * 0.5 - nz * 0.9;

    return { x: isoX, y: isoY };
  });

  return mapToViewBox(projected);
}

export function getCombinedBounds(tracks: ReplayPoint[][]): ProjectionBounds | null {
  const allPoints = tracks.flat();
  if (allPoints.length === 0) return null;
  return getProjectionBounds(allPoints);
}
