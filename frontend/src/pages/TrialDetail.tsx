import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { mockApi, MockApiError } from "../mock/client";
import { SectionCard } from "../components/SectionCard";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { Alert } from "../components/Alert";
import { Loading, ErrorState } from "../components/States";
import type { Trial } from "../types/api";
import { formatDateTime, formatNumber } from "../utils/format";

export function TrialDetail() {
  const { trialId } = useParams<{ trialId: string }>();
  const safeId = trialId ?? "";

  const trialQuery = useQuery({
    queryKey: ["trial", safeId],
    queryFn: () => mockApi.getTrial(safeId),
    enabled: !!safeId,
    retry: false,
  });

  if (trialQuery.isLoading) return <Loading label="Loading trial…" />;
  if (trialQuery.isError || !trialQuery.data) {
    return (
      <ErrorState
        title="Trial not found"
        description={
          trialQuery.error instanceof MockApiError
            ? trialQuery.error.message
            : "We couldn't find that trial."
        }
        action={
          <Link to="/" className="btn">
            Back to Dashboard
          </Link>
        }
      />
    );
  }

  const trial = trialQuery.data;

  return (
    <section className="stack-md">
      <TrialHeader trial={trial} />
      <TrialMetadata trial={trial} />
      <TrialMetricsSection trial={trial} />
      <TrialPlotPlaceholder trial={trial} />
      <FailureDetails trial={trial} />
    </section>
  );
}

function TrialHeader({ trial }: { trial: Trial }) {
  return (
    <header className="page-header">
      <div>
        <h1>
          Trial <code>{trial.id}</code>
        </h1>
        <p className="page-header-subtitle">
          Part of job{" "}
          <Link to={`/jobs/${trial.job_id}`}>
            <code>{trial.job_id}</code>
          </Link>
          {" · "}
          {trial.scenario_type}
        </p>
      </div>
      <div className="page-header-actions">
        <StatusBadge status={trial.status} />
      </div>
    </header>
  );
}

function TrialMetadata({ trial }: { trial: Trial }) {
  return (
    <SectionCard title="Trial metadata">
      <ul className="kv-list">
        <li>
          <span className="kv-key">Candidate ID</span>
          <span className="kv-value">
            <code>{trial.candidate_id}</code>
          </span>
        </li>
        <li>
          <span className="kv-key">Seed</span>
          <span className="kv-value">{trial.seed}</span>
        </li>
        <li>
          <span className="kv-key">Scenario type</span>
          <span className="kv-value">{trial.scenario_type}</span>
        </li>
        <li>
          <span className="kv-key">Attempt count</span>
          <span className="kv-value">{trial.attempt_count}</span>
        </li>
        <li>
          <span className="kv-key">Worker</span>
          <span className="kv-value">{trial.worker_id ?? "—"}</span>
        </li>
        <li>
          <span className="kv-key">Simulator backend</span>
          <span className="kv-value">{trial.simulator_backend ?? "—"}</span>
        </li>
        <li>
          <span className="kv-key">Queued at</span>
          <span className="kv-value">{formatDateTime(trial.queued_at)}</span>
        </li>
        <li>
          <span className="kv-key">Started at</span>
          <span className="kv-value">{formatDateTime(trial.started_at)}</span>
        </li>
        <li>
          <span className="kv-key">Finished at</span>
          <span className="kv-value">{formatDateTime(trial.finished_at)}</span>
        </li>
      </ul>
    </SectionCard>
  );
}

function TrialMetricsSection({ trial }: { trial: Trial }) {
  if (!trial.metrics) {
    return (
      <SectionCard title="Metrics">
        <Alert tone="warning">
          Metrics are not available for this trial
          {trial.status === "FAILED" ? " because it failed." : "."}
        </Alert>
      </SectionCard>
    );
  }
  const m = trial.metrics;
  return (
    <SectionCard title="Metrics">
      <div className="metric-grid">
        <MetricCard label="Score" value={formatNumber(m.score)} />
        <MetricCard label="RMSE" value={`${formatNumber(m.rmse)} m`} />
        <MetricCard label="Max error" value={`${formatNumber(m.max_error)} m`} />
        <MetricCard label="Overshoot" value={m.overshoot_count} />
        <MetricCard
          label="Completion time"
          value={`${formatNumber(m.completion_time)} s`}
        />
        <MetricCard label="Final error" value={`${formatNumber(m.final_error)} m`} />
        <MetricCard
          label="Pass"
          value={m.pass_flag ? "yes" : "no"}
          tone={m.pass_flag ? "positive" : "negative"}
        />
        <MetricCard
          label="Instability"
          value={m.instability_flag ? "yes" : "no"}
          tone={m.instability_flag ? "negative" : "muted"}
        />
      </div>
    </SectionCard>
  );
}

function TrialPlotPlaceholder({ trial }: { trial: Trial }) {
  return (
    <SectionCard
      title="Trajectory / visualization"
      description="A plot will render here in Phase 6 once artifacts are available."
    >
      <div
        className="state-block"
        style={{ minHeight: 160, justifyContent: "center" }}
      >
        <div className="state-title">Plot placeholder</div>
        <div className="state-description">
          Scenario: <code>{trial.scenario_type}</code> · Seed: {trial.seed}
        </div>
      </div>
    </SectionCard>
  );
}

function FailureDetails({ trial }: { trial: Trial }) {
  if (trial.status !== "FAILED") return null;
  return (
    <SectionCard title="Failure details">
      <Alert tone="danger" title={trial.failure_code ?? "Trial failed"}>
        {trial.failure_reason ?? "No failure reason reported."}
      </Alert>
      {trial.log_excerpt ? (
        <pre className="log-panel">{trial.log_excerpt}</pre>
      ) : null}
    </SectionCard>
  );
}
