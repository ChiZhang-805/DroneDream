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
  const x = sample.x;
  const y = sample.y;
  const z = sample.z === undefined ? 0 : sample.z;
  const t = sample.t === undefined ? idx : sample.t;

  if (
    typeof x !== "number"
    || typeof y !== "number"
    || typeof z !== "number"
    || typeof t !== "number"
    || ![x, y, z, t].every(Number.isFinite)
  ) {
    return null;
  }
  return { x, y, z, t };
}

function parsePointArray(candidate: unknown[]): ReplayPoint[] {
  const parsed = candidate.map((item, idx) => normalizePoint(item, idx));
  if (parsed.some((item) => item === null)) return [];
  const points = parsed as ReplayPoint[];
  if (points.some((point, index) => index > 0 && point.t <= points[index - 1].t)) {
    return [];
  }
  return points;
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
    // The first declared trajectory field is authoritative. If it is empty or
    // corrupt, fail closed instead of silently drawing a lower-priority field
    // (especially an embedded reference track) as the actual flight.
    return parsePointArray(candidate);
  }

  return [];
}

export function extractReferencePoints(payload: unknown): ReplayPoint[] {
  if (!payload || typeof payload !== "object") return [];

  const root = payload as Record<string, unknown>;
  if (!Array.isArray(root.reference_track)) return [];

  return parsePointArray(root.reference_track);
}

function getProjectionBounds(points: ReplayPoint[]): ProjectionBounds {
  const first = points[0];
  return points.slice(1).reduce<ProjectionBounds>(
    (bounds, point) => ({
      minX: Math.min(bounds.minX, point.x),
      maxX: Math.max(bounds.maxX, point.x),
      minY: Math.min(bounds.minY, point.y),
      maxY: Math.max(bounds.maxY, point.y),
      minZ: Math.min(bounds.minZ, point.z),
      maxZ: Math.max(bounds.maxZ, point.z),
    }),
    {
      minX: first.x,
      maxX: first.x,
      minY: first.y,
      maxY: first.y,
      minZ: first.z,
      maxZ: first.z,
    },
  );
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

  const projectedBounds = projected.slice(1).reduce(
    (current, point) => ({
      minX: Math.min(current.minX, point.x),
      maxX: Math.max(current.maxX, point.x),
      minY: Math.min(current.minY, point.y),
      maxY: Math.max(current.maxY, point.y),
    }),
    {
      minX: projected[0].x,
      maxX: projected[0].x,
      minY: projected[0].y,
      maxY: projected[0].y,
    },
  );
  const minX = bounds?.minX ?? projectedBounds.minX;
  const maxX = bounds?.maxX ?? projectedBounds.maxX;
  const minY = bounds?.minY ?? projectedBounds.minY;
  const maxY = bounds?.maxY ?? projectedBounds.maxY;

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
  const populatedTracks = tracks.filter((track) => track.length > 0);
  if (populatedTracks.length === 0) return null;
  return populatedTracks
    .map(getProjectionBounds)
    .slice(1)
    .reduce<ProjectionBounds>(
      (combined, bounds) => ({
        minX: Math.min(combined.minX, bounds.minX),
        maxX: Math.max(combined.maxX, bounds.maxX),
        minY: Math.min(combined.minY, bounds.minY),
        maxY: Math.max(combined.maxY, bounds.maxY),
        minZ: Math.min(combined.minZ, bounds.minZ),
        maxZ: Math.max(combined.maxZ, bounds.maxZ),
      }),
      getProjectionBounds(populatedTracks[0]),
    );
}
