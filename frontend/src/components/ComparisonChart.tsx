// Minimal baseline vs optimized chart. Uses plain CSS bars so we do not take
// on a chart-library dependency for Phase 1. Each row shows both bars side by
// side on a shared scale (0 → max(|baseline|, |optimized|)).

import type { ComparisonPoint } from "../types/api";

interface Props {
  data: ComparisonPoint[];
}

function effectiveLowerIsBetter(point: ComparisonPoint): boolean {
  return point.metric === "score" ? true : point.lower_is_better;
}

function formatValue(point: ComparisonPoint, value: number): string {
  const rounded =
    Math.abs(value) >= 100
      ? value.toFixed(0)
      : Math.abs(value) >= 10
        ? value.toFixed(1)
        : value.toFixed(2);
  return point.unit ? `${rounded} ${point.unit}` : rounded;
}

function winner(point: ComparisonPoint): "baseline" | "optimized" | "tie" {
  if (point.baseline === point.optimized) return "tie";
  const optimizedBetter = effectiveLowerIsBetter(point)
    ? point.optimized < point.baseline
    : point.optimized > point.baseline;
  return optimizedBetter ? "optimized" : "baseline";
}

export function ComparisonChart({ data }: Props) {
  return (
    <div className="comparison-chart" role="table" aria-label="Baseline vs optimized comparison">
      <div className="comparison-legend" role="presentation">
        <span className="legend-swatch legend-baseline" aria-hidden /> Baseline
        <span className="legend-swatch legend-optimized" aria-hidden /> Optimized
      </div>
      {data.map((point) => {
        const scale = Math.max(
          Math.abs(point.baseline),
          Math.abs(point.optimized),
          Number.EPSILON,
        );
        const baselinePct = (Math.abs(point.baseline) / scale) * 100;
        const optimizedPct = (Math.abs(point.optimized) / scale) * 100;
        const w = winner(point);
        return (
          <div className="comparison-row" key={point.metric} role="row">
            <div className="comparison-label" role="rowheader">
              {point.label}
              <span className="comparison-hint">
                {effectiveLowerIsBetter(point) ? "lower is better" : "higher is better"}
              </span>
            </div>
            <div className="comparison-bars" role="cell">
              <div className="bar-row">
                <div
                  className={`bar bar-baseline${w === "baseline" ? " bar-winner" : ""}`}
                  style={{ width: `${baselinePct}%` }}
                />
                <span className="bar-value">{formatValue(point, point.baseline)}</span>
              </div>
              <div className="bar-row">
                <div
                  className={`bar bar-optimized${w === "optimized" ? " bar-winner" : ""}`}
                  style={{ width: `${optimizedPct}%` }}
                />
                <span className="bar-value">{formatValue(point, point.optimized)}</span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
