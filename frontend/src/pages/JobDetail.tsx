import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import type { Job, JobReport, TrialSummary } from "../types/api";
import { isActiveJobStatus, formatDateTime, formatNumber } from "../utils/format";
import { SectionCard } from "../components/SectionCard";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { Alert } from "../components/Alert";
import { DataTable, type Column } from "../components/DataTable";
import { Loading, ErrorState, Empty } from "../components/States";
import { ComparisonChart } from "../components/ComparisonChart";

// Polling interval used only by the mock client so the UI can demonstrate
// "live" active states without faking backend state anywhere else. See
// docs/04_API_SPEC.md §12 — active jobs are expected to be polled.
const ACTIVE_POLL_INTERVAL_MS = 4000;

const TRIAL_COLUMNS: Column<TrialSummary>[] = [
  {
    key: "id",
    header: "Trial ID",
    render: (t) => (
      <Link to={`/trials/${t.id}`}>
        <code>{t.id}</code>
      </Link>
    ),
  },
  { key: "candidate_id", header: "Candidate", render: (t) => <code>{t.candidate_id}</code> },
  { key: "seed", header: "Seed", render: (t) => t.seed },
  { key: "scenario_type", header: "Scenario", render: (t) => t.scenario_type },
  {
    key: "status",
    header: "Status",
    render: (t) => <StatusBadge status={t.status} />,
  },
  {
    key: "score",
    header: "Score",
    align: "right",
    render: (t) => (t.score === null ? "—" : formatNumber(t.score)),
  },
  {
    key: "action",
    header: "Action",
    align: "right",
    render: (t) => <Link to={`/trials/${t.id}`}>View</Link>,
  },
];

export function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const safeId = jobId ?? "";

  const rerunMutation = useMutation({
    mutationFn: (id: string) => apiClient.rerunJob(id),
    onSuccess: (newJob) => {
      queryClient.invalidateQueries({ queryKey: ["jobs", "dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["jobs", "history"] });
      navigate(`/jobs/${newJob.id}`);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => apiClient.cancelJob(id),
    onSuccess: (updated) => {
      queryClient.setQueryData(["job", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["jobs", "dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["jobs", "history"] });
    },
  });

  const jobQuery = useQuery({
    queryKey: ["job", safeId],
    queryFn: () => apiClient.getJob(safeId),
    enabled: !!safeId,
    refetchInterval: (q) => {
      const j = q.state.data as Job | undefined;
      return j && isActiveJobStatus(j.status) ? ACTIVE_POLL_INTERVAL_MS : false;
    },
  });

  const jobStatus = jobQuery.data?.status;
  const trialsQuery = useQuery({
    queryKey: ["job-trials", safeId],
    queryFn: () => apiClient.listJobTrials(safeId),
    enabled: !!safeId,
    refetchInterval:
      jobStatus && isActiveJobStatus(jobStatus)
        ? ACTIVE_POLL_INTERVAL_MS
        : false,
  });

  const job = jobQuery.data;
  const reportEnabled = job?.status === "COMPLETED";

  const reportQuery = useQuery({
    queryKey: ["job-report", safeId],
    queryFn: () => apiClient.getJobReport(safeId),
    enabled: reportEnabled,
    retry: false,
  });

  if (jobQuery.isLoading) {
    return <Loading label="Loading job…" />;
  }
  if (jobQuery.isError || !job) {
    return (
      <ErrorState
        title="Unable to load job"
        description={
          jobQuery.error instanceof ApiClientError
            ? jobQuery.error.message
            : "Job not found."
        }
        action={<Link to="/history" className="btn">Back to History</Link>}
      />
    );
  }

  const trials = trialsQuery.data ?? [];
  const report = reportQuery.data;

  const isTerminal =
    job.status === "COMPLETED" ||
    job.status === "FAILED" ||
    job.status === "CANCELLED";

  return (
    <section className="stack-md">
      <JobHeader
        job={job}
        onRerun={() => rerunMutation.mutate(job.id)}
        onCancel={() => cancelMutation.mutate(job.id)}
        rerunPending={rerunMutation.isPending}
        cancelPending={cancelMutation.isPending}
        canCancel={!isTerminal}
      />
      {rerunMutation.isError ? (
        <Alert tone="danger" title="Rerun failed">
          {rerunMutation.error instanceof ApiClientError
            ? rerunMutation.error.message
            : "Could not rerun this job."}
        </Alert>
      ) : null}
      {cancelMutation.isError ? (
        <Alert tone="danger" title="Cancel failed">
          {cancelMutation.error instanceof ApiClientError
            ? cancelMutation.error.message
            : "Could not cancel this job."}
        </Alert>
      ) : null}
      <JobSummaryCard job={job} />
      <ProgressSection job={job} />

      <StatusSpecificTop job={job} report={report} />

      <MetricsCards job={job} report={report} />

      {job.status === "COMPLETED" && report ? (
        <>
          <SectionCard
            title="Baseline vs Optimized comparison"
            description="Optimized candidate vs. baseline across the core metrics."
          >
            <ComparisonChart data={report.comparison} />
          </SectionCard>

          <SectionCard
            title="Best parameters"
            description={`From candidate ${report.best_candidate_id}`}
          >
            <ul className="kv-list">
              {Object.entries(report.best_parameters).map(([k, v]) => (
                <li key={k}>
                  <span className="kv-key">{k}</span>
                  <span className="kv-value">{String(v)}</span>
                </li>
              ))}
            </ul>
          </SectionCard>

          <SectionCard title="Summary">
            <p style={{ margin: 0 }}>{report.summary_text}</p>
          </SectionCard>
        </>
      ) : null}

      <SectionCard
        title="Trials"
        description="Per-candidate evaluation runs for this job."
      >
        {trialsQuery.isLoading ? (
          <Loading label="Loading trials…" />
        ) : trialsQuery.isError ? (
          <ErrorState
            description={
              trialsQuery.error instanceof ApiClientError
                ? trialsQuery.error.message
                : "Failed to load trials."
            }
          />
        ) : (
          <DataTable
            columns={TRIAL_COLUMNS}
            rows={trials}
            rowKey={(t) => t.id}
            emptyState={
              <Empty
                title="No trials yet"
                description="Trials will appear here once the worker starts dispatching them."
              />
            }
          />
        )}
      </SectionCard>

      <DiagnosticsPanel job={job} />
    </section>
  );
}

function JobHeader({
  job,
  onRerun,
  onCancel,
  rerunPending,
  cancelPending,
  canCancel,
}: {
  job: Job;
  onRerun: () => void;
  onCancel: () => void;
  rerunPending: boolean;
  cancelPending: boolean;
  canCancel: boolean;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>
          Job <code>{job.id}</code>
        </h1>
        <p className="page-header-subtitle">
          Created {formatDateTime(job.created_at)} · Updated{" "}
          {formatDateTime(job.updated_at)}
        </p>
      </div>
      <div className="page-header-actions">
        <StatusBadge status={job.status} />
        {isActiveJobStatus(job.status) ? (
          <span className="form-hint">Polling every {ACTIVE_POLL_INTERVAL_MS / 1000}s…</span>
        ) : null}
        {canCancel ? (
          <button
            type="button"
            className="btn"
            onClick={onCancel}
            disabled={cancelPending}
          >
            {cancelPending ? "Cancelling…" : "Cancel"}
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn-primary"
          onClick={onRerun}
          disabled={rerunPending}
        >
          {rerunPending ? "Rerunning…" : "Rerun"}
        </button>
      </div>
    </header>
  );
}

function JobSummaryCard({ job }: { job: Job }) {
  return (
    <SectionCard title="Job summary">
      <ul className="kv-list">
        <li>
          <span className="kv-key">Track type</span>
          <span className="kv-value">{job.track_type}</span>
        </li>
        <li>
          <span className="kv-key">Objective profile</span>
          <span className="kv-value">{job.objective_profile}</span>
        </li>
        <li>
          <span className="kv-key">Altitude</span>
          <span className="kv-value">{job.altitude_m} m</span>
        </li>
        <li>
          <span className="kv-key">Start point</span>
          <span className="kv-value">
            ({job.start_point.x}, {job.start_point.y})
          </span>
        </li>
        <li>
          <span className="kv-key">Sensor noise</span>
          <span className="kv-value">{job.sensor_noise_level}</span>
        </li>
        <li>
          <span className="kv-key">Wind (N/E/S/W)</span>
          <span className="kv-value">
            {job.wind.north} / {job.wind.east} / {job.wind.south} /{" "}
            {job.wind.west}
          </span>
        </li>
      </ul>
    </SectionCard>
  );
}

function ProgressSection({ job }: { job: Job }) {
  const { completed_trials, total_trials, current_phase } = job.progress;
  const pct =
    total_trials > 0 ? Math.min(100, (completed_trials / total_trials) * 100) : 0;
  const active = isActiveJobStatus(job.status);
  return (
    <SectionCard
      title="Progress"
      description={
        current_phase ? (
          <>
            Current phase: <code>{current_phase}</code>
          </>
        ) : null
      }
    >
      <div className="progress-bar">
        <div
          className={`progress-bar-fill${active ? " progress-bar-fill-active" : ""}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="form-hint">
        {completed_trials} / {total_trials} trials completed ({pct.toFixed(0)}%)
      </div>
    </SectionCard>
  );
}

function StatusSpecificTop({
  job,
  report,
}: {
  job: Job;
  report: JobReport | undefined;
}) {
  if (job.status === "QUEUED") {
    return (
      <Alert tone="info" title="Job queued">
        The job is queued and waiting for a worker to pick it up. This page will
        auto-refresh while the job is active.
      </Alert>
    );
  }
  if (job.status === "RUNNING") {
    return (
      <Alert tone="info" title="Job running">
        Baseline and optimizer trials are being dispatched. Mock polling is
        simulated in the frontend only.
      </Alert>
    );
  }
  if (job.status === "AGGREGATING") {
    return (
      <Alert tone="info" title="Aggregating results">
        All trials have finished. The backend will select the best candidate and
        emit a report.
      </Alert>
    );
  }
  if (job.status === "CANCELLED") {
    return (
      <Alert tone="warning" title="Job cancelled">
        Cancelled {formatDateTime(job.cancelled_at)}. No report was generated.
      </Alert>
    );
  }
  if (job.status === "FAILED") {
    const err = job.latest_error;
    return (
      <Alert tone="danger" title="Job failed">
        {err ? (
          <>
            <div>
              <strong>{err.code}</strong>: {err.message}
            </div>

          </>
        ) : (
          "Failed with no detailed error reported."
        )}
      </Alert>
    );
  }
  if (job.status === "COMPLETED" && !report) {
    return (
      <Alert tone="info" title="Loading report…">
        Fetching final report from the mock API.
      </Alert>
    );
  }
  return null;
}

function MetricsCards({
  job,
  report,
}: {
  job: Job;
  report: JobReport | undefined;
}) {
  if (job.status === "COMPLETED" && report) {
    const { baseline_metrics: b, optimized_metrics: o } = report;
    return (
      <SectionCard title="Headline metrics">
        <div className="metric-grid">
          <MetricCard
            label="RMSE (optimized)"
            value={`${formatNumber(o.rmse)} m`}
            sub={`baseline ${formatNumber(b.rmse)} m`}
            tone="positive"
          />
          <MetricCard
            label="Max error (optimized)"
            value={`${formatNumber(o.max_error)} m`}
            sub={`baseline ${formatNumber(b.max_error)} m`}
            tone="positive"
          />
          <MetricCard
            label="Overshoot (optimized)"
            value={o.overshoot_count}
            sub={`baseline ${b.overshoot_count}`}
            tone="positive"
          />
          <MetricCard
            label="Completion time"
            value={`${formatNumber(o.completion_time)} s`}
            sub={`baseline ${formatNumber(b.completion_time)} s`}
          />
          <MetricCard
            label="Score"
            value={formatNumber(o.score)}
            sub={`baseline ${formatNumber(b.score)}`}
            tone="positive"
          />
        </div>
      </SectionCard>
    );
  }

  return (
    <SectionCard title="Headline metrics">
      <Empty
        title="Metrics not ready"
        description={
          job.status === "FAILED"
            ? "Job failed before a report could be generated."
            : job.status === "CANCELLED"
              ? "Job was cancelled before completion."
              : "Metrics will appear once the job completes."
        }
      />
    </SectionCard>
  );
}

function DiagnosticsPanel({ job }: { job: Job }) {
  const lines: string[] = [
    `[${formatDateTime(job.created_at)}] job_created id=${job.id}`,
  ];
  if (job.queued_at)
    lines.push(`[${formatDateTime(job.queued_at)}] job_queued`);
  if (job.started_at)
    lines.push(`[${formatDateTime(job.started_at)}] job_started`);
  if (job.progress.current_phase)
    lines.push(
      `[${formatDateTime(job.updated_at)}] phase=${job.progress.current_phase} progress=${job.progress.completed_trials}/${job.progress.total_trials}`,
    );
  if (job.completed_at)
    lines.push(
      `[${formatDateTime(job.completed_at)}] job_completed best_candidate=${job.best_candidate_id ?? "—"}`,
    );
  if (job.failed_at)
    lines.push(
      `[${formatDateTime(job.failed_at)}] job_failed code=${job.latest_error?.code ?? "UNKNOWN"} message=${job.latest_error?.message ?? ""}`,
    );
  if (job.cancelled_at)
    lines.push(`[${formatDateTime(job.cancelled_at)}] job_cancelled`);

  return (
    <SectionCard
      title="Diagnostics / logs"
      description="Structured job events. In Phase 2 this will stream from the backend."
    >
      <pre className="log-panel">{lines.join("\n")}</pre>
    </SectionCard>
  );
}
