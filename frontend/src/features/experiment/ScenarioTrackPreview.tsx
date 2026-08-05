import { useId, useMemo, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  WheelEvent as ReactWheelEvent,
} from "react";

import type { TrackPoint } from "../../types/api";
import { useI18n } from "../../i18n/I18nProvider";

type Axis = "x" | "y" | "z";
type PlanarScenarioTrackView = "xy" | "xz" | "yz";
type ScenarioTrackView = PlanarScenarioTrackView | "3d";

interface ScenarioTrackPreviewProps {
  points: TrackPoint[];
  defaultAltitude: number;
  title: string;
}

interface AxisBounds {
  min: number;
  max: number;
}

interface ProjectedPoint {
  x: number;
  y: number;
  depth?: number;
}

interface ThreeDimensionalGridSpec {
  x: AxisBounds;
  y: AxisBounds;
  xValues: number[];
  yValues: number[];
}

const VIEWBOX_WIDTH = 420;
const VIEWBOX_HEIGHT = 260;
const PADDING_X = 34;
const PADDING_Y = 30;
const VIEW_ORDER: readonly ScenarioTrackView[] = ["xy", "xz", "yz", "3d"];
const PLANAR_AXES: Record<PlanarScenarioTrackView, readonly [Axis, Axis]> = {
  xy: ["x", "y"],
  xz: ["x", "z"],
  yz: ["y", "z"],
};
const INITIAL_CAMERA = { yaw: -0.72, pitch: 0.58, zoom: 1.22 };

function finite(value: number | null | undefined, fallback = 0): number {
  return Number.isFinite(value) ? Number(value) : fallback;
}

function axisValue(point: TrackPoint, axis: Axis, defaultAltitude: number): number {
  return finite(point[axis], axis === "z" ? defaultAltitude : 0);
}

function niceGridStep(span: number): number {
  const rawStep = Math.max(span, 1) / 7;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return multiplier * magnitude;
}

function gridValues(min: number, max: number, step: number): number[] {
  const count = Math.round((max - min) / step);
  return Array.from({ length: count + 1 }, (_value, index) => min + index * step);
}

function fitProjection(rawPoints: ProjectedPoint[]): ProjectedPoint[] {
  if (rawPoints.length === 0) return [];
  const xs = rawPoints.map((point) => point.x);
  const ys = rawPoints.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const scale = Math.min(
    (VIEWBOX_WIDTH - PADDING_X * 2) / spanX,
    (VIEWBOX_HEIGHT - PADDING_Y * 2) / spanY,
  );
  const offsetX = (VIEWBOX_WIDTH - spanX * scale) / 2;
  const offsetY = (VIEWBOX_HEIGHT - spanY * scale) / 2;
  return rawPoints.map((point) => ({
    x: offsetX + (point.x - minX) * scale,
    y: VIEWBOX_HEIGHT - (offsetY + (point.y - minY) * scale),
  }));
}

function projectPlanarPoints(
  points: TrackPoint[],
  view: PlanarScenarioTrackView,
  defaultAltitude: number,
): ProjectedPoint[] {
  const [horizontalAxis, verticalAxis] = PLANAR_AXES[view];
  return fitProjection(points.map((point) => ({
    x: axisValue(point, horizontalAxis, defaultAltitude),
    y: axisValue(point, verticalAxis, defaultAltitude),
  })));
}

function axisLabels(view: PlanarScenarioTrackView): readonly [string, string] {
  if (view === "xy") return ["X", "Y"];
  if (view === "xz") return ["X", "Z"];
  return ["Y", "Z"];
}

export function ScenarioTrackPreview({
  points,
  defaultAltitude,
  title,
}: ScenarioTrackPreviewProps) {
  const { t } = useI18n();
  const instanceId = useId().replace(/:/gu, "");
  const rotationDrag = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    yaw: number;
    pitch: number;
  } | null>(null);
  const [view, setView] = useState<ScenarioTrackView>("3d");
  const [camera, setCamera] = useState(INITIAL_CAMERA);
  const [isRotating, setIsRotating] = useState(false);

  const bounds = useMemo<Record<Axis, AxisBounds>>(() => {
    const horizontalBounds = (axis: "x" | "y"): AxisBounds => {
      const values = points.map((point) => axisValue(point, axis, defaultAltitude));
      const min = Math.min(-5, ...values);
      const max = Math.max(5, ...values);
      const pad = Math.max(1.5, (max - min) * 0.12);
      return { min: min - pad, max: max + pad };
    };
    const zValues = points.map((point) => axisValue(point, "z", defaultAltitude));
    const zMax = Math.max(6, defaultAltitude * 1.7, ...zValues);
    return {
      x: horizontalBounds("x"),
      y: horizontalBounds("y"),
      z: { min: 0, max: zMax + Math.max(1, zMax * 0.12) },
    };
  }, [defaultAltitude, points]);

  const threeDimensionalGridSpec = useMemo<ThreeDimensionalGridSpec>(() => {
    const step = niceGridStep(Math.max(
      bounds.x.max - bounds.x.min,
      bounds.y.max - bounds.y.min,
    ));
    const x = {
      min: Math.floor(bounds.x.min / step) * step,
      max: Math.ceil(bounds.x.max / step) * step,
    };
    const y = {
      min: Math.floor(bounds.y.min / step) * step,
      max: Math.ceil(bounds.y.max / step) * step,
    };
    return {
      x,
      y,
      xValues: gridValues(x.min, x.max, step),
      yValues: gridValues(y.min, y.max, step),
    };
  }, [bounds]);

  const projectThreeDimensionalPoint = useMemo(() => {
    const centers: Record<Axis, number> = {
      x: (threeDimensionalGridSpec.x.min + threeDimensionalGridSpec.x.max) / 2,
      y: (threeDimensionalGridSpec.y.min + threeDimensionalGridSpec.y.max) / 2,
      z: (bounds.z.min + bounds.z.max) / 2,
    };
    const span = Math.max(
      threeDimensionalGridSpec.x.max - threeDimensionalGridSpec.x.min,
      threeDimensionalGridSpec.y.max - threeDimensionalGridSpec.y.min,
      bounds.z.max - bounds.z.min,
      1,
    );
    const scale = Math.min(VIEWBOX_WIDTH, VIEWBOX_HEIGHT) * 0.73 * camera.zoom;
    const cosYaw = Math.cos(camera.yaw);
    const sinYaw = Math.sin(camera.yaw);
    const cosPitch = Math.cos(camera.pitch);
    const sinPitch = Math.sin(camera.pitch);

    return (coordinate: Record<Axis, number>): ProjectedPoint => {
      const x = (coordinate.x - centers.x) / span;
      const y = (coordinate.y - centers.y) / span;
      const z = (coordinate.z - centers.z) / span;
      const rotatedX = cosYaw * x - sinYaw * y;
      const rotatedY = sinYaw * x + cosYaw * y;
      const depth = rotatedY * cosPitch + z * sinPitch;
      const perspective = 1 / Math.max(0.78, 1 + depth * 0.18);
      return {
        x: VIEWBOX_WIDTH / 2 + rotatedX * scale * perspective,
        y: VIEWBOX_HEIGHT / 2 + (rotatedY * sinPitch - z * cosPitch) * scale * perspective,
        depth,
      };
    };
  }, [bounds.z.max, bounds.z.min, camera, threeDimensionalGridSpec]);

  const threeDimensionalScene = useMemo(() => {
    const project = (point: TrackPoint, ground = false) => projectThreeDimensionalPoint({
      x: axisValue(point, "x", defaultAltitude),
      y: axisValue(point, "y", defaultAltitude),
      z: ground ? bounds.z.min : axisValue(point, "z", defaultAltitude),
    });
    const route = points.map((point) => project(point));
    const shadow = points.map((point) => project(point, true));
    const grid = {
      xLines: threeDimensionalGridSpec.xValues.map((x) => [
        projectThreeDimensionalPoint({ x, y: threeDimensionalGridSpec.y.min, z: bounds.z.min }),
        projectThreeDimensionalPoint({ x, y: threeDimensionalGridSpec.y.max, z: bounds.z.min }),
      ]),
      yLines: threeDimensionalGridSpec.yValues.map((y) => [
        projectThreeDimensionalPoint({ x: threeDimensionalGridSpec.x.min, y, z: bounds.z.min }),
        projectThreeDimensionalPoint({ x: threeDimensionalGridSpec.x.max, y, z: bounds.z.min }),
      ]),
    };
    const origin = {
      x: threeDimensionalGridSpec.x.min,
      y: threeDimensionalGridSpec.y.min,
      z: bounds.z.min,
    };
    const axes = ([
      { axis: "x", end: { ...origin, x: threeDimensionalGridSpec.x.max } },
      { axis: "y", end: { ...origin, y: threeDimensionalGridSpec.y.max } },
      { axis: "z", end: { ...origin, z: bounds.z.max } },
    ] as const).map(({ axis, end }) => ({
      axis,
      start: projectThreeDimensionalPoint(origin),
      end: projectThreeDimensionalPoint(end),
    }));
    const groundCorners = [
      projectThreeDimensionalPoint(origin),
      projectThreeDimensionalPoint({ ...origin, x: threeDimensionalGridSpec.x.max }),
      projectThreeDimensionalPoint({
        ...origin,
        x: threeDimensionalGridSpec.x.max,
        y: threeDimensionalGridSpec.y.max,
      }),
      projectThreeDimensionalPoint({ ...origin, y: threeDimensionalGridSpec.y.max }),
    ];
    return { route, shadow, grid, axes, groundCorners };
  }, [bounds.z.max, bounds.z.min, defaultAltitude, points, projectThreeDimensionalPoint, threeDimensionalGridSpec]);

  const planarProjected = useMemo(
    () => view === "3d" ? [] : projectPlanarPoints(points, view, defaultAltitude),
    [defaultAltitude, points, view],
  );
  const projected = view === "3d" ? threeDimensionalScene.route : planarProjected;
  const polyline = projected.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const shadowPolyline = threeDimensionalScene.shadow
    .map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(" ");
  const groundPolygon = threeDimensionalScene.groundCorners
    .map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(" ");
  const firstPoint = projected[0];
  const [horizontalLabel, verticalLabel] = view === "3d" ? ["", ""] : axisLabels(view);
  const gradientId = `scenario-track-gradient-${instanceId}-${view}`;
  const glowId = `scenario-track-glow-${instanceId}-${view}`;

  function stopRotation(): void {
    rotationDrag.current = null;
    setIsRotating(false);
  }

  function handlePointerDown(event: ReactPointerEvent<SVGSVGElement>): void {
    if (view !== "3d") return;
    rotationDrag.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      yaw: camera.yaw,
      pitch: camera.pitch,
    };
    setIsRotating(true);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>): void {
    if (view !== "3d") return;
    const origin = rotationDrag.current;
    if (!origin || origin.pointerId !== event.pointerId) return;
    setCamera((current) => ({
      ...current,
      yaw: origin.yaw + (event.clientX - origin.clientX) * 0.008,
      pitch: Math.max(
        0.15,
        Math.min(1.35, origin.pitch - (event.clientY - origin.clientY) * 0.006),
      ),
    }));
  }

  function handleWheel(event: ReactWheelEvent<SVGSVGElement>): void {
    if (view !== "3d") return;
    event.preventDefault();
    setCamera((current) => ({
      ...current,
      zoom: Math.max(0.65, Math.min(2.2, current.zoom * (event.deltaY > 0 ? 0.9 : 1.1))),
    }));
  }

  function handleKeyDown(event: ReactKeyboardEvent<SVGSVGElement>): void {
    if (view !== "3d") return;
    const rotationKeys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"];
    const zoomKeys = ["+", "=", "-", "_"];
    if (![...rotationKeys, ...zoomKeys, "Home"].includes(event.key)) return;
    event.preventDefault();
    if (event.key === "Home") {
      setCamera(INITIAL_CAMERA);
      return;
    }
    setCamera((current) => ({
      yaw: current.yaw + (event.key === "ArrowLeft" ? -0.1 : event.key === "ArrowRight" ? 0.1 : 0),
      pitch: Math.max(
        0.15,
        Math.min(1.35, current.pitch + (event.key === "ArrowUp" ? 0.08 : event.key === "ArrowDown" ? -0.08 : 0)),
      ),
      zoom: Math.max(
        0.65,
        Math.min(2.2, current.zoom * (event.key === "+" || event.key === "=" ? 1.1 : event.key === "-" || event.key === "_" ? 0.9 : 1)),
      ),
    }));
  }

  return (
    <figure
      className="scenario-track-preview"
      data-view={view}
      data-camera-yaw={camera.yaw.toFixed(3)}
      data-camera-pitch={camera.pitch.toFixed(3)}
      data-camera-zoom={camera.zoom.toFixed(3)}
      aria-label={title}
    >
      <div className="scenario-track-view-switcher" role="group" aria-label={t("track.viewSwitcher")}>
        {VIEW_ORDER.map((candidate) => (
          <button
            key={candidate}
            type="button"
            className={candidate === view ? "is-active" : ""}
            aria-pressed={candidate === view}
            aria-label={t(`track.view.${candidate}`)}
            onClick={() => {
              stopRotation();
              setView(candidate);
            }}
          >
            {candidate.toUpperCase()}
          </button>
        ))}
      </div>
      <svg
        className={`scenario-track-canvas ${view === "3d" ? "scenario-track-canvas-3d" : ""} ${isRotating ? "is-rotating" : ""}`}
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        role="group"
        tabIndex={view === "3d" ? 0 : undefined}
        aria-label={`${title} - ${t(`track.view.${view}`)}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={stopRotation}
        onPointerCancel={stopRotation}
        onWheel={handleWheel}
        onKeyDown={handleKeyDown}
      >
        <title>{`${title} - ${t(`track.view.${view}`)}`}</title>
        {view === "3d" ? <desc>{t("track.view3dHint")}</desc> : null}
        <defs>
          <linearGradient
            id={gradientId}
            gradientUnits="userSpaceOnUse"
            x1={PADDING_X}
            y1={VIEWBOX_HEIGHT - PADDING_Y}
            x2={VIEWBOX_WIDTH - PADDING_X}
            y2={PADDING_Y}
          >
            <stop offset="0" stopColor="#5fdbf4" />
            <stop offset="0.52" stopColor="#b061f0" />
            <stop offset="1" stopColor="#ff65b8" />
          </linearGradient>
          <filter
            id={glowId}
            filterUnits="userSpaceOnUse"
            x="-40"
            y="-40"
            width={VIEWBOX_WIDTH + 80}
            height={VIEWBOX_HEIGHT + 80}
          >
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <rect className="scenario-track-bg" width={VIEWBOX_WIDTH} height={VIEWBOX_HEIGHT} rx="18" />
        {view === "3d" ? (
          <g aria-hidden="true">
            <polygon className="scenario-track-3d-ground" points={groundPolygon} />
            {threeDimensionalScene.grid.xLines.map((line, index) => (
              <line
                key={`x-${index}`}
                data-grid-axis="x"
                x1={line[0].x}
                y1={line[0].y}
                x2={line[1].x}
                y2={line[1].y}
                className="scenario-track-3d-grid-line"
              />
            ))}
            {threeDimensionalScene.grid.yLines.map((line, index) => (
              <line
                key={`y-${index}`}
                data-grid-axis="y"
                x1={line[0].x}
                y1={line[0].y}
                x2={line[1].x}
                y2={line[1].y}
                className="scenario-track-3d-grid-line"
              />
            ))}
            {threeDimensionalScene.axes.map((axis) => (
              <g
                key={axis.axis}
                className={`scenario-track-3d-axis scenario-track-3d-axis-${axis.axis}`}
                data-axis={axis.axis}
              >
                <line x1={axis.start.x} y1={axis.start.y} x2={axis.end.x} y2={axis.end.y} />
                <text x={axis.end.x + 6} y={axis.end.y - 5}>{axis.axis.toUpperCase()}</text>
              </g>
            ))}
            {shadowPolyline ? (
              <polyline className="scenario-track-3d-shadow" points={shadowPolyline} />
            ) : null}
          </g>
        ) : (
          <>
            <g className={`scenario-track-grid scenario-track-grid-${view}`} aria-hidden="true">
              <path d="M38 55H388M38 105H388M38 155H388M38 205H388" />
              <path d="M88 25V232M158 25V232M228 25V232M298 25V232M368 25V232" />
            </g>
            <path className="scenario-track-axis" d="M38 225H390M45 232V22" aria-hidden="true" />
          </>
        )}
        {polyline ? (
          <g data-testid="scenario-track-route">
            <polyline
              className="scenario-track-route-glow"
              points={polyline}
              filter={`url(#${glowId})`}
            />
            <polyline
              className="scenario-track-route"
              points={polyline}
              stroke={`url(#${gradientId})`}
            />
            {firstPoint ? (
              <g transform={`translate(${firstPoint.x} ${firstPoint.y})`}>
                <circle className="scenario-track-marker-halo" r="10" />
                <circle className="scenario-track-marker" r="5" />
              </g>
            ) : null}
          </g>
        ) : null}
        {view !== "3d" ? (
          <>
            <text className="scenario-track-axis-label" x="388" y="246" textAnchor="end">
              {horizontalLabel}
            </text>
            <text className="scenario-track-axis-label" x="24" y="28">
              {verticalLabel}
            </text>
          </>
        ) : null}
      </svg>
    </figure>
  );
}
