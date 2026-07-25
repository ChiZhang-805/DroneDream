import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import type {
  Job,
  JobEventInfo,
  JobReport,
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
import { OptimizationInsights } from "../components/OptimizationInsights";
import {
  optimizerStrategyDescription,
  optimizerStrategyLabel,
} from "../features/experiment/optimizerStrategies";
import { optimizerUsesModelAccess } from "../types/api";
import { useI18n } from "../i18n/I18nProvider";

// Polling interval for active jobs. The frontend only polls; all state
// transitions are driven by the backend worker process (Phase 3+). See
// docs/04_API_SPEC.md §12.
const ACTIVE_POLL_INTERVAL_MS = 4000;

function CandidateCell({
  t,
  optimizerStrategy,
}: {
  t: TrialSummary;
  optimizerStrategy: Job["optimizer_strategy"];
}) {
  const { t: translate } = useI18n();
  const displayedStrategy = t.candidate_optimizer_strategy ?? optimizerStrategy;
  const label = t.candidate_label ?? (t.candidate_is_baseline ? translate("jobDetail.baseline") : "—");
  const isCmaEsOptimizer =
    t.candidate_source_type === "optimizer" && displayedStrategy === "cma_es";
  const isExperimentalOptimizer = ![
    "none",
    "heuristic",
    "gpt",
    "cma_es",
  ].includes(displayedStrategy);
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
  const strategyLabel = optimizerStrategyLabel(displayedStrategy, translate);
  let tagText = translate("jobDetail.gptGeneration", { count: t.candidate_generation_index });
  if (tone === "baseline") {
    tagText = translate("jobDetail.baseline");
  } else if (tone === "optimizer" && isCmaEsOptimizer) {
    tagText = translate("jobDetail.cmaGeneration", { count: t.candidate_generation_index });
  } else if (tone === "optimizer" && !isExperimentalOptimizer) {
    tagText = translate("jobDetail.heuristicGeneration", { count: t.candidate_generation_index });
  } else if (tone === "optimizer") {
    tagText = translate("jobDetail.strategyGeneration", {
      strategy: strategyLabel,
      count: t.candidate_generation_index,
    });
  }
  return (
    <span className="candidate-cell">
      <span className={`candidate-tag candidate-tag-${toneClass}`}>
        {tagText}
      </span>
      {t.candidate_is_best ? (
        <span className="candidate-tag candidate-tag-best">{translate("jobDetail.best")}</span>
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
  const { t } = useI18n();
  if (pass_flag === null) return <span className="form-hint">—</span>;
  return (
    <span
      className={`candidate-tag candidate-tag-${pass_flag ? "best" : "baseline"}`}
      aria-label={pass_flag ? t("jobDetail.trialPassed") : t("jobDetail.trialFailed")}
    >
      {pass_flag ? t("jobDetail.pass") : t("jobDetail.fail")}
    </span>
  );
}

function buildTrialColumns(
  optimizerStrategy: Job["optimizer_strategy"],
  translate: ReturnType<typeof useI18n>["t"],
): Column<TrialSummary>[] {
  return [
  {
    key: "id",
    header: translate("jobDetail.trialId"),
    render: (t) => (
      <Link to={`/trials/${t.id}`}>
        <code>{t.id}</code>
      </Link>
    ),
  },
  {
    key: "candidate",
    header: translate("jobDetail.candidate"),
    render: (t) => <CandidateCell t={t} optimizerStrategy={optimizerStrategy} />,
  },
  { key: "seed", header: translate("trial.seed"), render: (t) => t.seed },
  { key: "scenario_type", header: translate("trajectory.scenario"), render: (t) => t.scenario_type },
  {
    key: "status",
    header: translate("jobCompare.status"),
    render: (t) => <StatusBadge status={t.status} />,
  },
  {
    key: "pass",
    header: translate("trial.pass"),
    render: (t) => <PassBadge pass_flag={t.pass_flag} />,
  },
  {
    key: "score",
    header: translate("trial.score"),
    align: "right",
    render: (t) => (t.score === null ? "—" : formatNumber(t.score)),
  },
  {
    key: "action",
    header: translate("jobDetail.action"),
    align: "right",
    render: (t) => <Link to={`/trials/${t.id}`}>{translate("jobDetail.view")}</Link>,
  },
  ];
}

export function JobDetail() {
  const { t } = useI18n();
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const safeId = jobId ?? "";
  const [pdfDownloadError, setPdfDownloadError] = useState(false);

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

  const candidatesQuery = useQuery({
    queryKey: ["job-candidates", safeId],
    queryFn: () => apiClient.listJobCandidates(safeId),
    enabled: !!safeId,
    refetchInterval:
      jobStatus && isActiveJobStatus(jobStatus)
        ? ACTIVE_POLL_INTERVAL_MS
        : false,
    retry: false,
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
    return <Loading label={t("jobDetail.loading")} />;
  }
  if (jobQuery.isError || !job) {
    return (
      <ErrorState
        title={t("jobDetail.loadFailed")}
        description={
          jobQuery.error instanceof ApiClientError
            ? jobQuery.error.message
            : t("jobDetail.notFound")
        }
        action={<Link to="/history" className="btn">{t("jobDetail.backHistory")}</Link>}
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
    if (optimizerUsesModelAccess(job.optimizer_strategy)) {
      const freshKey = window.prompt(
        t("jobDetail.apiKeyPrompt"),
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
            onClick={() => {
              setPdfDownloadError(false);
              void apiClient.downloadArtifact(
                pdfArtifact.id,
                pdfArtifact.display_name ?? `${job.id}-report.pdf`,
              ).catch(() => setPdfDownloadError(true));
            }}
          >
            {t("jobDetail.downloadPdf")}
          </button>
        </div>
      ) : null}
      {pdfDownloadError ? (
        <p className="form-error" role="alert">{t("artifact.downloadFailed")}</p>
      ) : null}
      {rerunMutation.isError ? (
        <Alert tone="danger" title={t("jobDetail.rerunFailed")}>
          {rerunMutation.error instanceof ApiClientError
            ? rerunMutation.error.message
            : t("jobDetail.rerunFailedBody")}
        </Alert>
      ) : null}
      {cancelMutation.isError ? (
        <Alert tone="danger" title={t("jobDetail.cancelFailed")}>
          {cancelMutation.error instanceof ApiClientError
            ? cancelMutation.error.message
            : t("jobDetail.cancelFailedBody")}
        </Alert>
      ) : null}
      <JobSummaryCard job={job} />
      <ExecutionBackendCard job={job} />
      <ProgressSection job={job} />

      <StatusSpecificTop job={job} report={report} />

      <MetricsCards job={job} report={report} />
      {report?.optimized_metrics.holdout ? (
        <HoldoutValidationSummary holdout={report.optimized_metrics.holdout} />
      ) : null}
      <SectionCard
        title={t("jobDetail.bestReplay")}
        description={t("jobDetail.bestReplayDescription")}
      >
        {bestTrial ? (
          <Link to={`/trials/${bestTrial.id}`}>{t("jobDetail.openBestReplay")}</Link>
        ) : (
          <Empty
            title={t("trajectory.unavailable")}
            description={t("jobDetail.noBestTrial")}
          />
        )}
      </SectionCard>

      <GazeboLivePanel />

      {report ? (
        <>
          <SectionCard
            title={
              job.status === "FAILED"
                ? t("jobDetail.bestSoFarComparison")
                : t("comparison.ariaLabel")
            }
            description={t("jobDetail.comparisonDescription")}
          >
            <ComparisonChart data={report.comparison} />
          </SectionCard>

          <BestParametersSection job={job} report={report} />

          <SectionCard
            title={t("jobDetail.summary")}
            description={t("jobDetail.summaryDescription")}
          >
            <p style={{ margin: 0 }}>{report.summary_text}</p>
          </SectionCard>
        </>
      ) : null}

      {reportEnabled && reportQuery.isError && job.status === "COMPLETED" ? (
        <Alert tone="danger" title={t("jobDetail.reportUnavailable")}>
          {reportQuery.error instanceof ApiClientError
            ? reportQuery.error.message
            : t("jobDetail.reportUnavailableBody")}
        </Alert>
      ) : null}

      <SectionCard
        title={t("jobDetail.insights")}
        description={t("jobDetail.insightsDescription")}
      >
        {trialsQuery.isLoading ? (
          <Loading label={t("jobDetail.loadingEvidence")} />
        ) : trialsQuery.isError ? (
          <div className="insight-empty">
            {t("jobDetail.insightsUnavailable")}
          </div>
        ) : (
          <>
            {candidatesQuery.isError ? (
              <p className="form-hint insight-fallback-note">
                {t("jobDetail.insightsFallback")}
              </p>
            ) : null}
            <OptimizationInsights
              trials={trials}
              history={candidatesQuery.data}
            />
          </>
        )}
      </SectionCard>

      <SectionCard
        title={t("jobDetail.trials")}
        description={t("jobDetail.trialsDescription")}
      >
        {trialsQuery.isLoading ? (
          <Loading label={t("jobDetail.loadingTrials")} />
        ) : trialsQuery.isError ? (
          <ErrorState
            description={
              trialsQuery.error instanceof ApiClientError
                ? trialsQuery.error.message
                : t("jobDetail.trialsLoadFailed")
            }
          />
        ) : (
          <DataTable
            columns={buildTrialColumns(job.optimizer_strategy, t)}
            rows={trials}
            rowKey={(t) => t.id}
            emptyState={
              <Empty
                title={t("jobDetail.noTrials")}
                description={t("jobDetail.noTrialsDescription")}
              />
            }
          />
        )}
      </SectionCard>

      {artifactsEnabled ? (
        <ArtifactsPanel
          title={t("artifacts.title")}
          description={t("jobDetail.artifactsDescription")}
          isLoading={artifactsQuery.isLoading}
          emptyDescription={t("jobDetail.artifactsEmpty")}
          sections={[
            {
              heading: t("trial.jobArtifacts", { count: artifacts.filter((a) => a.owner_type === "job").length }),
              artifacts: artifacts.filter((a) => a.owner_type === "job"),
              emptyNote: t("jobDetail.noJobArtifacts"),
            },
            {
              heading: t("trial.trialArtifacts", { count: artifacts.filter((a) => a.owner_type === "trial").length }),
              artifacts: artifacts.filter((a) => a.owner_type === "trial"),
              emptyNote: t("jobDetail.noTrialArtifacts"),
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
  const { t } = useI18n();
  return (
    <header className="page-header">
      <div>
        <h1>
          {t("jobDetail.job")} <code>{job.id}</code>
        </h1>
        <p className="page-header-subtitle">
          {t("jobDetail.createdUpdated", {
            created: formatDateTime(job.created_at),
            updated: formatDateTime(job.updated_at),
          })}
        </p>
      </div>
      <div className="page-header-actions">
        <StatusBadge status={job.status} />
        {isActiveJobStatus(job.status) ? (
          <span className="form-hint">
            {t("jobDetail.polling", { seconds: ACTIVE_POLL_INTERVAL_MS / 1000 })}
          </span>
        ) : null}
        {canCancel ? (
          <button
            type="button"
            className="btn"
            onClick={onCancel}
            disabled={cancelPending}
          >
            {cancelPending ? t("jobDetail.cancelling") : t("jobDetail.cancel")}
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn-primary"
          onClick={onRerun}
          disabled={rerunPending}
        >
          {rerunPending ? t("jobDetail.rerunning") : t("jobDetail.rerun")}
        </button>
      </div>
    </header>
  );
}

function JobSummaryCard({ job }: { job: Job }) {
  const { t } = useI18n();
  const customPreview = (job.reference_track ?? []).slice(0, 5);
  const advanced = job.advanced_scenario_config;
  const obstacleCount = advanced?.obstacles?.length ?? 0;
  const dropout = advanced?.sensor_degradation?.dropout_rate;
  const gust = advanced?.wind_gusts;
  const battery = advanced?.battery;
  return (
    <SectionCard title={t("jobDetail.jobSummary")}>
      <ul className="kv-list">
        <li>
          <span className="kv-key">{t("jobDetail.trackType")}</span>
          <span className="kv-value">{job.track_type}</span>
        </li>
        {job.track_type === "custom" ? (
          <li>
            <span className="kv-key">{t("jobDetail.customTrack")}</span>
            <span className="kv-value">
              {t("jobDetail.trackPoints", { count: (job.reference_track ?? []).length })}
              {customPreview.length > 0
                ? ` · ${t("jobDetail.preview")} ${JSON.stringify(customPreview)}`
                : ""}
            </span>
          </li>
        ) : null}
        <li>
          <span className="kv-key">{t("jobDetail.objectiveProfile")}</span>
          <span className="kv-value">{job.objective_profile}</span>
        </li>
        {job.vehicle_profile ? (
          <li>
            <span className="kv-key">{t("jobDetail.vehicleFirmware")}</span>
            <span className="kv-value">
              {job.vehicle_profile.airframe} · {job.vehicle_profile.simulator_model} · PX4 {job.vehicle_profile.px4_version}
              {job.vehicle_profile.firmware_commit ? ` @ ${job.vehicle_profile.firmware_commit}` : ""}
            </span>
          </li>
        ) : null}
        {job.parameter_space && job.parameter_space.length > 0 ? (
          <li>
            <span className="kv-key">{t("jobDetail.tunableParameters")}</span>
            <span className="kv-value">
              {t("jobDetail.dimensions", { count: job.parameter_space.filter((parameter) => parameter.enabled && !parameter.locked).length })} · {job.parameter_space.map((parameter) => parameter.name).join(", ")}
            </span>
          </li>
        ) : null}
        {job.scenario_suite ? (
          <li>
            <span className="kv-key">{t("jobDetail.scenarioSuite")}</span>
            <span className="kv-value">
              {t("jobDetail.scenarioSuiteValue", {
                search: job.scenario_suite.cases.filter((scenario) => scenario.enabled && !scenario.holdout).length,
                holdout: job.scenario_suite.cases.filter((scenario) => scenario.enabled && scenario.holdout).length,
                matched: job.scenario_suite.common_random_numbers ? t("common.yes") : t("common.no"),
              })}
            </span>
          </li>
        ) : null}
        <li>
          <span className="kv-key">{t("jobDetail.altitude")}</span>
          <span className="kv-value">{job.altitude_m} m</span>
        </li>
        <li>
          <span className="kv-key">{t("jobDetail.startPoint")}</span>
          <span className="kv-value">
            ({job.start_point.x}, {job.start_point.y})
          </span>
        </li>
        <li>
          <span className="kv-key">{t("jobDetail.sensorNoise")}</span>
          <span className="kv-value">{job.sensor_noise_level}</span>
        </li>
        <li>
          <span className="kv-key">{t("jobDetail.wind")}</span>
          <span className="kv-value">
            {job.wind.north} / {job.wind.east} / {job.wind.south} /{" "}
            {job.wind.west}
          </span>
        </li>
        <li>
          <span className="kv-key">{t("jobDetail.advancedScenario")}</span>
          <span className="kv-value">
            {advanced
              ? t("jobDetail.advancedScenarioValue", {
                  gust: gust?.enabled ? t("common.yes") : t("common.no"),
                  obstacles: obstacleCount,
                  dropout: dropout ?? 0,
                  battery: battery?.initial_percent ?? 100,
                })
              : t("jobDetail.disabled")}
          </span>
        </li>
      </ul>
    </SectionCard>
  );
}

function ExecutionBackendCard({ job }: { job: Job }) {
  const { t } = useI18n();
  const ac = job.acceptance_criteria;
  return (
    <SectionCard
      title={t("jobDetail.execution")}
      description={t("jobDetail.executionDescription")}
    >
      <ul className="kv-list">
        <li>
          <span className="kv-key">{t("trial.simulatorBackend")}</span>
          <span className="kv-value">
            <code>{job.simulator_backend_requested}</code>
          </span>
        </li>
        <li>
          <span className="kv-key">{t("job.optimizerStrategy")}</span>
          <span className="kv-value">
            <strong>{optimizerStrategyLabel(job.optimizer_strategy, t)}</strong>
            <span className="form-hint">
              {" "}· {optimizerStrategyDescription(job.optimizer_strategy, t)}
            </span>
            {job.openai_model ? (
              <span className="form-hint"> · {t("jobDetail.model")} {job.openai_model}</span>
            ) : null}
            {job.llm_provider ? (
              <span className="form-hint"> · {t("jobDetail.provider")} {job.llm_provider}</span>
            ) : null}
          </span>
        </li>
        <li>
          <span className="kv-key">{t("jobDetail.currentGeneration")}</span>
          <span className="kv-value">
            {t("jobDetail.generationValue", { current: job.current_generation, max: job.max_iterations })}
          </span>
        </li>
        <li>
          <span className="kv-key">{t("jobDetail.trialsPerCandidate")}</span>
          <span className="kv-value">{job.trials_per_candidate}</span>
        </li>
        {job.max_total_trials ? (
          <li>
            <span className="kv-key">{t("jobDetail.maximumTrials")}</span>
            <span className="kv-value">{job.max_total_trials}</span>
          </li>
        ) : null}
        <li>
          <span className="kv-key">{t("jobDetail.acceptanceCriteria")}</span>
          <span className="kv-value">
            {ac.target_rmse !== null ? (
              <>RMSE ≤ {formatNumber(ac.target_rmse)} m · </>
            ) : null}
            {ac.target_max_error !== null ? (
              <>{t("jobDetail.maxErrorLower", { value: formatNumber(ac.target_max_error) })} · </>
            ) : null}
            {/* Phase 8 polish: "pass rate" means the per-trial pass_flag rate
                (fraction of dispatched trials whose pass_flag is true), NOT
                the execution-completion ratio. The outcome only reports
                "success" when this rate meets the threshold. */}
            {t("jobDetail.passRateHigher", { value: Math.round(ac.min_pass_rate * 100) })}
          </span>
        </li>
        {job.optimization_outcome ? (
          <li>
            <span className="kv-key">{t("jobDetail.outcome")}</span>
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
  const { t } = useI18n();
  const { completed_trials, total_trials, current_phase } = job.progress;
  const pct = total_trials > 0
    ? Math.max(0, Math.min(100, (completed_trials / total_trials) * 100))
    : 0;
  const active = isActiveJobStatus(job.status);
  return (
    <SectionCard
      title={t("jobDetail.progress")}
      description={
        current_phase ? (
          <>
            {t("jobDetail.currentPhase")}: <code>{current_phase}</code>
          </>
        ) : null
      }
    >
      <div
        className="progress-bar"
        role="progressbar"
        aria-label={t("jobDetail.progress")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-valuetext={t("jobDetail.progressValue", {
          completed: completed_trials,
          total: total_trials,
          percent: pct.toFixed(0),
        })}
      >
        <div
          className={`progress-bar-fill${active ? " progress-bar-fill-active" : ""}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="form-hint">
        {t("jobDetail.progressValue", {
          completed: completed_trials,
          total: total_trials,
          percent: pct.toFixed(0),
        })}
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
  const { t } = useI18n();
  if (job.status === "QUEUED") {
    return (
      <Alert tone="info" title={t("jobDetail.queuedTitle")}>
        {t("jobDetail.queuedBody")}
      </Alert>
    );
  }
  if (job.status === "RUNNING") {
    return (
      <Alert tone="info" title={t("jobDetail.runningTitle")}>
        {t("jobDetail.runningBody")}
      </Alert>
    );
  }
  if (job.status === "AGGREGATING" || job.status === "FINALIZING") {
    return (
      <Alert tone="info" title={t("jobDetail.finalizingTitle")}>
        {t("jobDetail.finalizingBody")}
      </Alert>
    );
  }
  if (job.status === "CANCELLED") {
    return (
      <Alert tone="warning" title={t("jobDetail.cancelledTitle")}>
        {t("jobDetail.cancelledBody", { time: formatDateTime(job.cancelled_at) })}
      </Alert>
    );
  }
  if (job.status === "FAILED") {
    const err = job.latest_error;
    const outcome = job.optimization_outcome;
    const hasBestSoFar = Boolean(report);
    const title = hasBestSoFar
      ? t("jobDetail.failedBestTitle")
      : t("jobDetail.failedTitle");
    const outcomeLabel =
      outcome === "max_iterations_reached"
        ? t("jobDetail.outcomeMaxIterations")
        : outcome === "no_usable_candidate"
          ? t("jobDetail.outcomeNoCandidate")
          : outcome === "llm_failed"
            ? t("jobDetail.outcomeLlmFailed")
            : outcome === "simulator_unavailable"
              ? t("jobDetail.outcomeSimulatorUnavailable")
              : null;
    return (
      <Alert tone={hasBestSoFar ? "warning" : "danger"} title={title}>
        {err ? (
          <div>
            <strong>{err.code}</strong>: {err.message}
          </div>
        ) : (
          <div>{t("jobDetail.noDetailedError")}</div>
        )}
        {outcomeLabel ? <div style={{ marginTop: 4 }}>{outcomeLabel}</div> : null}
        {hasBestSoFar ? (
          <div style={{ marginTop: 4 }}>
            {t("jobDetail.bestSoFarBelow")}
          </div>
        ) : null}
      </Alert>
    );
  }
  if (job.status === "COMPLETED") {
    if (job.optimization_outcome === "success") {
      return (
        <Alert tone="success" title={t("jobDetail.acceptanceSatisfied")}>
          {t("jobDetail.acceptanceSatisfiedBody")}
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
          title={t("jobDetail.budgetExhausted")}
        >
          {t("jobDetail.budgetExhaustedBody")}
        </Alert>
      );
    }
  }
  if (job.status === "COMPLETED" && !report) {
    return (
      <Alert tone="info" title={t("jobDetail.loadingReport")}>
        {t("jobDetail.loadingReportBody")}
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
  const { t } = useI18n();
  if (
    (job.status === "COMPLETED" || job.status === "FAILED") &&
    report
  ) {
    const { baseline_metrics: b, optimized_metrics: o } = report;
    return (
      <SectionCard title={t("jobDetail.headlineMetrics")}>
        <div className="metric-grid">
          <MetricCard
            label={t("jobDetail.rmseOptimized")}
            value={`${formatNumber(o.rmse)} m`}
            sub={t("jobDetail.baselineMetric", { value: `${formatNumber(b.rmse)} m` })}
            tone="positive"
          />
          <MetricCard
            label={t("jobDetail.worstErrorOptimized")}
            value={`${formatNumber(o.max_error_worst ?? o.max_error)} m`}
            sub={t("jobDetail.errorComparison", {
              baseline: formatNumber(b.max_error_worst ?? b.max_error),
              mean: formatNumber(o.max_error_mean ?? o.max_error),
            })}
            tone="positive"
          />
          <MetricCard
            label={t("jobDetail.overshootOptimized")}
            value={o.overshoot_count}
            sub={t("jobDetail.baselineMetric", { value: b.overshoot_count })}
            tone="positive"
          />
          <MetricCard
            label={t("trial.completionTime")}
            value={`${formatNumber(o.completion_time)} s`}
            sub={t("jobDetail.baselineMetric", { value: `${formatNumber(b.completion_time)} s` })}
          />
          <MetricCard
            label={t("trial.score")}
            value={formatNumber(o.score)}
            sub={t("jobDetail.baselineMetric", { value: formatNumber(b.score) })}
            tone="positive"
          />
        </div>
      </SectionCard>
    );
  }

  return (
    <SectionCard title={t("jobDetail.headlineMetrics")}>
      <Empty
        title={t("jobDetail.metricsNotReady")}
        description={
          job.status === "FAILED"
            ? t("jobDetail.metricsFailed")
            : job.status === "CANCELLED"
              ? t("jobDetail.metricsCancelled")
              : t("jobDetail.metricsPending")
        }
      />
    </SectionCard>
  );
}

function HoldoutValidationSummary({
  holdout,
}: {
  holdout: NonNullable<JobReport["optimized_metrics"]["holdout"]>;
}) {
  const { t } = useI18n();
  const tone = holdout.validation_status === "passed"
    ? "success"
    : holdout.validation_status === "incomplete"
      ? "warning"
      : "danger";
  return (
    <Alert tone={tone} title={t("jobDetail.holdoutTitle", { status: holdout.validation_status })}>
      {t("jobDetail.holdoutBody", {
        completed: holdout.completed_trial_count,
        total: holdout.trial_count,
        passed: holdout.passing_trial_count,
        passRate: (holdout.pass_rate * 100).toFixed(1),
        failureRate: (holdout.failure_rate * 100).toFixed(1),
      })}
    </Alert>
  );
}

function BestParametersSection({
  job,
  report,
}: {
  job: Job;
  report: JobReport;
}) {
  const { t } = useI18n();
  const baselineWon = report.best_candidate_id === job.baseline_candidate_id;
  return (
    <SectionCard
      title={t("jobDetail.bestParameters")}
      description={
        baselineWon
          ? t("jobDetail.baselineWinnerDescription")
          : t("jobDetail.optimizerWinnerDescription")
      }
    >
      <div className="best-parameters-head">
        <span
          className={`candidate-tag ${
            baselineWon ? "candidate-tag-baseline" : "candidate-tag-optimizer"
          }`}
        >
          {baselineWon ? t("jobDetail.baselineWinner") : t("jobDetail.optimizerWinner")}
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
  const { t } = useI18n();
  const events = job.recent_events ?? [];
  // `recent_events` is returned newest-first by the backend. The log panel
  // reads naturally oldest-first, so reverse before formatting.
  const eventLines = [...events].reverse().map(formatEventLine);
  const lines = eventLines.length > 0 ? eventLines : synthesizeDiagnosticLines(job);

  return (
    <SectionCard
      title={t("jobDetail.diagnostics")}
      description={
        eventLines.length > 0
          ? t("jobDetail.diagnosticsEvents", { count: events.length })
          : t("jobDetail.diagnosticsFallback")
      }
    >
      <pre className="log-panel">{lines.join("\n")}</pre>
    </SectionCard>
  );
}
