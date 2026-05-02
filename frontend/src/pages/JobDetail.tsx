import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import type {
  Job,
  JobEventInfo,
  JobReport,
  RuntimeState,
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
import { ArtifactsPanel } from "../components/ArtifactsPanel";
import { GazeboLivePanel } from "../components/GazeboLivePanel";

// Polling interval for active jobs. The frontend only polls; all state
// transitions are driven by the backend worker process (Phase 3+). See
// docs/04_API_SPEC.md §12.
const ACTIVE_POLL_INTERVAL_MS = 4000;
const SERVER_OPENAI_ENABLED = String(import.meta.env.VITE_SERVER_OPENAI_ENABLED ?? "false") === "true";

function CandidateCell({
  t,
  optimizerStrategy,
}: {
  t: TrialSummary;
  optimizerStrategy: Job["optimizer_strategy"];
}) {
  const label = t.candidate_label ?? (t.candidate_is_baseline ? "baseline" : "—");
  const isCmaEsOptimizer =
    t.candidate_source_type === "optimizer" && optimizerStrategy === "cma_es";
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
      : tone === "optimizer" && isCmaEsOptimizer
        ? `CMA-ES Gen ${t.candidate_generation_index}`
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

function buildTrialColumns(
  optimizerStrategy: Job["optimizer_strategy"],
): Column<TrialSummary>[] {
  return [
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
    render: (t) => <CandidateCell t={t} optimizerStrategy={optimizerStrategy} />,
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
}

export function JobDetail() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const safeId = jobId ?? "";

  const rerunMutation = useMutation({
    mutationFn: ({
      id,
      openaiApiKey,
      openaiModel,
    }: {
      id: string;
      openaiApiKey?: string;
      openaiModel?: string | null;
    }) =>
      apiClient.rerunJob(id, {
        openai: openaiApiKey
          ? {
              api_key: openaiApiKey,
              model: openaiModel ?? null,
            }
          : undefined,
      }),
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
  const runtimeQuery = useQuery({
    queryKey: ["runtime-state"],
    queryFn: () => apiClient.getRuntimeState(),
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
  const bestTrial = trials.find((trial) => trial.candidate_is_best);
  const pdfArtifact = artifacts.find(
    (a) => a.artifact_type === "pdf_report" || a.mime_type === "application/pdf",
  );

  const isTerminal =
    job.status === "COMPLETED" ||
    job.status === "FAILED" ||
    job.status === "CANCELLED";

  const handleRerun = () => {
    if (job.optimizer_strategy === "gpt" && !SERVER_OPENAI_ENABLED) {
      const freshKey = window.prompt(
        "Enter a fresh OpenAI API key for this GPT rerun:",
      );
      if (!freshKey || freshKey.trim() === "") return;
      rerunMutation.mutate({
        id: job.id,
        openaiApiKey: freshKey.trim(),
        openaiModel: job.openai_model,
      });
      return;
    }
    rerunMutation.mutate({ id: job.id });
  };

  return (
    <section className="stack-md">
      <JobHeader
        job={job}
        onRerun={handleRerun}
        onCancel={() => cancelMutation.mutate(job.id)}
        rerunPending={rerunMutation.isPending}
        cancelPending={cancelMutation.isPending}
        canCancel={!isTerminal}
      />
      {pdfArtifact ? (
        <div>
          <button
            type="button"
            className="btn"
            onClick={() =>
              void apiClient.downloadArtifact(
                pdfArtifact.id,
                pdfArtifact.display_name ?? `${job.id}-report.pdf`,
              )
            }
          >
            Download PDF report
          </button>
        </div>
      ) : null}
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
        <ExecutionBackendCard job={job} runtimeState={runtimeQuery.data ?? null} />
      <ProgressSection job={job} />

      <StatusSpecificTop job={job} report={report} />

      <MetricsCards job={job} report={report} />
      <SectionCard
        title="Best candidate replay"
        description="Trajectory replay renders on Trial Detail using telemetry/trajectory artifacts."
      >
        {bestTrial ? (
          <Link to={`/trials/${bestTrial.id}`}>Open best trial replay</Link>
        ) : (
          <Empty
            title="Replay unavailable"
            description="No best trial is available yet."
          />
        )}
      </SectionCard>

      <GazeboLivePanel />

      {report ? (
        <>
          <SectionCard
            title={
              job.status === "FAILED"
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
            columns={buildTrialColumns(job.optimizer_strategy)}
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

      {artifactsEnabled ? (
        <ArtifactsPanel
          title="Artifacts"
          description="Job-level artifacts and per-trial artifacts recorded by the backend."
          isLoading={artifactsQuery.isLoading}
          emptyDescription="Artifacts will appear once a completed job has generated report or trial outputs."
          sections={[
            {
              heading: `Job artifacts (${artifacts.filter((a) => a.owner_type === "job").length})`,
              artifacts: artifacts.filter((a) => a.owner_type === "job"),
              emptyNote: "No job-level artifacts yet.",
            },
            {
              heading: `Trial artifacts (${artifacts.filter((a) => a.owner_type === "trial").length})`,
              artifacts: artifacts.filter((a) => a.owner_type === "trial"),
              emptyNote: "No trial-level artifacts yet.",
            },
          ]}
        />
      ) : null}

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
  const customPreview = (job.reference_track ?? []).slice(0, 5);
  const advanced = job.advanced_scenario_config;
  const obstacleCount = advanced?.obstacles?.length ?? 0;
  const dropout = advanced?.sensor_degradation?.dropout_rate;
  const gust = advanced?.wind_gusts;
  const battery = advanced?.battery;
  return (
    <SectionCard title="Job summary">
      <ul className="kv-list">
        <li>
          <span className="kv-key">Track type</span>
          <span className="kv-value">{job.track_type}</span>
        </li>
        {job.track_type === "custom" ? (
          <li>
            <span className="kv-key">Custom track</span>
            <span className="kv-value">
              {(job.reference_track ?? []).length} points
              {customPreview.length > 0
                ? ` · preview ${JSON.stringify(customPreview)}`
                : ""}
            </span>
          </li>
        ) : null}
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
        <li>
          <span className="kv-key">Advanced scenario</span>
          <span className="kv-value">
            {advanced
              ? `enabled · gust=${gust?.enabled ? "on" : "off"} · obstacles=${obstacleCount} · dropout=${dropout ?? 0} · battery=${battery?.initial_percent ?? 100}%`
              : "disabled"}
          </span>
        </li>
      </ul>
    </SectionCard>
  );
}

function ExecutionBackendCard({ job, runtimeState }: { job: Job; runtimeState: RuntimeState | null }) {
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
        {job.simulator_backend_requested === "real_cli" && runtimeState ? (
          <>
            <li>
              <span className="kv-key">Platform runtime mode</span>
              <span className="kv-value">{runtimeState.mode_label}</span>
            </li>
            {runtimeState.mode_warning ? (
              <li>
                <span className="kv-key">Runtime warning</span>
                <span className="kv-value">{runtimeState.mode_warning}</span>
              </li>
            ) : null}
            {runtimeState.mode_advisory ? (
              <li>
                <span className="kv-key">Runtime advisory</span>
                <span className="kv-value">Gazebo real mode may run, but the web live-view iframe is not configured.</span>
              </li>
            ) : null}
            <li>
              <span className="kv-key">Runtime detail</span>
              <span className="kv-value">
                {runtimeState.hosted_real_cli_requires_px4
                  ? runtimeState.real_mode_config_complete
                    ? "PX4/Gazebo real mode active. Trials may take significantly longer."
                    : "Hosted B strict real_cli is enabled, but real PX4/Gazebo configuration is incomplete. real_cli jobs will fail early until configuration is fixed."
                  : runtimeState.px4_gazebo_dry_run
                    ? "Developer dry-run mode: no external PX4/Gazebo process is launched."
                    : "Non-strict real_cli mode. Check configuration before assuming PX4/Gazebo is running."}
              </span>
            </li>
          </>
        ) : null}
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
    if (job.optimization_outcome === "success") {
      return (
        <Alert tone="success" title="Acceptance criteria satisfied">
          The tuning loop found a candidate that meets the configured acceptance
          criteria.
        </Alert>
      );
    }
    if (
      job.optimization_outcome === "max_iterations_reached" ||
      job.optimization_outcome === "no_usable_candidate"
    ) {
      return (
        <Alert
          tone="warning"
          title="Search budget exhausted — showing best-so-far parameters"
        >
          No candidate fully satisfied acceptance before the search budget was
          exhausted.
        </Alert>
      );
    }
  }
  if (job.status === "COMPLETED" && !report) {
    return (
      <Alert tone="info" title="Loading report…">
        Fetching the final report.
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
