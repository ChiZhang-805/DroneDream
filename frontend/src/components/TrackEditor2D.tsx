import { useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";

import type { TrackPoint } from "../types/api";
import { useI18n } from "../i18n/I18nProvider";

interface TrackEditor2DProps {
  points: TrackPoint[];
  defaultAltitude: number;
  onChange: (points: TrackPoint[]) => void;
}

const WIDTH = 640;
const HEIGHT = 360;
const PADDING = 36;

function finite(value: number | null | undefined, fallback = 0): number {
  return Number.isFinite(value) ? Number(value) : fallback;
}

function roundCoordinate(value: number): number {
  return Math.round(value * 100) / 100;
}

export function TrackEditor2D({
  points,
  defaultAltitude,
  onChange,
}: TrackEditor2DProps) {
  const { t } = useI18n();
  const history = useRef<TrackPoint[][]>([]);
  const [dragging, setDragging] = useState<number | null>(null);

  const bounds = useMemo(() => {
    const xs = points.map((point) => finite(point.x));
    const ys = points.map((point) => finite(point.y));
    const minX = Math.min(-5, ...xs);
    const maxX = Math.max(5, ...xs);
    const minY = Math.min(-5, ...ys);
    const maxY = Math.max(5, ...ys);
    const xPad = Math.max(2, (maxX - minX) * 0.15);
    const yPad = Math.max(2, (maxY - minY) * 0.15);
    return {
      minX: minX - xPad,
      maxX: maxX + xPad,
      minY: minY - yPad,
      maxY: maxY + yPad,
    };
  }, [points]);

  function project(point: TrackPoint): { x: number; y: number } {
    const x =
      PADDING +
      ((finite(point.x) - bounds.minX) / (bounds.maxX - bounds.minX)) *
        (WIDTH - PADDING * 2);
    const y =
      HEIGHT -
      PADDING -
      ((finite(point.y) - bounds.minY) / (bounds.maxY - bounds.minY)) *
        (HEIGHT - PADDING * 2);
    return { x, y };
  }

  function unproject(svgX: number, svgY: number): { x: number; y: number } {
    return {
      x: roundCoordinate(
        bounds.minX +
          ((svgX - PADDING) / (WIDTH - PADDING * 2)) *
            (bounds.maxX - bounds.minX),
      ),
      y: roundCoordinate(
        bounds.minY +
          ((HEIGHT - PADDING - svgY) / (HEIGHT - PADDING * 2)) *
            (bounds.maxY - bounds.minY),
      ),
    };
  }

  function snapshot(): void {
    history.current.push(points.map((point) => ({ ...point })));
    if (history.current.length > 40) history.current.shift();
  }

  function commit(next: TrackPoint[]): void {
    snapshot();
    onChange(next);
  }

  function updatePoint(index: number, patch: Partial<TrackPoint>): void {
    commit(points.map((point, pointIndex) => (pointIndex === index ? { ...point, ...patch } : point)));
  }

  function addPoint(): void {
    const previous = points.at(-1);
    commit([
      ...points,
      {
        x: roundCoordinate(finite(previous?.x) + 2),
        y: roundCoordinate(finite(previous?.y)),
        z: finite(previous?.z, defaultAltitude),
      },
    ]);
  }

  function removePoint(index: number): void {
    commit(points.filter((_point, pointIndex) => pointIndex !== index));
  }

  function undo(): void {
    const previous = history.current.pop();
    if (previous) onChange(previous);
  }

  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>): void {
    if (dragging === null) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const svgX = ((event.clientX - rect.left) / rect.width) * WIDTH;
    const svgY = ((event.clientY - rect.top) / rect.height) * HEIGHT;
    const coordinate = unproject(svgX, svgY);
    onChange(
      points.map((point, pointIndex) =>
        pointIndex === dragging ? { ...point, ...coordinate } : point,
      ),
    );
  }

  const projected = points.map(project);
  const polyline = projected.map((point) => `${point.x},${point.y}`).join(" ");

  return (
    <div className="track-editor">
      <div className="track-editor-toolbar">
        <button type="button" className="btn btn-small" onClick={addPoint}>
          {t("track.add")}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-small"
          onClick={undo}
          disabled={history.current.length === 0}
        >
          {t("track.undo")}
        </button>
        <span className="form-hint">{t("track.dragHint")}</span>
      </div>

      <svg
        className="track-editor-canvas"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={t("track.preview")}
        onPointerMove={handlePointerMove}
        onPointerUp={() => setDragging(null)}
        onPointerCancel={() => setDragging(null)}
      >
        <title>{t("track.preview")}</title>
        <rect x="0" y="0" width={WIDTH} height={HEIGHT} className="track-editor-bg" />
        {Array.from({ length: 9 }, (_value, index) => {
          const x = PADDING + (index / 8) * (WIDTH - PADDING * 2);
          const y = PADDING + (index / 8) * (HEIGHT - PADDING * 2);
          return (
            <g key={index}>
              <line x1={x} y1={PADDING} x2={x} y2={HEIGHT - PADDING} className="track-grid-line" />
              <line x1={PADDING} y1={y} x2={WIDTH - PADDING} y2={y} className="track-grid-line" />
            </g>
          );
        })}
        {projected.length > 1 ? <polyline points={polyline} className="track-path-line" /> : null}
        {projected.map((point, index) => (
          <g
            key={`${index}-${points[index].z ?? "default"}`}
            className="track-waypoint"
            transform={`translate(${point.x} ${point.y})`}
            onPointerDown={(event) => {
              snapshot();
              setDragging(index);
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
          >
            <circle r="11" />
            <text y="4" textAnchor="middle">{index + 1}</text>
          </g>
        ))}
        <text x={WIDTH - PADDING} y={HEIGHT - 10} textAnchor="end" className="track-axis-label">
          X / East (m)
        </text>
        <text x={PADDING} y={18} className="track-axis-label">Y / North (m)</text>
      </svg>

      <div className="track-waypoint-table-wrap">
        <table className="track-waypoint-table">
          <thead>
            <tr>
              <th>#</th>
              <th>X (m)</th>
              <th>Y (m)</th>
              <th>Z (m)</th>
              <th><span className="sr-only">{t("track.actions")}</span></th>
            </tr>
          </thead>
          <tbody>
            {points.map((point, index) => (
              <tr key={index}>
                <td>{index + 1}</td>
                {(["x", "y", "z"] as const).map((axis) => (
                  <td key={axis}>
                    <label className="sr-only" htmlFor={`waypoint-${index}-${axis}`}>
                      Waypoint {index + 1} {axis.toUpperCase()}
                    </label>
                    <input
                      id={`waypoint-${index}-${axis}`}
                      type="number"
                      step="0.1"
                      value={finite(point[axis], axis === "z" ? defaultAltitude : 0)}
                      onChange={(event) =>
                        updatePoint(index, { [axis]: Number(event.target.value) })
                      }
                    />
                  </td>
                ))}
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost btn-small"
                    onClick={() => removePoint(index)}
                    aria-label={`${t("track.remove")} ${t("track.waypoint")} ${index + 1}`}
                  >
                    {t("track.remove")}
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
