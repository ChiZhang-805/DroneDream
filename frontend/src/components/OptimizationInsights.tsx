import { useMemo } from "react";

import type { OptimizationHistory, TrialSummary } from "../types/api";
import { formatNumber } from "../utils/format";
import { useI18n } from "../i18n/I18nProvider";

interface OptimizationInsightsProps {
  trials: TrialSummary[];
  history?: OptimizationHistory | null;
}

interface CandidateAggregate {
  id: string;
  label: string;
  generation: number;
  isBaseline: boolean;
  isBest: boolean;
  meanScore: number;
  bestScore: number;
  passRate: number | null;
  completed: number;
  total: number;
  scenarios: number | null;
  frontier: boolean;
}

function aggregateCandidates(trials: TrialSummary[]): CandidateAggregate[] {
  const grouped = new Map<string, TrialSummary[]>();
  for (const trial of trials) {
    grouped.set(trial.candidate_id, [...(grouped.get(trial.candidate_id) ?? []), trial]);
  }

  const rows = [...grouped.entries()].flatMap(([id, candidateTrials]) => {
    const scored = candidateTrials.filter(
      (trial): trial is TrialSummary & { score: number } =>
        trial.status === "COMPLETED" && trial.score !== null && Number.isFinite(trial.score),
    );
    if (scored.length === 0) return [];
    const passKnown = scored.filter((trial) => trial.pass_flag !== null);
    const first = candidateTrials[0];
    return [{
      id,
      label: first.candidate_label ?? id,
      generation: first.candidate_generation_index,
      isBaseline: first.candidate_is_baseline,
      isBest: candidateTrials.some((trial) => trial.candidate_is_best),
      meanScore: scored.reduce((total, trial) => total + trial.score, 0) / scored.length,
      bestScore: Math.min(...scored.map((trial) => trial.score)),
      passRate:
        passKnown.length === 0
          ? null
          : passKnown.filter((trial) => trial.pass_flag).length / passKnown.length,
      completed: scored.length,
      total: candidateTrials.length,
      scenarios: new Set(candidateTrials.map((trial) => `${trial.scenario_type}:${trial.seed}`)).size,
      frontier: false,
    }];
  });

  let bestPassRate = -1;
  for (const candidate of [...rows].sort((a, b) => a.meanScore - b.meanScore)) {
    const rate = candidate.passRate ?? 0;
    if (rate > bestPassRate) {
      candidate.frontier = true;
      bestPassRate = rate;
    }
  }
  return rows.sort((a, b) => a.meanScore - b.meanScore);
}

function aggregateHistory(history: OptimizationHistory): CandidateAggregate[] {
  const pareto = new Set(history.pareto_candidate_ids);
  return history.items
    .filter((candidate) => candidate.aggregated_score !== null)
    .map((candidate) => ({
      id: candidate.id,
      label: candidate.label ?? candidate.id,
      generation: candidate.generation_index,
      isBaseline: candidate.is_baseline,
      isBest: candidate.is_best,
      meanScore: Number(candidate.aggregated_score),
      bestScore: Number(candidate.aggregated_score),
      passRate:
        candidate.objective_values && Number.isFinite(candidate.objective_values.pass_flag)
          ? Number(candidate.objective_values.pass_flag)
          : candidate.feasible === null
            ? null
            : candidate.feasible
              ? 1
              : 0,
      completed: candidate.completed_trial_count,
      total: candidate.trial_count,
      scenarios: null,
      frontier: pareto.has(candidate.id),
    }))
    .sort((a, b) => a.meanScore - b.meanScore);
}

function linePath(
  values: number[],
  width: number,
  height: number,
  sharedMin?: number,
  sharedMax?: number,
): string {
  if (values.length === 0) return "";
  const min = sharedMin ?? Math.min(...values);
  const max = sharedMax ?? Math.max(...values);
  const span = max - min || 1;
  return values
    .map((value, index) => {
      const x = values.length === 1 ? width / 2 : 24 + (index / (values.length - 1)) * (width - 48);
      const y = 18 + ((max - value) / span) * (height - 44);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function GenerationTrend({ candidates }: { candidates: CandidateAggregate[] }) {
  const { t } = useI18n();
  const generationRows = useMemo(() => {
    const generations = new Map<number, CandidateAggregate[]>();
    for (const candidate of candidates.filter((item) => !item.isBaseline)) {
      generations.set(candidate.generation, [
        ...(generations.get(candidate.generation) ?? []),
        candidate,
      ]);
    }
    return [...generations.entries()]
      .sort(([a], [b]) => a - b)
      .map(([generation, rows]) => ({
        generation,
        best: Math.min(...rows.map((row) => row.meanScore)),
        mean: rows.reduce((total, row) => total + row.meanScore, 0) / rows.length,
      }));
  }, [candidates]);

  if (generationRows.length === 0) {
    return (
      <div className="insight-empty">
        {t("insights.generationEmpty")}
      </div>
    );
  }

  const width = 520;
  const height = 190;
  const bestValues = generationRows.map((row) => row.best);
  const meanValues = generationRows.map((row) => row.mean);
  const combined = [...bestValues, ...meanValues];
  const sharedMin = Math.min(...combined);
  const sharedMax = Math.max(...combined);
  return (
    <div className="insight-chart-block">
      <div className="insight-chart-legend">
        <span><i className="legend-line legend-best" />{t("insights.bestScore")}</span>
        <span><i className="legend-line legend-mean" />{t("insights.generationMean")}</span>
        <span>{t("comparison.lowerIsBetter")}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("insights.generationAria")} className="insight-svg">
        <title>{t("insights.generationAria")}</title>
        <line x1="24" y1={height - 25} x2={width - 20} y2={height - 25} className="insight-axis" />
        <path d={linePath(meanValues, width, height, sharedMin, sharedMax)} className="generation-line generation-line-mean" />
        <path d={linePath(bestValues, width, height, sharedMin, sharedMax)} className="generation-line generation-line-best" />
        {generationRows.map((row, index) => {
          const x = generationRows.length === 1 ? width / 2 : 24 + (index / (generationRows.length - 1)) * (width - 48);
          const y = 18 + ((sharedMax - row.best) / (sharedMax - sharedMin || 1)) * (height - 44);
          return (
            <g key={row.generation}>
              <circle cx={x} cy={y} r="4" className="generation-dot" />
              <text x={x} y={height - 8} textAnchor="middle" className="insight-axis-label">G{row.generation}</text>
              <title>{t("insights.generationPoint", {
                generation: row.generation,
                best: formatNumber(row.best),
                mean: formatNumber(row.mean),
              })}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function ParetoPlot({ candidates }: { candidates: CandidateAggregate[] }) {
  const { t } = useI18n();
  const plottable = candidates.filter((candidate) => candidate.passRate !== null);
  if (plottable.length < 2) {
    return (
      <div className="insight-empty">
        {t("insights.paretoEmpty")}
      </div>
    );
  }
  const width = 520;
  const height = 230;
  const scores = plottable.map((candidate) => candidate.meanScore);
  const minScore = Math.min(...scores);
  const maxScore = Math.max(...scores);
  const scoreSpan = maxScore - minScore || 1;
  return (
    <div className="insight-chart-block">
      <div className="insight-chart-legend">
        <span><i className="legend-dot legend-frontier" />{t("insights.nonDominated")}</span>
        <span><i className="legend-dot legend-candidate" />{t("jobDetail.candidate")}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("insights.paretoAria")} className="insight-svg">
        <title>{t("insights.paretoTitle")}</title>
        <line x1="42" y1={height - 34} x2={width - 18} y2={height - 34} className="insight-axis" />
        <line x1="42" y1="18" x2="42" y2={height - 34} className="insight-axis" />
        <text x={width / 2} y={height - 8} textAnchor="middle" className="insight-axis-label">{t("insights.meanScoreAxis")}</text>
        <text x="13" y={height / 2} textAnchor="middle" transform={`rotate(-90 13 ${height / 2})`} className="insight-axis-label">{t("insights.passRate")}</text>
        {plottable.map((candidate) => {
          const x = 50 + ((candidate.meanScore - minScore) / scoreSpan) * (width - 80);
          const y = 26 + (1 - (candidate.passRate ?? 0)) * (height - 68);
          return (
            <g key={candidate.id} className={candidate.frontier ? "pareto-frontier" : "pareto-candidate"}>
              <circle cx={x} cy={y} r={candidate.isBest ? 8 : 6} />
              <text x={x + 9} y={y - 7} className="pareto-label">{candidate.label}</text>
              <title>{t("insights.candidatePoint", {
                candidate: candidate.label,
                score: formatNumber(candidate.meanScore),
                passRate: ((candidate.passRate ?? 0) * 100).toFixed(0),
              })}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function ObjectiveParetoPlot({ history }: { history: OptimizationHistory }) {
  const { t } = useI18n();
  const metricNames = Object.keys(history.objective_directions);
  if (metricNames.length < 2) return null;
  const [xMetric, yMetric] = metricNames;
  const rows = history.items.filter(
    (candidate) =>
      candidate.objective_values &&
      Number.isFinite(candidate.objective_values[xMetric]) &&
      Number.isFinite(candidate.objective_values[yMetric]),
  );
  if (rows.length < 2) {
    return <div className="insight-empty">{t("insights.objectiveParetoEmpty")}</div>;
  }
  const width = 520;
  const height = 230;
  const xs = rows.map((candidate) => Number(candidate.objective_values?.[xMetric]));
  const ys = rows.map((candidate) => Number(candidate.objective_values?.[yMetric]));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const pareto = new Set(history.pareto_candidate_ids);
  return (
    <div className="insight-chart-block">
      <div className="insight-chart-legend">
        <span><i className="legend-dot legend-frontier" />{t("insights.backendPareto")}</span>
        <span><i className="legend-dot legend-candidate" />{t("jobDetail.candidate")}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("insights.objectiveParetoAria")} className="insight-svg">
        <title>{t("insights.objectiveParetoTitle")}</title>
        <line x1="42" y1={height - 34} x2={width - 18} y2={height - 34} className="insight-axis" />
        <line x1="42" y1="18" x2="42" y2={height - 34} className="insight-axis" />
        <text x={width / 2} y={height - 8} textAnchor="middle" className="insight-axis-label">
          {xMetric} ({history.objective_directions[xMetric]})
        </text>
        <text x="13" y={height / 2} textAnchor="middle" transform={`rotate(-90 13 ${height / 2})`} className="insight-axis-label">
          {yMetric} ({history.objective_directions[yMetric]})
        </text>
        {rows.map((candidate) => {
          const xValue = Number(candidate.objective_values?.[xMetric]);
          const yValue = Number(candidate.objective_values?.[yMetric]);
          const x = 50 + ((xValue - minX) / (maxX - minX || 1)) * (width - 80);
          const y = 26 + ((maxY - yValue) / (maxY - minY || 1)) * (height - 68);
          return (
            <g key={candidate.id} className={pareto.has(candidate.id) ? "pareto-frontier" : "pareto-candidate"}>
              <circle cx={x} cy={y} r={candidate.is_best ? 8 : 6} />
              <text x={x + 9} y={y - 7} className="pareto-label">{candidate.label ?? candidate.id}</text>
              <title>{t("insights.objectivePoint", {
                candidate: candidate.label ?? candidate.id,
                xMetric,
                xValue: formatNumber(xValue),
                yMetric,
                yValue: formatNumber(yValue),
                feasibility: candidate.feasible === false ? t("insights.infeasibleSuffix") : "",
              })}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function OptimizationInsights({ trials, history }: OptimizationInsightsProps) {
  const { t } = useI18n();
  const candidates = useMemo(
    () => (history && history.items.length > 0 ? aggregateHistory(history) : aggregateCandidates(trials)),
    [history, trials],
  );

  if (candidates.length === 0) {
    return (
      <div className="insight-empty" data-testid="optimization-insights-empty">
        {t("insights.empty")}
      </div>
    );
  }

  return (
    <div className="optimization-insights">
      <div className="insight-grid">
        <div>
          <h3>{t("insights.generationTrend")}</h3>
          <GenerationTrend candidates={candidates} />
        </div>
        <div>
          <h3>{t("insights.tradeoffs")}</h3>
          {history && <ObjectiveParetoPlot history={history} />}
          {history && Object.keys(history.objective_directions).length >= 2 ? null : <ParetoPlot candidates={candidates} />}
        </div>
      </div>
      {history && Object.keys(history.recommendations).length > 0 ? (
        <div className="recommendation-strip">
          {Object.entries(history.recommendations).map(([name, candidateId]) => (
            <span key={name}><strong>{name}</strong>: {history.items.find((item) => item.id === candidateId)?.label ?? candidateId}</span>
          ))}
        </div>
      ) : null}
      <div className="candidate-comparison-wrap">
        <table className="candidate-comparison-table">
          <thead>
            <tr>
              <th>{t("jobDetail.candidate")}</th>
              <th>{t("insights.generation")}</th>
              <th>{t("insights.meanScore")}</th>
              <th>{t("insights.bestAggregate")}</th>
              <th>{t("insights.passRateUp")}</th>
              <th>{t("insights.evidence")}</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate) => (
              <tr key={candidate.id} className={candidate.isBest ? "candidate-row-best" : undefined}>
                <td>
                  <span className="candidate-comparison-name">{candidate.label}</span>
                  {candidate.isBaseline ? <span className="candidate-tag candidate-tag-baseline">{t("jobDetail.baseline")}</span> : null}
                  {candidate.frontier ? <span className="candidate-tag candidate-tag-best">{t("insights.pareto")}</span> : null}
                </td>
                <td>{candidate.isBaseline ? "—" : candidate.generation}</td>
                <td>{formatNumber(candidate.meanScore)}</td>
                <td>{formatNumber(candidate.bestScore)}</td>
                <td>{candidate.passRate === null ? "—" : `${(candidate.passRate * 100).toFixed(0)}%`}</td>
                <td>
                  {t("insights.trialEvidence", { completed: candidate.completed, total: candidate.total })}
                  {candidate.scenarios === null ? "" : ` · ${t("insights.scenarios", { count: candidate.scenarios })}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
