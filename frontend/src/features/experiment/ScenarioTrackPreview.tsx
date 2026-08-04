import { useId, useMemo, useState } from "react";

import type { TrackPoint } from "../../types/api";
import { useI18n } from "../../i18n/I18nProvider";

type Axis = "x" | "y" | "z";
type ScenarioTrackView = "xy" | "xz" | "yz" | "3d";

interface ScenarioTrackPreviewProps {
  points: TrackPoint[];
  defaultAltitude: number;
  title: string;
}

interface ProjectedPoint {
  x: number;
  y: number;
}

const VIEWBOX_WIDTH = 420;
const VIEWBOX_HEIGHT = 260;
const PADDING_X = 34;
const PADDING_Y = 30;
const VIEW_ORDER: readonly ScenarioTrackView[] = ["xy", "xz", "yz", "3d"];
const PLANAR_AXES: Record<Exclude<ScenarioTrackView, "3d">, readonly [Axis, Axis]> = {
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

function projectPoints(
  points: TrackPoint[],
  view: ScenarioTrackView,
  defaultAltitude: number,
): ProjectedPoint[] {
  const rawPoints = points.map((point) => {
    if (view === "3d") {
      const x = axisValue(point, "x", defaultAltitude);
      const y = axisValue(point, "y", defaultAltitude);
      const z = axisValue(point, "z", defaultAltitude);
      return {
        x: (x - y) * 0.86,
        y: (x + y) * 0.42 + z * 1.05,
      };
    }
    const [horizontalAxis, verticalAxis] = PLANAR_AXES[view];
    return {
      x: axisValue(point, horizontalAxis, defaultAltitude),
      y: axisValue(point, verticalAxis, defaultAltitude),
    };
  });
  return fitProjection(rawPoints);
}

function axisLabels(view: ScenarioTrackView): readonly [string, string] {
  if (view === "xy") return ["X", "Y"];
  if (view === "xz") return ["X", "Z"];
  if (view === "yz") return ["Y", "Z"];
  return ["X / Y", "Z"];
}

export function ScenarioTrackPreview({
  points,
  defaultAltitude,
  title,
}: ScenarioTrackPreviewProps) {
  const { t } = useI18n();
  const instanceId = useId().replace(/:/gu, "");
  const [view, setView] = useState<ScenarioTrackView>("xy");
  const projected = useMemo(
    () => projectPoints(points, view, defaultAltitude),
    [defaultAltitude, points, view],
  );
  const polyline = projected.map((point) => `${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
  const firstPoint = projected[0];
  const [horizontalLabel, verticalLabel] = axisLabels(view);
  const gradientId = `scenario-track-gradient-${instanceId}-${view}`;
  const glowId = `scenario-track-glow-${instanceId}-${view}`;

  return (
    <figure className="scenario-track-preview" data-view={view} aria-label={title}>
      <div className="scenario-track-view-switcher" role="group" aria-label={t("track.viewSwitcher")}>
        {VIEW_ORDER.map((candidate) => (
          <button
            key={candidate}
            type="button"
            className={candidate === view ? "is-active" : ""}
            aria-pressed={candidate === view}
            aria-label={t(`track.view.${candidate}`)}
            onClick={() => setView(candidate)}
          >
            {candidate.toUpperCase()}
          </button>
        ))}
      </div>
      <svg
        className="scenario-track-canvas"
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        role="img"
        aria-label={`${title} - ${t(`track.view.${view}`)}`}
      >
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
        <g className={`scenario-track-grid scenario-track-grid-${view}`} aria-hidden="true">
          <path d="M38 55H388M38 105H388M38 155H388M38 205H388" />
          <path d="M88 25V232M158 25V232M228 25V232M298 25V232M368 25V232" />
        </g>
        <path className="scenario-track-axis" d="M38 225H390M45 232V22" aria-hidden="true" />
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
        <text className="scenario-track-axis-label" x="388" y="246" textAnchor="end">
          {horizontalLabel}
        </text>
        <text className="scenario-track-axis-label" x="24" y="28">
          {verticalLabel}
        </text>
      </svg>
    </figure>
  );
}
