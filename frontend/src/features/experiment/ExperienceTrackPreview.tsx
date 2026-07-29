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

const VIEWBOX_WIDTH = 320;
const VIEWBOX_HEIGHT = 150;
const PADDING = 22;

function finitePoints(points: TrackPoint[]): TrackPoint[] {
  return points.filter(
    (point) =>
      Number.isFinite(point.x) &&
      Number.isFinite(point.y) &&
      Number.isFinite(point.z),
  );
}

function projectedPolyline(points: TrackPoint[]): string {
  if (points.length === 0) return "";
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);
  const scale = Math.min(
    (VIEWBOX_WIDTH - 2 * PADDING) / spanX,
    (VIEWBOX_HEIGHT - 2 * PADDING) / spanY,
  );
  const offsetX = (VIEWBOX_WIDTH - spanX * scale) / 2;
  const offsetY = (VIEWBOX_HEIGHT - spanY * scale) / 2;
  return points
    .map((point) => {
      const x = offsetX + (point.x - minX) * scale;
      const y = VIEWBOX_HEIGHT - (offsetY + (point.y - minY) * scale);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
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
  const safePoints = finitePoints(points);
  const polyline = projectedPolyline(safePoints);
  const isHover = trackType === "hover";

  return (
    <figure className="experience-preview" aria-label={title}>
      <figcaption>
        <strong>{title}</strong>
        <span>{isHover ? hoverLabel : routeLabel}</span>
      </figcaption>
      <svg
        className="experience-preview-canvas"
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        role="img"
        aria-label={isHover ? hoverLabel : routeLabel}
      >
        <rect className="experience-preview-bg" width="320" height="150" rx="12" />
        <path className="experience-preview-axis" d="M22 128H298M42 138V18" />
        {isHover ? (
          <g data-testid="hover-preview">
            <path className="experience-preview-climb" d="M96 124V42" />
            <circle className="experience-preview-hover-ring" cx="96" cy="42" r="18" />
            <circle className="experience-preview-marker" cx="96" cy="42" r="5" />
            <text className="experience-preview-altitude" x="124" y="47">
              {Number.isFinite(altitudeM) ? `${altitudeM} m` : "—"}
            </text>
          </g>
        ) : polyline ? (
          <g data-testid="route-preview">
            <polyline className="experience-preview-route" points={polyline} />
            {(() => {
              const [first = "0,0"] = polyline.split(" ");
              const [x, y] = first.split(",").map(Number);
              return <circle className="experience-preview-marker" cx={x} cy={y} r="5" />;
            })()}
          </g>
        ) : (
          <text className="experience-preview-empty" x="160" y="78" textAnchor="middle">
            —
          </text>
        )}
      </svg>
      <div className="experience-preview-meta">
        <span>{pointCountLabel}</span>
        <span>{localOnlyLabel}</span>
      </div>
    </figure>
  );
}
