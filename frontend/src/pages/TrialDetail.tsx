import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { Alert } from "../components/Alert";
import { Loading, ErrorState, Empty } from "../components/States";
import type { Artifact, Trial } from "../types/api";
import { formatDateTime, formatNumber } from "../utils/format";

export function TrialDetail() {
  const { trialId } = useParams<{ trialId: string }>();
  const safeId = trialId ?? "";

  const trialQuery = useQuery({
    queryKey: ["trial", safeId],
    queryFn: () => apiClient.getTrial(safeId),
    enabled: !!safeId,
    retry: false,
  });

  const parentJobId = trialQuery.data?.job_id;
  const artifactsQuery = useQuery({
    queryKey: ["job-artifacts", parentJobId ?? ""],
    queryFn: () => apiClient.listJobArtifacts(parentJobId ?? ""),
    enabled: !!parentJobId,
    retry: false,
  });

  if (trialQuery.isLoading) return <Loading label="Loading trial…" />;
  if (trialQuery.isError || !trialQuery.data) {
    return (
      <ErrorState
        title="Trial not found"
        description={
          trialQuery.error instanceof ApiClientError
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
  const artifacts = artifactsQuery.data ?? [];

  return (
    <section className="stack-md">
      <TrialHeader trial={trial} />
      <TrialMetadata trial={trial} />
      <TrialMetricsSection trial={trial} />
      <TrialArtifactsSection
        trial={trial}
        artifacts={artifacts}
        isLoading={artifactsQuery.isLoading}
      />
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

function TrialArtifactsSection({
  trial,
  artifacts,
  isLoading,
}: {
  trial: Trial;
  artifacts: Artifact[];
  isLoading: boolean;
}) {
  // Phase 8 polish: the job artifacts endpoint returns both job-scoped and
  // trial-scoped artifacts with ``owner_type`` preserved. For real_cli jobs
  // the worker persists trajectory_plot / telemetry_json / worker_log under
  // owner_type="trial", owner_id=<trial.id>. We surface those here so the
  // Trial Detail page shows real artifact metadata instead of mock-only
  // placeholders. Job-scoped artifacts are still listed below so users can
  // reach the job report from the trial page.
  const trialArtifacts = artifacts.filter(
    (a) => a.owner_type === "trial" && a.owner_id === trial.id,
  );
  const jobArtifacts = artifacts.filter((a) => a.owner_type === "job");
  const total = trialArtifacts.length + jobArtifacts.length;
  return (
    <SectionCard
      title="Artifacts"
      description={
        `Artifacts for this trial (scenario ${trial.scenario_type}, seed ${trial.seed})` +
        ` and for its parent job.`
      }
    >
      {isLoading ? (
        <Loading label="Loading artifacts…" />
      ) : total === 0 ? (
        <Empty
          title="No artifacts yet"
          description="Artifacts become available after the parent job completes."
        />
      ) : (
        <div className="stack-md">
          <ArtifactList
            heading={`Trial artifacts (${trialArtifacts.length})`}
            artifacts={trialArtifacts}
            emptyNote={
              trial.simulator_backend === "mock"
                ? "The mock simulator does not produce per-trial artifact files."
                : "No trial-level artifacts were recorded for this trial."
            }
          />
          <ArtifactList
            heading={`Job artifacts (${jobArtifacts.length})`}
            artifacts={jobArtifacts}
            emptyNote="The job has not produced shared artifacts yet."
          />
        </div>
      )}
    </SectionCard>
  );
}

function ArtifactList({
  heading,
  artifacts,
  emptyNote,
}: {
  heading: string;
  artifacts: Artifact[];
  emptyNote: string;
}) {
  return (
    <div>
      <h3 className="section-subheading">{heading}</h3>
      {artifacts.length === 0 ? (
        <p className="form-hint">{emptyNote}</p>
      ) : (
        <ul className="kv-list">
          {artifacts.map((a) => (
            <li key={a.id}>
              <span className="kv-key">
                {a.display_name ?? a.artifact_type}
              </span>
              <span className="kv-value">
                <code>{a.storage_path}</code>
                {a.mime_type ? (
                  <span className="form-hint"> · {a.mime_type}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
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
