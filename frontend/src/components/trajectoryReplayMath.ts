export interface ReplayPoint {
  t: number;
  x: number;
  y: number;
  z: number;
}

export interface ProjectionBounds {
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
  bounds?: { minX: number; maxX: number; minY: number; maxY: number },
): ViewBoxProjection {
  if (projected.length === 0) {
    return {
      linePoints: "",
      markerX: () => VIEWBOX_SIZE / 2,
      markerY: () => VIEWBOX_SIZE / 2,
    };
  }

  const xs = projected.map((point) => point.x);
  const ys = projected.map((point) => point.y);

  const minX = bounds?.minX ?? Math.min(...xs);
  const maxX = bounds?.maxX ?? Math.max(...xs);
  const minY = bounds?.minY ?? Math.min(...ys);
  const maxY = bounds?.maxY ?? Math.max(...ys);

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

export function to2DViewBoxCoordinates(
  points: ReplayPoint[],
  bounds?: ProjectionBounds,
): ViewBoxProjection {
  return mapToViewBox(
    points.map((point) => ({ x: point.x, y: point.y })),
    bounds
      ? {
          minX: bounds.minX,
          maxX: bounds.maxX,
          minY: bounds.minY,
          maxY: bounds.maxY,
        }
      : undefined,
  );
}

export function to3DProjectedCoordinates(
  points: ReplayPoint[],
  bounds?: ProjectionBounds,
): ViewBoxProjection {
  const projected = points.map((point) => ({
    x: point.x - point.y * 0.5,
    y: -point.z + (point.x + point.y) * 0.25,
  }));

  let projectedBounds:
    | { minX: number; maxX: number; minY: number; maxY: number }
    | undefined;
  if (bounds) {
    // Project every corner of the shared XYZ bounding box. The isometric
    // projection is linear, so its extrema are guaranteed to occur at one of
    // these corners. This keeps actual and reference tracks on one scale.
    const corners = [bounds.minX, bounds.maxX].flatMap((x) =>
      [bounds.minY, bounds.maxY].flatMap((y) =>
        [bounds.minZ, bounds.maxZ].map((z) => ({
          x: x - y * 0.5,
          y: -z + (x + y) * 0.25,
        })),
      ),
    );
    const xs = corners.map((point) => point.x);
    const ys = corners.map((point) => point.y);
    projectedBounds = {
      minX: Math.min(...xs),
      maxX: Math.max(...xs),
      minY: Math.min(...ys),
      maxY: Math.max(...ys),
    };
  }

  return mapToViewBox(projected, projectedBounds);
}

export function getCombinedBounds(tracks: ReplayPoint[][]): ProjectionBounds | null {
  const allPoints = tracks.flat();
  if (allPoints.length === 0) return null;
  return getProjectionBounds(allPoints);
}
