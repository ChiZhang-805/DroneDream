import { useEffect, useMemo, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
  WheelEvent as ReactWheelEvent,
} from "react";

import type { TrackPoint } from "../types/api";
import { useI18n } from "../i18n/I18nProvider";

interface TrackEditor2DProps {
  points: TrackPoint[];
  defaultAltitude: number;
  onChange: (points: TrackPoint[]) => void;
  dataPanelAction?: ReactNode;
}

type Axis = "x" | "y" | "z";
type PlanarView = "xy" | "xz" | "yz";
type TrackView = PlanarView | "3d";

interface AxisBounds {
  min: number;
  max: number;
}

interface ProjectedPoint {
  x: number;
  y: number;
  depth?: number;
}

interface PlanarDragBounds {
  horizontal: AxisBounds;
  vertical: AxisBounds;
}

interface ThreeDimensionalGridSpec {
  step: number;
  x: AxisBounds;
  y: AxisBounds;
  xValues: number[];
  yValues: number[];
}

const WIDTH = 560;
const HEIGHT = 560;
const PADDING = 52;
const VIEW_ORDER: TrackView[] = ["xy", "xz", "yz", "3d"];
const VIEW_AXES: Record<PlanarView, readonly [Axis, Axis]> = {
  xy: ["x", "y"],
  xz: ["x", "z"],
  yz: ["y", "z"],
};

function finite(value: number | null | undefined, fallback = 0): number {
  return Number.isFinite(value) ? Number(value) : fallback;
}

function axisValue(point: TrackPoint, axis: Axis, defaultAltitude: number): number {
  return finite(point[axis], axis === "z" ? defaultAltitude : 0);
}

function roundCoordinate(value: number): number {
  return Math.round(value * 100) / 100;
}

function clonePoints(points: TrackPoint[]): TrackPoint[] {
  return points.map((point) => ({ ...point }));
}

function niceGridStep(span: number): number {
  const rawStep = Math.max(span, 1) / 9;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return multiplier * magnitude;
}

function gridValues(min: number, max: number, step: number): number[] {
  const count = Math.round((max - min) / step);
  return Array.from({ length: count + 1 }, (_value, index) => min + index * step);
}

function Icon({ name }: { name: "add" | "undo" | "trash" | "left" | "right" | "confirm" | "cancel" }) {
  const paths = {
    add: <path d="M12 5v14M5 12h14" />,
    undo: <path d="M9 7 4 12l5 5M5 12h8a6 6 0 0 1 6 6" />,
    trash: <path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5" />,
    left: <path d="m15 5-7 7 7 7" />,
    right: <path d="m9 5 7 7-7 7" />,
    confirm: <path d="m5 12 4 4L19 6" />,
    cancel: <path d="m6 6 12 12M18 6 6 18" />,
  } as const;

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {paths[name]}
    </svg>
  );
}

export function TrackEditor2D({
  points,
  defaultAltitude,
  onChange,
  dataPanelAction,
}: TrackEditor2DProps) {
  const { t } = useI18n();
  const history = useRef<TrackPoint[][]>([]);
  const tableWrapRef = useRef<HTMLDivElement | null>(null);
  const rowRefs = useRef<Array<HTMLTableRowElement | null>>([]);
  const dragOrigin = useRef<TrackPoint[] | null>(null);
  const dragBounds = useRef<PlanarDragBounds | null>(null);
  const dragChanged = useRef(false);
  const rotationDrag = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    yaw: number;
    pitch: number;
  } | null>(null);
  const addButtonRef = useRef<HTMLButtonElement | null>(null);
  const clearButtonRef = useRef<HTMLButtonElement | null>(null);
  const confirmClearRef = useRef<HTMLButtonElement | null>(null);
  const [view, setView] = useState<TrackView>("xy");
  const [dragging, setDragging] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [rotation, setRotation] = useState({ yaw: -0.72, pitch: 0.58, zoom: 1.22 });

  const bounds = useMemo<Record<Axis, AxisBounds>>(() => {
    const makeBounds = (axis: Axis): AxisBounds => {
      const values = points.map((point) => axisValue(point, axis, defaultAltitude));
      const baseMin = axis === "z" ? 0 : -5;
      const baseMax = axis === "z" ? Math.max(10, defaultAltitude * 2) : 5;
      const min = Math.min(baseMin, ...values);
      const max = Math.max(baseMax, ...values);
      const pad = Math.max(2, (max - min) * 0.15);
      return { min: min - pad, max: max + pad };
    };

    return {
      x: makeBounds("x"),
      y: makeBounds("y"),
      z: makeBounds("z"),
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
      step,
      x,
      y,
      xValues: gridValues(x.min, x.max, step),
      yValues: gridValues(y.min, y.max, step),
    };
  }, [bounds]);

  const threeDimensionalProjection = useMemo(() => {
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
    const scale = Math.min(WIDTH, HEIGHT) * 0.62 * rotation.zoom;
    const cosYaw = Math.cos(rotation.yaw);
    const sinYaw = Math.sin(rotation.yaw);
    const cosPitch = Math.cos(rotation.pitch);
    const sinPitch = Math.sin(rotation.pitch);

    return (coordinate: Record<Axis, number>): ProjectedPoint => {
      const x = (coordinate.x - centers.x) / span;
      const y = (coordinate.y - centers.y) / span;
      const z = (coordinate.z - centers.z) / span;
      const rotatedX = cosYaw * x - sinYaw * y;
      const rotatedY = sinYaw * x + cosYaw * y;
      return {
        x: WIDTH / 2 + rotatedX * scale,
        y: HEIGHT / 2 + (rotatedY * sinPitch - z * cosPitch) * scale,
        depth: rotatedY * cosPitch + z * sinPitch,
      };
    };
  }, [bounds.z.max, bounds.z.min, rotation, threeDimensionalGridSpec]);

  useEffect(() => {
    if (selected !== null && selected >= points.length) {
      setSelected(points.length > 0 ? points.length - 1 : null);
    }
  }, [points.length, selected]);

  useEffect(() => {
    if (confirmingClear) confirmClearRef.current?.focus();
  }, [confirmingClear]);

  function projectPlanar(point: TrackPoint, planarView: PlanarView): ProjectedPoint {
    const [horizontalAxis, verticalAxis] = VIEW_AXES[planarView];
    const horizontalBounds = bounds[horizontalAxis];
    const verticalBounds = bounds[verticalAxis];
    return {
      x:
        PADDING +
        ((axisValue(point, horizontalAxis, defaultAltitude) - horizontalBounds.min) /
          (horizontalBounds.max - horizontalBounds.min)) *
          (WIDTH - PADDING * 2),
      y:
        HEIGHT -
        PADDING -
        ((axisValue(point, verticalAxis, defaultAltitude) - verticalBounds.min) /
          (verticalBounds.max - verticalBounds.min)) *
          (HEIGHT - PADDING * 2),
    };
  }

  function unprojectPlanar(
    svgX: number,
    svgY: number,
    planarView: PlanarView,
    dragSnapshot?: PlanarDragBounds | null,
  ): Partial<Record<Axis, number>> {
    const [horizontalAxis, verticalAxis] = VIEW_AXES[planarView];
    const horizontalBounds = dragSnapshot?.horizontal ?? bounds[horizontalAxis];
    const verticalBounds = dragSnapshot?.vertical ?? bounds[verticalAxis];
    const clampedX = Math.max(PADDING, Math.min(WIDTH - PADDING, svgX));
    const clampedY = Math.max(PADDING, Math.min(HEIGHT - PADDING, svgY));
    return {
      [horizontalAxis]: roundCoordinate(
        horizontalBounds.min +
          ((clampedX - PADDING) / (WIDTH - PADDING * 2)) *
            (horizontalBounds.max - horizontalBounds.min),
      ),
      [verticalAxis]: roundCoordinate(
        verticalBounds.min +
          ((HEIGHT - PADDING - clampedY) / (HEIGHT - PADDING * 2)) *
            (verticalBounds.max - verticalBounds.min),
      ),
    };
  }

  function project3DPoint(point: TrackPoint): ProjectedPoint {
    return threeDimensionalProjection({
      x: axisValue(point, "x", defaultAltitude),
      y: axisValue(point, "y", defaultAltitude),
      z: axisValue(point, "z", defaultAltitude),
    });
  }

  function pushHistory(snapshot: TrackPoint[]): void {
    history.current.push(clonePoints(snapshot));
    if (history.current.length > 40) history.current.shift();
  }

  function commit(next: TrackPoint[]): void {
    pushHistory(points);
    onChange(next);
  }

  function updatePoint(index: number, patch: Partial<TrackPoint>): void {
    commit(
      points.map((point, pointIndex) =>
        pointIndex === index ? { ...point, ...patch } : point,
      ),
    );
  }

  function scrollWaypointIntoView(index: number): void {
    const container = tableWrapRef.current;
    const row = rowRefs.current[index];
    if (!container || !row) return;
    const top = Math.max(
      0,
      row.offsetTop - container.clientHeight / 2 + row.clientHeight / 2,
    );
    if (typeof container.scrollTo === "function") {
      container.scrollTo({ top, behavior: "smooth" });
    } else {
      container.scrollTop = top;
    }
  }

  function selectWaypoint(index: number, scrollTable = false): void {
    setSelected(index);
    if (scrollTable) scrollWaypointIntoView(index);
  }

  function addPoint(): void {
    const previous = points.at(-1);
    const nextIndex = points.length;
    commit([
      ...points,
      {
        x: roundCoordinate(finite(previous?.x) + 2),
        y: roundCoordinate(finite(previous?.y)),
        z: finite(previous?.z, defaultAltitude),
      },
    ]);
    setSelected(nextIndex);
  }

  function removePoint(index: number): void {
    const next = points.filter((_point, pointIndex) => pointIndex !== index);
    commit(next);
    setSelected((current) => {
      if (current === null) return null;
      if (current === index) return next.length > 0 ? Math.min(index, next.length - 1) : null;
      return current > index ? current - 1 : current;
    });
  }

  function clearPoints(): void {
    commit([]);
    setSelected(null);
    setConfirmingClear(false);
    window.requestAnimationFrame(() => addButtonRef.current?.focus());
  }

  function cancelClear(): void {
    setConfirmingClear(false);
    window.requestAnimationFrame(() => clearButtonRef.current?.focus());
  }

  function undo(): void {
    const previous = history.current.pop();
    if (previous) {
      onChange(previous);
      setConfirmingClear(false);
    }
  }

  function changeView(direction: -1 | 1): void {
    const currentIndex = VIEW_ORDER.indexOf(view);
    const nextIndex = (currentIndex + direction + VIEW_ORDER.length) % VIEW_ORDER.length;
    setDragging(null);
    dragOrigin.current = null;
    dragBounds.current = null;
    rotationDrag.current = null;
    setView(VIEW_ORDER[nextIndex]);
  }

  function handleWaypointKeyDown(
    event: ReactKeyboardEvent<SVGGElement>,
    index: number,
  ): void {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    selectWaypoint(index, true);
  }

  function handleCanvasPointerDown(event: ReactPointerEvent<SVGSVGElement>): void {
    if (view !== "3d") return;
    rotationDrag.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      yaw: rotation.yaw,
      pitch: rotation.pitch,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>): void {
    if (view === "3d") {
      const origin = rotationDrag.current;
      if (!origin || origin.pointerId !== event.pointerId) return;
      const nextYaw = origin.yaw + (event.clientX - origin.clientX) * 0.008;
      const nextPitch = Math.max(
        0.15,
        Math.min(1.35, origin.pitch - (event.clientY - origin.clientY) * 0.006),
      );
      setRotation((current) => ({ ...current, yaw: nextYaw, pitch: nextPitch }));
      return;
    }

    if (dragging === null) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    if (!dragChanged.current && dragOrigin.current) {
      pushHistory(dragOrigin.current);
      dragChanged.current = true;
    }
    const svgX = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const svgY = ((event.clientY - rect.top) / rect.height) * HEIGHT;
    const coordinate = unprojectPlanar(svgX, svgY, view, dragBounds.current);
    onChange(
      points.map((point, pointIndex) =>
        pointIndex === dragging ? { ...point, ...coordinate } : point,
      ),
    );
  }

  function stopPointerInteraction(): void {
    setDragging(null);
    dragOrigin.current = null;
    dragBounds.current = null;
    dragChanged.current = false;
    rotationDrag.current = null;
  }

  function handleWheel(event: ReactWheelEvent<SVGSVGElement>): void {
    if (view !== "3d") return;
    event.preventDefault();
    setRotation((current) => ({
      ...current,
      zoom: Math.max(0.65, Math.min(2.2, current.zoom * (event.deltaY > 0 ? 0.9 : 1.1))),
    }));
  }

  const viewLabel = t(`track.view.${view}`);
  const projected = points.map((point) =>
    view === "3d" ? project3DPoint(point) : projectPlanar(point, view),
  );
  const polyline = projected.map((point) => `${point.x},${point.y}`).join(" ");
  const planarAxes = view === "3d" ? null : VIEW_AXES[view];
  const threeDimensionalGrid = view === "3d"
    ? {
        xLines: threeDimensionalGridSpec.xValues.map((x) => [
          threeDimensionalProjection({
            x,
            y: threeDimensionalGridSpec.y.min,
            z: bounds.z.min,
          }),
          threeDimensionalProjection({
            x,
            y: threeDimensionalGridSpec.y.max,
            z: bounds.z.min,
          }),
        ]),
        yLines: threeDimensionalGridSpec.yValues.map((y) => [
          threeDimensionalProjection({
            x: threeDimensionalGridSpec.x.min,
            y,
            z: bounds.z.min,
          }),
          threeDimensionalProjection({
            x: threeDimensionalGridSpec.x.max,
            y,
            z: bounds.z.min,
          }),
        ]),
      }
    : null;
  const threeDimensionalAxes = view === "3d"
    ? [
        {
          axis: "x" as const,
          start: threeDimensionalProjection({ x: threeDimensionalGridSpec.x.min, y: threeDimensionalGridSpec.y.min, z: bounds.z.min }),
          end: threeDimensionalProjection({ x: threeDimensionalGridSpec.x.max, y: threeDimensionalGridSpec.y.min, z: bounds.z.min }),
        },
        {
          axis: "y" as const,
          start: threeDimensionalProjection({ x: threeDimensionalGridSpec.x.min, y: threeDimensionalGridSpec.y.min, z: bounds.z.min }),
          end: threeDimensionalProjection({ x: threeDimensionalGridSpec.x.min, y: threeDimensionalGridSpec.y.max, z: bounds.z.min }),
        },
        {
          axis: "z" as const,
          start: threeDimensionalProjection({ x: threeDimensionalGridSpec.x.min, y: threeDimensionalGridSpec.y.min, z: bounds.z.min }),
          end: threeDimensionalProjection({ x: threeDimensionalGridSpec.x.min, y: threeDimensionalGridSpec.y.min, z: bounds.z.max }),
        },
      ]
    : [];

  return (
    <div className="track-editor" data-testid="track-editor-workspace">
      <div className="track-editor-toolbar">
        <div className="track-editor-actions">
          {dataPanelAction ? (
            <div className="track-editor-data-action" data-testid="track-editor-data-action">
              {dataPanelAction}
            </div>
          ) : null}
          <button
            ref={addButtonRef}
            type="button"
            className="track-icon-button"
            onClick={addPoint}
            aria-label={t("track.add")}
            title={t("track.add")}
          >
            <Icon name="add" />
          </button>
          <button
            type="button"
            className="track-icon-button"
            onClick={undo}
            disabled={history.current.length === 0}
            aria-label={t("track.undo")}
            title={t("track.undo")}
          >
            <Icon name="undo" />
          </button>
          <button
            ref={clearButtonRef}
            type="button"
            className="track-icon-button track-icon-button-danger"
            onClick={() => setConfirmingClear(true)}
            disabled={points.length === 0 || confirmingClear}
            aria-label={t("track.clearAll")}
            title={t("track.clearAll")}
          >
            <Icon name="trash" />
          </button>
        </div>

      </div>

      {confirmingClear ? (
        <div
          className="track-clear-confirm"
          role="alertdialog"
          aria-labelledby="track-clear-confirm-title"
          onKeyDown={(event) => {
            if (event.key === "Escape") cancelClear();
          }}
        >
          <strong id="track-clear-confirm-title">{t("track.clearQuestion")}</strong>
          <div className="track-clear-confirm-actions">
            <button
              ref={confirmClearRef}
              type="button"
              className="track-icon-button track-icon-button-danger"
              onClick={clearPoints}
              aria-label={t("track.confirmClear")}
              title={t("track.confirmClear")}
            >
              <Icon name="confirm" />
            </button>
            <button
              type="button"
              className="track-icon-button"
              onClick={cancelClear}
              aria-label={t("track.cancelClear")}
              title={t("track.cancelClear")}
            >
              <Icon name="cancel" />
            </button>
          </div>
        </div>
      ) : null}

      <div className="track-canvas-shell" data-testid="track-editor-visual-pane">
        <div className="track-view-switcher" role="group" aria-label={t("track.viewSwitcher")}>
          <button
            type="button"
            className="track-icon-button"
            onClick={() => changeView(-1)}
            aria-label={t("track.previousView")}
            title={t("track.previousView")}
          >
            <Icon name="left" />
          </button>
          <span className="track-view-label" aria-live="polite">{viewLabel}</span>
          <button
            type="button"
            className="track-icon-button"
            onClick={() => changeView(1)}
            aria-label={t("track.nextView")}
            title={t("track.nextView")}
          >
            <Icon name="right" />
          </button>
        </div>
        <svg
          className={`track-editor-canvas ${view === "3d" ? "track-editor-canvas-3d" : ""}`}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="group"
          aria-label={t("track.previewView", { view: viewLabel })}
          onPointerDown={handleCanvasPointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={stopPointerInteraction}
          onPointerCancel={stopPointerInteraction}
          onWheel={handleWheel}
        >
          <title>{t("track.previewView", { view: viewLabel })}</title>
          {view === "3d" ? <desc>{t("track.view3dHint")}</desc> : null}
          <rect x="0" y="0" width={WIDTH} height={HEIGHT} className="track-editor-bg" />

          {view !== "3d"
            ? Array.from({ length: 9 }, (_value, index) => {
                const x = PADDING + (index / 8) * (WIDTH - PADDING * 2);
                const y = PADDING + (index / 8) * (HEIGHT - PADDING * 2);
                return (
                  <g key={index}>
                    <line x1={x} y1={PADDING} x2={x} y2={HEIGHT - PADDING} className="track-grid-line" />
                    <line x1={PADDING} y1={y} x2={WIDTH - PADDING} y2={y} className="track-grid-line" />
                  </g>
                );
              })
            : null}

          {view === "3d" ? (
            <g aria-hidden="true">
              {threeDimensionalGrid?.xLines.map((line, index) => (
                <line
                  key={`x-${index}`}
                  data-grid-axis="x"
                  x1={line[0].x}
                  y1={line[0].y}
                  x2={line[1].x}
                  y2={line[1].y}
                  className="track-3d-grid-line"
                />
              ))}
              {threeDimensionalGrid?.yLines.map((line, index) => (
                <line
                  key={`y-${index}`}
                  data-grid-axis="y"
                  x1={line[0].x}
                  y1={line[0].y}
                  x2={line[1].x}
                  y2={line[1].y}
                  className="track-3d-grid-line"
                />
              ))}
              {threeDimensionalAxes.map((axis) => (
                <g key={axis.axis} className={`track-3d-axis track-3d-axis-${axis.axis}`}>
                  <line x1={axis.start.x} y1={axis.start.y} x2={axis.end.x} y2={axis.end.y} />
                  <text x={axis.end.x + 7} y={axis.end.y - 5}>{axis.axis.toUpperCase()}</text>
                </g>
              ))}
            </g>
          ) : null}

          {projected.length > 1 ? <polyline points={polyline} className="track-path-line" /> : null}
          {projected.map((point, index) => {
            const label = t("track.selectWaypoint", {
              index: index + 1,
              x: axisValue(points[index], "x", defaultAltitude),
              y: axisValue(points[index], "y", defaultAltitude),
              z: axisValue(points[index], "z", defaultAltitude),
            });
            return (
              <g
                key={index}
                data-testid={`track-waypoint-${index + 1}`}
                className={`track-waypoint ${selected === index ? "track-waypoint-selected" : ""}`}
                transform={`translate(${point.x} ${point.y})`}
                role="button"
                tabIndex={0}
                aria-label={label}
                aria-pressed={selected === index}
                onClick={(event) => {
                  event.stopPropagation();
                  selectWaypoint(index, true);
                }}
                onKeyDown={(event) => handleWaypointKeyDown(event, index)}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  selectWaypoint(index, true);
                  if (view === "3d") return;
                  dragOrigin.current = clonePoints(points);
                  const [horizontalAxis, verticalAxis] = VIEW_AXES[view];
                  dragBounds.current = {
                    horizontal: { ...bounds[horizontalAxis] },
                    vertical: { ...bounds[verticalAxis] },
                  };
                  dragChanged.current = false;
                  setDragging(index);
                  event.currentTarget.setPointerCapture?.(event.pointerId);
                }}
              >
                <circle r={selected === index ? 13 : 11} />
                <text y="4" textAnchor="middle">{index + 1}</text>
              </g>
            );
          })}

          {points.length === 0 ? (
            <text x={WIDTH / 2} y={HEIGHT / 2} textAnchor="middle" className="track-empty-label">
              {t("track.empty")}
            </text>
          ) : null}

          {planarAxes ? (
            <>
              <text x={WIDTH - PADDING} y={HEIGHT - 12} textAnchor="end" className="track-axis-label">
                {t(`track.axis.${planarAxes[0]}`)}
              </text>
              <text x={PADDING} y={20} className="track-axis-label">
                {t(`track.axis.${planarAxes[1]}`)}
              </text>
            </>
          ) : null}
        </svg>
      </div>

      <div
        ref={tableWrapRef}
        className="track-waypoint-table-wrap"
        data-testid="track-waypoint-table-scroll"
      >
        <table className="track-waypoint-table">
          <thead>
            <tr>
              <th>#</th>
              <th>{t("track.axis.x")}</th>
              <th>{t("track.axis.y")}</th>
              <th>{t("track.axis.z")}</th>
              <th><span className="sr-only">{t("track.actions")}</span></th>
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr
                key={index}
                ref={(node) => {
                  rowRefs.current[index] = node;
                }}
                className={selected === index ? "track-waypoint-row-selected" : ""}
                onClick={() => selectWaypoint(index)}
                onFocus={() => selectWaypoint(index)}
              >
                <td>{index + 1}</td>
                {(["x", "y", "z"] as const).map((axis) => (
                  <td key={axis}>
                    <label className="sr-only" htmlFor={`waypoint-${index}-${axis}`}>
                      {t("track.waypointInput", { index: index + 1, axis: axis.toUpperCase() })}
                    </label>
                    <input
                      id={`waypoint-${index}-${axis}`}
                      type="number"
                      step="0.1"
                      value={axisValue(point, axis, defaultAltitude)}
                      onChange={(event) =>
                        updatePoint(index, { [axis]: Number(event.target.value) })
                      }
                    />
                  </td>
                ))}
                <td>
                  <button
                    type="button"
                    className="track-icon-button track-icon-button-danger track-waypoint-delete"
                    onClick={(event) => {
                      event.stopPropagation();
                      removePoint(index);
                    }}
                    aria-label={t("track.removeWaypoint", { index: index + 1 })}
                    title={t("track.removeWaypoint", { index: index + 1 })}
                  >
                    <Icon name="trash" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
