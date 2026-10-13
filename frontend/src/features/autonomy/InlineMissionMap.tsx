import type { AgentCoreLiveTelemetry } from "./agentCore";
import type { AutonomyVector3 } from "./workspaceStore";

type PlanarPoint = { x: number; y: number };

function planarRoute(points: AutonomyVector3[]): PlanarPoint[] {
  return points.reduce<PlanarPoint[]>((result, point) => {
    const next = { x: point.x, y: -point.y };
    const previous = result.at(-1);
    if (!previous || Math.hypot(next.x - previous.x, next.y - previous.y) > 0.05) result.push(next);
    return result;
  }, []);
}

function routeViewBox(route: PlanarPoint[], bounds: AutonomyVector3) {
  const fallback = { x: -bounds.x / 2, y: -bounds.y / 2, width: bounds.x, height: bounds.y };
  if (route.length < 2) return fallback;
  const xs = route.map((point) => point.x);
  const ys = route.map((point) => point.y);
  let minX = Math.min(...xs) - 34;
  let maxX = Math.max(...xs) + 34;
  let minY = Math.min(...ys) - 28;
  let maxY = Math.max(...ys) + 28;
  const aspect = 16 / 9;
  const width = Math.max(110, maxX - minX);
  const height = Math.max(62, maxY - minY);
  if (width / height > aspect) {
    const desired = width / aspect;
    const grow = desired - height;
    minY -= grow / 2;
    maxY += grow / 2;
  } else {
    const desired = height * aspect;
    const grow = desired - width;
    minX -= grow / 2;
    maxX += grow / 2;
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

function pointDistance(left: PlanarPoint, right: PlanarPoint) {
  return Math.hypot(left.x - right.x, left.y - right.y);
}

export function InlineMissionMap({
  chinese,
  routePositions,
  telemetry,
  bounds,
  previewUrl,
}: {
  chinese: boolean;
  routePositions: AutonomyVector3[];
  telemetry: AgentCoreLiveTelemetry | null;
  bounds: AutonomyVector3;
  previewUrl: string | null;
}) {
  const route = planarRoute(routePositions);
  const view = routeViewBox(route, bounds);
  const start = route[0] ?? null;
  const roundTrip = Boolean(start && route.length > 2 && pointDistance(start, route.at(-1)!) < 2);
  const destinationIndex = start && roundTrip
    ? route.reduce((best, point, index) => pointDistance(start, point) > pointDistance(start, route[best]) ? index : best, 0)
    : Math.max(0, route.length - 1);
  const destination = route[destinationIndex] ?? null;
  const outbound = route.slice(0, destinationIndex + 1);
  const intermediate = outbound.length > 2 ? outbound[Math.floor((outbound.length - 1) / 2)] : null;
  const aircraft = telemetry && typeof telemetry.east_m === "number" && typeof telemetry.north_m === "number"
    ? { x: telemetry.east_m, y: -telemetry.north_m }
    : null;
  const fontSize = Math.max(6.5, Math.min(9, view.width * 0.045));
  const markerRadius = Math.max(2.8, Math.min(4.6, view.width * 0.02));
  const points = route.map((point) => `${point.x},${point.y}`).join(" ");

  const marker = (point: PlanarPoint | null, kind: "start" | "via" | "destination", label: string) => point ? (
    <g className={`autonomy-inline-map-marker is-${kind}`} transform={`translate(${point.x} ${point.y})`}>
      <circle r={markerRadius * 1.85} className="autonomy-inline-map-marker-halo" />
      <circle r={markerRadius} className="autonomy-inline-map-marker-core" />
      <text x={markerRadius * 1.75} y={-markerRadius * 1.4} style={{ fontSize }}>{label}</text>
    </g>
  ) : null;

  return (
    <svg
      className="autonomy-inline-mission-map"
      viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`}
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label={chinese ? "二维任务地图" : "2D mission map"}
    >
      {previewUrl ? (
        <image
          href={previewUrl}
          x={-bounds.x / 2}
          y={-bounds.y / 2}
          width={bounds.x}
          height={bounds.y}
          preserveAspectRatio="none"
        />
      ) : <rect x={-bounds.x / 2} y={-bounds.y / 2} width={bounds.x} height={bounds.y} className="autonomy-inline-map-fallback" />}
      <rect x={view.x} y={view.y} width={view.width} height={view.height} className="autonomy-inline-map-shade" />
      {points ? <>
        <polyline className="autonomy-inline-map-route-shadow" points={points} />
        <polyline className="autonomy-inline-map-route" points={points} />
      </> : null}
      {marker(start, "start", roundTrip ? (chinese ? "起点 / 返航" : "Start / return") : (chinese ? "起点" : "Start"))}
      {intermediate && destination && pointDistance(intermediate, start!) > 8 && pointDistance(intermediate, destination) > 8
        ? marker(intermediate, "via", chinese ? "中转点" : "Waypoint")
        : null}
      {marker(destination, "destination", chinese ? "终点" : "Destination")}
      {aircraft ? (
        <g className="autonomy-inline-map-aircraft" transform={`translate(${aircraft.x} ${aircraft.y})`}>
          <circle r={markerRadius * 2.6} />
          <path d={`M 0 ${-markerRadius * 1.2} L ${markerRadius * 0.95} ${markerRadius} L 0 ${markerRadius * 0.62} L ${-markerRadius * 0.95} ${markerRadius} Z`} />
          <text x={markerRadius * 1.75} y={markerRadius * 0.5} style={{ fontSize }}>{chinese ? "无人机" : "Aircraft"}</text>
        </g>
      ) : null}
    </svg>
  );
}
