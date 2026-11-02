import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import type { TrackPoint, TrackType } from "../../types/api";

interface ExperienceTrackPreviewProps {
  trackType: TrackType;
  points: TrackPoint[];
  altitudeM: number;
  title: string;
  hoverLabel: string;
  routeLabel: string;
  pointCountLabel: string;
  localOnlyLabel: string;
}

type PreviewView = "3d" | "xy" | "xz" | "yz";

interface WorldPoint {
  x: number;
  y: number;
  z: number;
}

interface ProjectedPoint {
  x: number;
  y: number;
}

interface PreviewGeometry {
  floor: string;
  gridLines: Array<{ start: ProjectedPoint; end: ProjectedPoint }>;
  route: string;
  shadow: string;
  start: ProjectedPoint;
  end: ProjectedPoint;
}

const VIEWBOX_WIDTH = 320;
const VIEWBOX_HEIGHT = 180;
const PADDING = 24;
const PREVIEW_VIEWS: readonly PreviewView[] = ["3d", "xy", "xz", "yz"];

function finiteWorldPoints(points: TrackPoint[], altitudeM: number): WorldPoint[] {
  const fallbackAltitude = Number.isFinite(altitudeM) ? altitudeM : 0;
  return points.flatMap((point) => {
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) return [];
    return [{
      x: point.x,
      y: point.y,
      z: Number.isFinite(point.z) ? Number(point.z) : fallbackAltitude,
    }];
  });
}

function expandedBounds(values: number[], minimumSpan: number): [number, number] {
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  if (maximum - minimum >= minimumSpan) return [minimum, maximum];
  const midpoint = (minimum + maximum) / 2;
  return [midpoint - minimumSpan / 2, midpoint + minimumSpan / 2];
}

function rawProjection(point: WorldPoint, view: PreviewView): ProjectedPoint {
  if (view === "xy") return { x: point.x, y: point.y };
  if (view === "xz") return { x: point.x, y: point.z };
  if (view === "yz") return { x: point.y, y: point.z };
  return {
    x: (point.x - point.y) * 0.88,
    y: (point.x + point.y) * 0.38 + point.z * 1.32,
  };
}

function previewGeometry(
  points: WorldPoint[],
  altitudeM: number,
  isHover: boolean,
  view: PreviewView,
): PreviewGeometry | null {
  if (points.length === 0 && !isHover) return null;
  const altitude = Math.max(0.5, Number.isFinite(altitudeM) ? altitudeM : 0);
  const routePoints = isHover
    ? [{ x: 0, y: 0, z: 0 }, { x: 0, y: 0, z: altitude }]
    : points[0]?.z > 0
      ? [{ ...points[0], z: 0 }, ...points]
      : points;
  if (routePoints.length === 0) return null;
  const [minX, maxX] = expandedBounds(routePoints.map((point) => point.x), 6);
  const [minY, maxY] = expandedBounds(routePoints.map((point) => point.y), 6);
  const maxZ = Math.max(altitude, ...routePoints.map((point) => point.z), 1);
  const groundCorners: WorldPoint[] = [
    { x: minX, y: minY, z: 0 },
    { x: maxX, y: minY, z: 0 },
    { x: maxX, y: maxY, z: 0 },
    { x: minX, y: maxY, z: 0 },
  ];
  const gridWorldLines: Array<{ start: WorldPoint; end: WorldPoint }> = [];
  for (let index = 0; index <= 4; index += 1) {
    const progress = index / 4;
    if (view === "3d" || view === "xy") {
      const x = minX + (maxX - minX) * progress;
      const y = minY + (maxY - minY) * progress;
      gridWorldLines.push(
        { start: { x, y: minY, z: 0 }, end: { x, y: maxY, z: 0 } },
        { start: { x: minX, y, z: 0 }, end: { x: maxX, y, z: 0 } },
      );
    } else {
      const horizontalMinimum = view === "xz" ? minX : minY;
      const horizontalMaximum = view === "xz" ? maxX : maxY;
      const horizontal = horizontalMinimum + (horizontalMaximum - horizontalMinimum) * progress;
      const z = maxZ * progress;
      const makePoint = (horizontalValue: number, zValue: number): WorldPoint => view === "xz"
        ? { x: horizontalValue, y: 0, z: zValue }
        : { x: 0, y: horizontalValue, z: zValue };
      gridWorldLines.push(
        { start: makePoint(horizontal, 0), end: makePoint(horizontal, maxZ) },
        { start: makePoint(horizontalMinimum, z), end: makePoint(horizontalMaximum, z) },
      );
    }
  }
  const shadowPoints = routePoints.map((point) => ({ ...point, z: 0 }));
  const projectionInputs = [
    ...groundCorners,
    ...routePoints,
    ...shadowPoints,
    ...gridWorldLines.flatMap((line) => [line.start, line.end]),
  ].map((point) => rawProjection(point, view));
  const minProjectedX = Math.min(...projectionInputs.map((point) => point.x));
  const maxProjectedX = Math.max(...projectionInputs.map((point) => point.x));
  const minProjectedY = Math.min(...projectionInputs.map((point) => point.y));
  const maxProjectedY = Math.max(...projectionInputs.map((point) => point.y));
  const spanX = Math.max(maxProjectedX - minProjectedX, 1);
  const spanY = Math.max(maxProjectedY - minProjectedY, 1);
  const scale = Math.min(
    (VIEWBOX_WIDTH - 2 * PADDING) / spanX,
    (VIEWBOX_HEIGHT - 2 * PADDING) / spanY,
  );
  const offsetX = (VIEWBOX_WIDTH - spanX * scale) / 2;
  const offsetY = (VIEWBOX_HEIGHT - spanY * scale) / 2;
  const project = (point: WorldPoint): ProjectedPoint => {
    const raw = rawProjection(point, view);
    return {
      x: offsetX + (raw.x - minProjectedX) * scale,
      y: VIEWBOX_HEIGHT - (offsetY + (raw.y - minProjectedY) * scale),
    };
  };
  const polyline = (values: WorldPoint[]) => values
    .map((point) => {
      const projected = project(point);
      return `${projected.x.toFixed(2)},${projected.y.toFixed(2)}`;
    })
    .join(" ");
  return {
    floor: polyline(groundCorners),
    gridLines: gridWorldLines.map((line) => ({
      start: project(line.start),
      end: project(line.end),
    })),
    route: polyline(routePoints),
    shadow: polyline(shadowPoints),
    start: project(routePoints[0]),
    end: project(routePoints.at(-1) ?? routePoints[0]),
  };
}

export function ExperienceTrackPreview({
  trackType,
  points,
  altitudeM,
  title,
  hoverLabel,
  routeLabel,
  pointCountLabel,
  localOnlyLabel,
}: ExperienceTrackPreviewProps) {
  const { t } = useI18n();
  const [view, setView] = useState<PreviewView>("3d");
  const isHover = trackType === "hover";
  const safePoints = useMemo(
    () => finiteWorldPoints(points, altitudeM),
    [altitudeM, points],
  );
  const geometry = useMemo(
    () => previewGeometry(safePoints, altitudeM, isHover, view),
    [altitudeM, isHover, safePoints, view],
  );
  const viewLabel = t(`track.view.${view}`);
  const changeView = (offset: number) => {
    const current = PREVIEW_VIEWS.indexOf(view);
    setView(PREVIEW_VIEWS[(current + offset + PREVIEW_VIEWS.length) % PREVIEW_VIEWS.length]);
  };

  return (
    <figure className="experience-preview" aria-label={title}>
      <figcaption>
        <strong>{title}</strong>
        <div className="experience-preview-view-switcher" role="group" aria-label={t("track.viewSwitcher")}>
          <button type="button" onClick={() => changeView(-1)} aria-label={t("track.previousView")}>
            <ChevronLeft aria-hidden="true" />
          </button>
          <span aria-live="polite">{viewLabel}</span>
          <button type="button" onClick={() => changeView(1)} aria-label={t("track.nextView")}>
            <ChevronRight aria-hidden="true" />
          </button>
        </div>
      </figcaption>
      <svg
        className="experience-preview-canvas"
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        role="img"
        aria-label={`${viewLabel}: ${isHover ? hoverLabel : routeLabel}`}
        data-view={view}
      >
        <rect className="experience-preview-bg" width={VIEWBOX_WIDTH} height={VIEWBOX_HEIGHT} rx="12" />
        {geometry ? (
          <>
            <polygon className="experience-preview-floor" points={geometry.floor} />
            <g className="experience-preview-grid" aria-hidden="true">
              {geometry.gridLines.map((line, index) => (
                <line
                  key={`${view}-${index}`}
                  x1={line.start.x}
                  y1={line.start.y}
                  x2={line.end.x}
                  y2={line.end.y}
                />
              ))}
            </g>
            {view === "3d" ? <polyline className="experience-preview-shadow" points={geometry.shadow} /> : null}
            <g data-testid={isHover ? "hover-preview" : "route-preview"}>
              <polyline className={isHover ? "experience-preview-climb" : "experience-preview-route"} points={geometry.route} />
              {isHover ? <ellipse className="experience-preview-hover-ring" cx={geometry.end.x} cy={geometry.end.y} rx="15" ry={view === "3d" ? "7" : "15"} /> : null}
              <circle className="experience-preview-start" cx={geometry.start.x} cy={geometry.start.y} r="4" />
              <circle className="experience-preview-marker" cx={geometry.end.x} cy={geometry.end.y} r="5" />
            </g>
          </>
        ) : (
          <text className="experience-preview-empty" x="160" y="94" textAnchor="middle">—</text>
        )}
      </svg>
      <span className="sr-only">{pointCountLabel}. {localOnlyLabel}</span>
    </figure>
  );
}
