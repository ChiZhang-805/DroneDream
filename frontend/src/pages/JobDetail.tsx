import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import type {
  Artifact,
  Job,
  JobEventInfo,
  JobReport,
  OpenAIConfig,
  TrialSummary,
} from "../types/api";
import { isActiveJobStatus, formatDateTime, formatNumber } from "../utils/format";
import { SectionCard } from "../components/SectionCard";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { Alert } from "../components/Alert";
import { DataTable, type Column } from "../components/DataTable";
import { Loading, ErrorState, Empty } from "../components/States";
import { ComparisonChart } from "../components/ComparisonChart";

// Polling interval for active jobs. The frontend only polls; all state
// transitions are driven by the backend worker process (Phase 3+). See
// docs/04_API_SPEC.md §12.
const ACTIVE_POLL_INTERVAL_MS = 4000;

function CandidateCell({ t }: { t: TrialSummary }) {
  const label = t.candidate_label ?? (t.candidate_is_baseline ? "baseline" : "—");
  // Phase 8: "llm_optimizer" rows must render as GPT Gen N, not collapse into
  // "Baseline". Tone classes fall through to "optimizer" for the LLM variant
  // so the existing CSS (orange/heuristic) still applies.
  const source = t.candidate_source_type;
  const tone: "baseline" | "optimizer" | "llm_optimizer" =
    source === "optimizer"
      ? "optimizer"
      : source === "llm_optimizer"
        ? "llm_optimizer"
        : "baseline";
  const toneClass = tone === "llm_optimizer" ? "optimizer" : tone;
  const tagText =
    tone === "baseline"
      ? "Baseline"
      : tone === "optimizer"
        ? `Heuristic #${t.candidate_generation_index}`
        : `GPT Gen ${t.candidate_generation_index}`;
  return (
    <span className="candidate-cell">
      <span className={`candidate-tag candidate-tag-${toneClass}`}>
        {tagText}
      </span>
      {t.candidate_is_best ? (
        <span className="candidate-tag candidate-tag-best">Best</span>
      ) : null}
      <code className="candidate-id">{label}</code>
    </span>
  );
}

// Phase 8 polish: a trial's `status` (COMPLETED / FAILED / ...) only says
// whether the trial executed; `pass_flag` says whether it met per-trial
// acceptance (within error envelopes, no instability/crash/timeout). We
// render both so users can see at a glance which completed trials actually
// passed. ``null`` means the trial has no metric yet (queued/running or a
// hard failure without metrics) and is rendered as "—".
function PassBadge({ pass_flag }: { pass_flag: boolean | null }) {
  if (pass_flag === null) return <span className="form-hint">—</span>;
  return (
    <span
      className={`candidate-tag candidate-tag-${pass_flag ? "best" : "baseline"}`}
      aria-label={pass_flag ? "Trial passed" : "Trial failed"}
    >
      {pass_flag ? "PASS" : "FAIL"}
    </span>
  );
}

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
  {
    key: "candidate",
    header: "Candidate",
    render: (t) => <CandidateCell t={t} />,
  },
  { key: "seed", header: "Seed", render: (t) => t.seed },
  { key: "scenario_type", header: "Scenario", render: (t) => t.scenario_type },
  {
    key: "status",
    header: "Status",
    render: (t) => <StatusBadge status={t.status} />,
  },
  {
    key: "pass",
    header: "Pass",
    render: (t) => <PassBadge pass_flag={t.pass_flag} />,
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
    mutationFn: (args: { id: string; openai?: OpenAIConfig | null }) =>
      apiClient.rerunJob(
        args.id,
        args.openai !== undefined ? { openai: args.openai } : undefined,
      ),
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
  // Phase 8: FAILED jobs (e.g. MAX_ITERATIONS_REACHED) may still have a
  // best-so-far READY report; the backend returns it if available and
  // otherwise returns JOB_FAILED, which we handle as a reportQuery error.
  const reportEnabled = job?.status === "COMPLETED" || job?.status === "FAILED";
  const artifactsEnabled =
    job?.status === "COMPLETED" ||
    job?.status === "FAILED" ||
    job?.status === "CANCELLED";

  const reportQuery = useQuery({
    queryKey: ["job-report", safeId],
    queryFn: () => apiClient.getJobReport(safeId),
    enabled: reportEnabled,
    retry: false,
  });

  const artifactsQuery = useQuery({
    queryKey: ["job-artifacts", safeId],
    queryFn: () => apiClient.listJobArtifacts(safeId),
    enabled: artifactsEnabled,
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
  const artifacts = artifactsQuery.data ?? [];

  const isTerminal =
    job.status === "COMPLETED" ||
    job.status === "FAILED" ||
    job.status === "CANCELLED";

  return (
    <section className="stack-md">
      <JobHeader
        job={job}
        onRerun={(openai) => rerunMutation.mutate({ id: job.id, openai })}
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
      <ExecutionBackendCard job={job} />
      <ProgressSection job={job} />

      <StatusSpecificTop job={job} report={report} />

      <MetricsCards job={job} report={report} />

      {report ? (
        <>
          <SectionCard
            title={
              // Phase 8 product alignment: budget-exhausted jobs are now
              // COMPLETED (not FAILED) but still show best-so-far results,
              // so surface the "Best-so-far" label for those too.
              job.status === "FAILED" ||
              job.optimization_outcome === "max_iterations_reached" ||
              job.optimization_outcome === "no_usable_candidate"
                ? "Best-so-far: Baseline vs Optimized comparison"
                : "Baseline vs Optimized comparison"
            }
            description="Optimized candidate vs. baseline across the core metrics."
          >
            <ComparisonChart data={report.comparison} />
          </SectionCard>

          <BestParametersSection job={job} report={report} />

          <SectionCard
            title="Summary"
            description="Deterministic local summary — no external LLM call."
          >
            <p style={{ margin: 0 }}>{report.summary_text}</p>
          </SectionCard>
        </>
      ) : null}

      {reportEnabled && reportQuery.isError && job.status === "COMPLETED" ? (
        <Alert tone="danger" title="Report unavailable">
          {reportQuery.error instanceof ApiClientError
            ? reportQuery.error.message
            : "Could not load the job report."}
        </Alert>
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

      <ArtifactsPanel
        artifacts={artifacts}
        visible={artifactsEnabled}
        isLoading={artifactsQuery.isLoading}
      />

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
  onRerun: (openai: OpenAIConfig | null | undefined) => void;
  onCancel: () => void;
  rerunPending: boolean;
  cancelPending: boolean;
  canCancel: boolean;
}) {
  const isGpt = job.optimizer_strategy === "gpt";
  const [rerunOpen, setRerunOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [modelOverride, setModelOverride] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  function handleRerunClick() {
    if (isGpt) {
      setRerunOpen((prev) => !prev);
      setFormError(null);
      return;
    }
    onRerun(undefined);
  }

  function handleConfirmGptRerun() {
    const trimmed = apiKey.trim();
    if (trimmed === "") {
      setFormError(
        "Please enter a fresh OpenAI API key. The key from the original job is wiped once it finishes.",
      );
      return;
    }
    const modelTrim = modelOverride.trim();
    onRerun({ api_key: trimmed, model: modelTrim === "" ? null : modelTrim });
  }

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
          onClick={handleRerunClick}
          disabled={rerunPending}
          aria-expanded={isGpt ? rerunOpen : undefined}
        >
          {rerunPending
            ? "Rerunning…"
            : isGpt
              ? rerunOpen
                ? "Cancel rerun"
                : "Rerun with new API key"
              : "Rerun"}
        </button>
      </div>
      {isGpt && rerunOpen ? (
        <div
          className="stack-md"
          style={{ gridColumn: "1 / -1", width: "100%" }}
          aria-label="Rerun GPT job"
        >
          <SectionCard
            title="Rerun this GPT job"
            description="GPT jobs keep their optimizer strategy on rerun. Please provide a fresh OpenAI API key — the original job's encrypted key was wiped when it finished."
          >
            <div className="form-grid">
              <div className="form-field">
                <label htmlFor="rerun_api_key" className="form-field-required">
                  OpenAI API Key
                </label>
                <input
                  id="rerun_api_key"
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <span className="form-hint">
                  Sent to the backend over HTTPS, stored encrypted for the
                  duration of the new job, and purged on completion.
                </span>
              </div>
              <div className="form-field">
                <label htmlFor="rerun_model">OpenAI Model (optional)</label>
                <input
                  id="rerun_model"
                  type="text"
                  value={modelOverride}
                  onChange={(e) => setModelOverride(e.target.value)}
                  placeholder={job.openai_model ?? ""}
                />
                <span className="form-hint">
                  Leave blank to reuse{" "}
                  <code>{job.openai_model ?? "the backend default"}</code>.
                </span>
              </div>
            </div>
            {formError ? (
              <Alert tone="danger" title="Cannot rerun yet">
                {formError}
              </Alert>
            ) : null}
            <div className="form-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleConfirmGptRerun}
                disabled={rerunPending}
              >
                {rerunPending ? "Submitting…" : "Confirm GPT rerun"}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setRerunOpen(false);
                  setApiKey("");
                  setModelOverride("");
                  setFormError(null);
                }}
                disabled={rerunPending}
              >
                Cancel
              </button>
            </div>
          </SectionCard>
        </div>
      ) : null}
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

function ExecutionBackendCard({ job }: { job: Job }) {
  const ac = job.acceptance_criteria;
  return (
    <SectionCard
      title="Execution Backend & Auto-Tuning"
      description="Simulator backend, optimizer strategy, and acceptance criteria for this job."
    >
      <ul className="kv-list">
        <li>
          <span className="kv-key">Simulator backend</span>
          <span className="kv-value">
            <code>{job.simulator_backend_requested}</code>
          </span>
        </li>
        <li>
          <span className="kv-key">Optimizer strategy</span>
          <span className="kv-value">
            <code>{job.optimizer_strategy}</code>
            {job.openai_model ? (
              <span className="form-hint"> · model {job.openai_model}</span>
            ) : null}
          </span>
        </li>
        <li>
          <span className="kv-key">Current generation</span>
          <span className="kv-value">
            {job.current_generation} of max {job.max_iterations}
          </span>
        </li>
        <li>
          <span className="kv-key">Trials per candidate</span>
          <span className="kv-value">{job.trials_per_candidate}</span>
        </li>
        <li>
          <span className="kv-key">Acceptance criteria</span>
          <span className="kv-value">
            {ac.target_rmse !== null ? (
              <>RMSE ≤ {formatNumber(ac.target_rmse)} m · </>
            ) : null}
            {ac.target_max_error !== null ? (
              <>max error ≤ {formatNumber(ac.target_max_error)} m · </>
            ) : null}
            {/* Phase 8 polish: "pass rate" means the per-trial pass_flag rate
                (fraction of dispatched trials whose pass_flag is true), NOT
                the execution-completion ratio. The outcome only reports
                "success" when this rate meets the threshold. */}
            trial pass rate ≥ {Math.round(ac.min_pass_rate * 100)}%
          </span>
        </li>
        {job.optimization_outcome ? (
          <li>
            <span className="kv-key">Outcome</span>
            <span className="kv-value">
              <code>{job.optimization_outcome}</code>
            </span>
          </li>
        ) : null}
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
        Baseline trials are being dispatched and executed by the worker. This
        page auto-refreshes while the job is active.
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
    const outcome = job.optimization_outcome;
    const hasBestSoFar = Boolean(report);
    const title = hasBestSoFar
      ? "Job failed — best-so-far results available"
      : "Job failed";
    const outcomeLabel =
      outcome === "max_iterations_reached"
        ? "Max iterations reached before any candidate passed the acceptance criteria."
        : outcome === "no_usable_candidate"
          ? "No candidate produced usable metrics."
          : outcome === "llm_failed"
            ? "GPT parameter proposer failed; see the job event log."
            : outcome === "simulator_unavailable"
              ? "Simulator adapter was unavailable."
              : null;
    return (
      <Alert tone={hasBestSoFar ? "warning" : "danger"} title={title}>
        {err ? (
          <div>
            <strong>{err.code}</strong>: {err.message}
          </div>
        ) : (
          <div>Failed with no detailed error reported.</div>
        )}
        {outcomeLabel ? <div style={{ marginTop: 4 }}>{outcomeLabel}</div> : null}
        {hasBestSoFar ? (
          <div style={{ marginTop: 4 }}>
            Best-so-far parameters and baseline-vs-optimized metrics are shown below.
          </div>
        ) : null}
      </Alert>
    );
  }
  if (job.status === "COMPLETED") {
    if (!report) {
      return (
        <Alert tone="info" title="Loading report…">
          Fetching the final report.
        </Alert>
      );
    }
    const outcome = job.optimization_outcome;
    if (outcome === "max_iterations_reached" || outcome === "no_usable_candidate") {
      const reason =
        outcome === "max_iterations_reached"
          ? `the ${job.max_iterations}-iteration tuning budget was exhausted`
          : "no candidate produced usable metrics";
      return (
        <Alert
          tone="warning"
          title="Search budget exhausted — showing best-so-far parameters"
        >
          The optimizer stopped because {reason}. The best-so-far parameters
          and their baseline-vs-optimized metrics are shown below — they are
          the best candidate observed, not a fully accepted solution.
        </Alert>
      );
    }
    if (outcome === "llm_failed") {
      return (
        <Alert tone="warning" title="GPT proposer failed — best-so-far shown">
          The GPT parameter proposer failed and the job fell back to the
          best-so-far candidate. See the diagnostics log for the raw error.
        </Alert>
      );
    }
    if (outcome === "success") {
      return (
        <Alert tone="success" title="Acceptance criteria satisfied">
          A candidate met all configured acceptance criteria.
        </Alert>
      );
    }
    return null;
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
  if (
    (job.status === "COMPLETED" || job.status === "FAILED") &&
    report
  ) {
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

function BestParametersSection({
  job,
  report,
}: {
  job: Job;
  report: JobReport;
}) {
  const baselineWon = report.best_candidate_id === job.baseline_candidate_id;
  return (
    <SectionCard
      title="Best parameters"
      description={
        baselineWon
          ? "Baseline outperformed every optimizer candidate — baseline parameters are the recommended result."
          : "Parameters from the winning optimizer candidate. Baseline shown for comparison."
      }
    >
      <div className="best-parameters-head">
        <span
          className={`candidate-tag ${
            baselineWon ? "candidate-tag-baseline" : "candidate-tag-optimizer"
          }`}
        >
          {baselineWon ? "Baseline winner" : "Optimizer winner"}
        </span>
        <code className="candidate-id">{report.best_candidate_id}</code>
      </div>
      <ul className="kv-list">
        {Object.entries(report.best_parameters).map(([k, v]) => (
          <li key={k}>
            <span className="kv-key">{k}</span>
            <span className="kv-value">{String(v)}</span>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

function ArtifactsPanel({
  artifacts,
  visible,
  isLoading,
}: {
  artifacts: Artifact[];
  visible: boolean;
  isLoading: boolean;
}) {
  if (!visible) return null;
  return (
    <SectionCard
      title="Artifacts"
      description="Metadata for report assets produced by the worker. Mock entries in the MVP — no underlying files yet."
    >
      {isLoading ? (
        <Loading label="Loading artifacts…" />
      ) : artifacts.length === 0 ? (
        <Empty
          title="No artifacts yet"
          description="Artifacts will appear once a completed job has generated its report."
        />
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
    </SectionCard>
  );
}

/** Build the fallback diagnostic lines from the job's timestamp columns. Used
 *  when the backend has not yet populated `recent_events` (e.g. a stale job
 *  record from before Phase 6). */
function synthesizeDiagnosticLines(job: Job): string[] {
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
  return lines;
}

function formatEventLine(e: JobEventInfo): string {
  const payloadKeys = e.payload ? Object.keys(e.payload) : [];
  const payloadBits = payloadKeys
    .slice(0, 3)
    .map((k) => {
      const raw = e.payload?.[k];
      const value =
        typeof raw === "string" || typeof raw === "number" || typeof raw === "boolean"
          ? String(raw)
          : JSON.stringify(raw);
      return `${k}=${value}`;
    })
    .join(" ");
  return `[${formatDateTime(e.created_at)}] ${e.event_type}${payloadBits ? " " + payloadBits : ""}`;
}

function DiagnosticsPanel({ job }: { job: Job }) {
  const events = job.recent_events ?? [];
  // `recent_events` is returned newest-first by the backend. The log panel
  // reads naturally oldest-first, so reverse before formatting.
  const eventLines = [...events].reverse().map(formatEventLine);
  const lines = eventLines.length > 0 ? eventLines : synthesizeDiagnosticLines(job);

  return (
    <SectionCard
      title="Diagnostics / logs"
      description={
        eventLines.length > 0
          ? `Last ${events.length} structured job events from the backend.`
          : "Structured job events derived from the backend job state."
      }
    >
      <pre className="log-panel">{lines.join("\n")}</pre>
    </SectionCard>
  );
}
