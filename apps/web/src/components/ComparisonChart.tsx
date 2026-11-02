// Lightweight baseline-vs-optimized chart. Plain CSS bars keep this compact;
// each row shares a scale from zero to max(|baseline|, |optimized|).

import type { ComparisonPoint } from "../types/api";
import { useI18n } from "../i18n/I18nProvider";

interface Props {
  data: ComparisonPoint[];
}

/** Product score is a cost to minimize even if an older payload mislabeled its direction. */
function effectiveLowerIsBetter(point: ComparisonPoint): boolean {
  return point.metric === "score" ? true : point.lower_is_better;
}

/** Retain units and readable precision; missing measurements must not masquerade as zero. */
function formatValue(point: ComparisonPoint, value: number): string {
  if (!Number.isFinite(value)) return "—";
  const rounded =
    Math.abs(value) >= 100
      ? value.toFixed(0)
      : Math.abs(value) >= 10
        ? value.toFixed(1)
        : value.toFixed(2);
  return point.unit ? `${rounded} ${point.unit}` : rounded;
}

/** Highlight improvement only when both sides have finite comparable measurements. */
function winner(point: ComparisonPoint): "baseline" | "optimized" | "tie" | "unknown" {
  if (!Number.isFinite(point.baseline) || !Number.isFinite(point.optimized)) return "unknown";
  if (point.baseline === point.optimized) return "tie";
  const optimizedBetter = effectiveLowerIsBetter(point)
    ? point.optimized < point.baseline
    : point.optimized > point.baseline;
  return optimizedBetter ? "optimized" : "baseline";
}

/** Compare each metric on its own absolute-magnitude scale, not across unrelated units. */
export function ComparisonChart({ data }: Props) {
  const { t } = useI18n();
  return (
    <div className="comparison-chart" role="table" aria-label={t("comparison.ariaLabel")}>
      <div className="comparison-legend" role="presentation">
        <span className="legend-swatch legend-baseline" aria-hidden /> {t("comparison.baseline")}
        <span className="legend-swatch legend-optimized" aria-hidden /> {t("comparison.optimized")}
      </div>
      {data.map((point) => {
        const baselineMagnitude = Number.isFinite(point.baseline) ? Math.abs(point.baseline) : 0;
        const optimizedMagnitude = Number.isFinite(point.optimized) ? Math.abs(point.optimized) : 0;
        const scale = Math.max(
          baselineMagnitude,
          optimizedMagnitude,
          Number.EPSILON,
        );
        const baselinePct = (baselineMagnitude / scale) * 100;
        const optimizedPct = (optimizedMagnitude / scale) * 100;
        const w = winner(point);
        return (
          <div className="comparison-row" key={point.metric} role="row">
            <div className="comparison-label" role="rowheader">
              {point.label}
              <span className="comparison-hint">
                {effectiveLowerIsBetter(point)
                  ? t("comparison.lowerIsBetter")
                  : t("comparison.higherIsBetter")}
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
