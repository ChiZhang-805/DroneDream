import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type {
  ContinueExplorationBudget,
  ContinueExplorationRequest,
  Job,
  JobEventInfo,
  JobReport,
  JobRerunRequest,
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
import { localeSafeError, useI18n } from "../i18n/I18nProvider";
import { issueManagedModelGrant } from "../features/settings/cloudModelAccess";

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
  const { locale, t } = useI18n();
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const safeId = jobId ?? "";
  const [pdfDownloadError, setPdfDownloadError] = useState(false);
  const [showContinuationDialog, setShowContinuationDialog] = useState(false);
  const [continuationConfirmed, setContinuationConfirmed] = useState(false);
  const [continuationApiKey, setContinuationApiKey] = useState("");
  const [continuationError, setContinuationError] = useState<string | null>(null);
  const [continuationBudget, setContinuationBudget] = useState({
    generations: "4",
    trials: "80",
    providerTurns: "16",
    minutes: "60",
  });
  const terminalReconciledJobRef = useRef<string | null>(null);
  const continuationDialogRef = useRef<HTMLElement | null>(null);
  const continuationReturnFocusRef = useRef<HTMLElement | null>(null);
  const rerunInFlightRef = useRef(false);
  const cancelInFlightRef = useRef(false);

  const rerunMutation = useMutation({
    mutationFn: ({
      id,
      request,
      managedAccess,
    }: {
      id: string;
      request?: JobRerunRequest;
      managedAccess?: boolean;
    }) => managedAccess
      ? issueManagedModelGrant("job", id).then((grant) =>
          apiClient.rerunJob(id, {
            llm: {
              access_mode: "platform",
              provider: "dronedream",
              api_key: null,
              platform_grant: grant.grant,
              model: null,
              base_url: null,
            },
          })
        )
      : apiClient.rerunJob(id, request),
    onSuccess: (newJob) => {
      queryClient.invalidateQueries({ queryKey: ["jobs", "dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["jobs", "history"] });
      navigate(`/jobs/${newJob.id}`);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: ({
      id,
      controlVersion,
    }: {
      id: string;
      controlVersion: number;
    }) => apiClient.cancelJob(id, controlVersion),
    onSuccess: (updated) => {
      queryClient.setQueryData(["job", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["jobs", "dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["jobs", "history"] });
    },
  });

  const continuationMutation = useMutation({
    mutationFn: async ({
      id,
      controlVersion,
      request,
      managedAccess,
    }: {
      id: string;
      controlVersion: number;
      request: ContinueExplorationRequest;
      managedAccess: boolean;
    }) => {
      if (!managedAccess) {
        return apiClient.continueExploration(id, controlVersion, request);
      }
      const grant = await issueManagedModelGrant("job", id);
      return apiClient.continueExploration(id, controlVersion, {
        ...request,
        llm: {
          access_mode: "platform",
          provider: "dronedream",
          api_key: null,
          platform_grant: grant.grant,
          model: null,
          base_url: null,
        },
      });
    },
    onSuccess: (child) => {
      setContinuationApiKey("");
      setShowContinuationDialog(false);
      queryClient.invalidateQueries({ queryKey: ["job", safeId] });
      queryClient.invalidateQueries({ queryKey: ["jobs", "dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["jobs", "history"] });
      navigate(`/jobs/${child.id}`);
    },
  });

  useEffect(() => {
    if (!showContinuationDialog) return;
    const dialog = continuationDialogRef.current;
    if (!dialog) return;
    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
      "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])",
    ));
    focusable[0]?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !continuationMutation.isPending) {
        event.preventDefault();
        setContinuationApiKey("");
        setShowContinuationDialog(false);
        window.setTimeout(() => continuationReturnFocusRef.current?.focus(), 0);
        return;
      }
      if (event.key !== "Tab" || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [continuationMutation.isPending, showContinuationDialog]);

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

  useEffect(() => {
    if (
      !safeId ||
      !jobStatus ||
      isActiveJobStatus(jobStatus) ||
      !trialsQuery.isFetched ||
      !candidatesQuery.isFetched ||
      terminalReconciledJobRef.current === safeId
    ) {
      return;
    }

    terminalReconciledJobRef.current = safeId;
    void queryClient.invalidateQueries({
      queryKey: ["job-trials", safeId],
      exact: true,
    });
    void queryClient.invalidateQueries({
      queryKey: ["job-candidates", safeId],
      exact: true,
    });
  }, [
    candidatesQuery.isFetched,
    jobStatus,
    queryClient,
    safeId,
    trialsQuery.isFetched,
  ]);

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
          localeSafeError(jobQuery.error, locale, {
            zh: t("jobDetail.notFound"),
            en: t("jobDetail.notFound"),
          })
        }
        action={<Link to="/history" className="btn">{t("jobDetail.backHistory")}</Link>}
      />
    );
  }

  const trials = trialsQuery.data ?? [];
  const report = reportQuery.data;
  const artifacts = artifactsQuery.data ?? [];
  const bestCandidateTrials = trials.filter((trial) => trial.candidate_is_best);
  const bestTrial = bestCandidateTrials.find(
    (trial) => trial.status === "COMPLETED" && trial.pass_flag === true,
  ) ?? bestCandidateTrials.find(
    (trial) => trial.status === "COMPLETED" && trial.score !== null,
  ) ?? bestCandidateTrials.find(
    (trial) => trial.status === "COMPLETED",
  ) ?? bestCandidateTrials[0];
  const artifactsError = artifactsQuery.isError
    ? (
        localeSafeError(artifactsQuery.error, locale, {
          zh: t("artifacts.loadFailedDescription"),
          en: t("artifacts.loadFailedDescription"),
        })
      )
    : null;
  const pdfArtifact = artifacts.find(
    (a) => a.artifact_type === "pdf_report" || a.mime_type === "application/pdf",
  );

  const isTerminal =
    job.status === "COMPLETED" ||
    job.status === "FAILED" ||
    job.status === "CANCELLED";

  const submitRerun = (args: {
    id: string;
    request?: JobRerunRequest;
    managedAccess?: boolean;
  }) => {
    if (rerunInFlightRef.current) return;
    rerunInFlightRef.current = true;
    rerunMutation.mutate(args, {
      onSettled: () => {
        rerunInFlightRef.current = false;
      },
    });
  };

  const submitCancel = () => {
    if (cancelInFlightRef.current) return;
    cancelInFlightRef.current = true;
    cancelMutation.mutate(
      {
        id: job.id,
        controlVersion: job.control_version,
      },
      {
        onSettled: () => {
          cancelInFlightRef.current = false;
        },
      },
    );
  };

  const handleRerun = () => {
    if (optimizerUsesModelAccess(job.optimizer_strategy)) {
      const accessMode = job.llm_access_mode
        ?? (job.llm_provider === "dronedream" ? "platform" : "byok");
      if (accessMode === "platform") {
        submitRerun({ id: job.id, managedAccess: true });
        return;
      }
      const provider = job.llm_provider?.trim() || "openai";
      const freshKey = window.prompt(
        t("jobDetail.apiKeyPrompt", { provider }),
      );
      if (!freshKey || freshKey.trim() === "") return;
      submitRerun({
        id: job.id,
        request: {
          llm: {
            access_mode: "byok",
            provider,
            api_key: freshKey.trim(),
            platform_grant: null,
            model: job.openai_model,
            base_url: job.llm_base_url,
          },
        },
      });
      return;
    }
    submitRerun({ id: job.id });
  };

  const openContinuationDialog = () => {
    const budget = job.exploration_budget;
    setContinuationBudget({
      generations: String(budget?.additional_generation_cap ?? 4),
      trials: String(budget?.additional_trial_cap ?? 80),
      providerTurns: String(
        optimizerUsesModelAccess(job.optimizer_strategy)
          ? (budget?.additional_provider_turn_cap ?? 16)
          : 0,
      ),
      minutes: String(
        Math.max(1, Math.round((budget?.additional_time_budget_seconds ?? 3600) / 60)),
      ),
    });
    setContinuationApiKey("");
    setContinuationConfirmed(false);
    setContinuationError(null);
    continuationMutation.reset();
    continuationReturnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    setShowContinuationDialog(true);
  };

  const submitContinuation = () => {
    const generationCap = Number(continuationBudget.generations);
    const trialCap = Number(continuationBudget.trials);
    const providerTurnCap = optimizerUsesModelAccess(job.optimizer_strategy)
      ? Number(continuationBudget.providerTurns)
      : 0;
    const timeMinutes = Number(continuationBudget.minutes);
    const valid = Number.isInteger(generationCap) && generationCap >= 1 && generationCap <= 32
      && Number.isInteger(trialCap) && trialCap >= 2 && trialCap <= 5000
      && Number.isInteger(providerTurnCap) && providerTurnCap >= 0
      && providerTurnCap <= Math.min(128, generationCap * 4)
      && Number.isInteger(timeMinutes) && timeMinutes >= 1 && timeMinutes <= 1440;
    if (!valid) {
      setContinuationError(t("jobDetail.continuation.invalidBudget"));
      return;
    }
    const budget: ContinueExplorationBudget = {
      additional_generation_cap: generationCap,
      additional_trial_cap: trialCap,
      additional_provider_turn_cap: providerTurnCap,
      additional_time_budget_seconds: timeMinutes * 60,
    };
    const request: ContinueExplorationRequest = { budget };
    const accessMode = job.llm_access_mode
      ?? (job.llm_provider === "dronedream" ? "platform" : "byok");
    const managedAccess = optimizerUsesModelAccess(job.optimizer_strategy)
      && accessMode === "platform";
    if (optimizerUsesModelAccess(job.optimizer_strategy) && !managedAccess) {
      const key = continuationApiKey.trim();
      if (!key) {
        setContinuationError(t("jobDetail.continuation.freshKeyRequired"));
        return;
      }
      request.llm = {
        access_mode: "byok",
        provider: job.llm_provider?.trim() || "openai",
        api_key: key,
        platform_grant: null,
        model: job.openai_model,
        base_url: job.llm_base_url,
      };
    }
    setContinuationError(null);
    continuationMutation.mutate({
      id: job.id,
      controlVersion: job.control_version,
      request,
      managedAccess,
    });
  };

  return (
    <section className="stack-md job-detail-content">
      <JobHeader
        job={job}
        onRerun={handleRerun}
        onCancel={submitCancel}
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
          {localeSafeError(rerunMutation.error, locale, {
            zh: t("jobDetail.rerunFailedBody"),
            en: t("jobDetail.rerunFailedBody"),
          })}
        </Alert>
      ) : null}
      {cancelMutation.isError ? (
        <Alert tone="danger" title={t("jobDetail.cancelFailed")}>
          {localeSafeError(cancelMutation.error, locale, {
            zh: t("jobDetail.cancelFailedBody"),
            en: t("jobDetail.cancelFailedBody"),
          })}
        </Alert>
      ) : null}
      <JobSummaryCard job={job} />
      <ExecutionBackendCard job={job} />
      <ProgressSection job={job} />

      <StatusSpecificTop job={job} report={report} />

      <QualificationAndExplorationCard
        job={job}
        onContinue={openContinuationDialog}
      />

      <MetricsCards job={job} report={report} />
      {report?.optimized_metrics.holdout ? (
        <HoldoutValidationSummary holdout={report.optimized_metrics.holdout} />
      ) : null}
      {bestTrial ? (
        <SectionCard title={t("jobDetail.bestReplay")}>
          <Link to={`/trials/${bestTrial.id}`}>{t("jobDetail.openBestReplay")}</Link>
        </SectionCard>
      ) : null}

      <GazeboLivePanel />

      {report ? (
        <>
          <SectionCard
            title={
              job.status === "FAILED"
                ? t("jobDetail.bestSoFarComparison")
                : t("comparison.ariaLabel")
            }
          >
            <ComparisonChart data={report.comparison} />
          </SectionCard>

          <BestParametersSection job={job} report={report} />

          <SectionCard title={t("jobDetail.summary")}>
            <p style={{ margin: 0 }}>
              {reportHasValidatedRecommendation(job, report)
                ? report.summary_text
                : t("jobDetail.noValidatedSummary")}
            </p>
          </SectionCard>
        </>
      ) : null}

      {reportEnabled && reportQuery.isError && job.status === "COMPLETED" ? (
        <Alert tone="danger" title={t("jobDetail.reportUnavailable")}>
          {localeSafeError(reportQuery.error, locale, {
            zh: t("jobDetail.reportUnavailableBody"),
            en: t("jobDetail.reportUnavailableBody"),
          })}
        </Alert>
      ) : null}

      <SectionCard title={t("jobDetail.insights")}>
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

      <SectionCard title={t("jobDetail.trials")}>
        {trialsQuery.isLoading ? (
          <Loading label={t("jobDetail.loadingTrials")} />
        ) : trialsQuery.isError ? (
          <ErrorState
            description={
              localeSafeError(trialsQuery.error, locale, {
                zh: t("jobDetail.trialsLoadFailed"),
                en: t("jobDetail.trialsLoadFailed"),
              })
            }
          />
        ) : (
          <DataTable
            columns={buildTrialColumns(job.optimizer_strategy, t)}
            rows={trials}
            rowKey={(t) => t.id}
            emptyState={
              <Empty title={t("jobDetail.noTrials")} />
            }
          />
        )}
      </SectionCard>

      {artifactsEnabled ? (
        <ArtifactsPanel
          title={t("artifacts.title")}
          isLoading={artifactsQuery.isLoading}
          error={artifactsError}
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
      {showContinuationDialog ? (
        <div
          className="confirm-dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !continuationMutation.isPending) {
              setContinuationApiKey("");
              setShowContinuationDialog(false);
              window.setTimeout(() => continuationReturnFocusRef.current?.focus(), 0);
            }
          }}
        >
          <section
            ref={continuationDialogRef}
            className="confirm-dialog-card continuation-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="continuation-dialog-title"
          >
            <h2 id="continuation-dialog-title">{t("jobDetail.continuation.dialogTitle")}</h2>
            <p>{t("jobDetail.continuation.dialogBody")}</p>
            <div className="form-grid continuation-dialog-budget">
              {([
                ["generations", "jobDetail.continuation.generations", 1, 32],
                ["trials", "jobDetail.continuation.trials", 2, 5000],
                ["providerTurns", "jobDetail.continuation.providerTurns", 0, 128],
                ["minutes", "jobDetail.continuation.minutes", 1, 1440],
              ] as const).map(([key, label, minimum, maximum]) => (
                <label key={key} className="form-field">
                  <span>{t(label)}</span>
                  <input
                    type="number"
                    min={minimum}
                    max={maximum}
                    step="1"
                    disabled={Boolean(job.exploration_budget) || (key === "providerTurns" && !optimizerUsesModelAccess(job.optimizer_strategy))}
                    value={continuationBudget[key]}
                    onChange={(event) => setContinuationBudget((current) => ({
                      ...current,
                      [key]: event.target.value,
                    }))}
                  />
                </label>
              ))}
            </div>
            {optimizerUsesModelAccess(job.optimizer_strategy)
              && (job.llm_access_mode ?? (job.llm_provider === "dronedream" ? "platform" : "byok")) === "byok" ? (
                <label className="form-field">
                  <span>{t("jobDetail.continuation.freshKey")}</span>
                  <input
                    type="password"
                    autoComplete="off"
                    value={continuationApiKey}
                    onChange={(event) => setContinuationApiKey(event.target.value)}
                  />
                </label>
              ) : null}
            <p className="continuation-dialog-warning">
              {t("jobDetail.continuation.costWarning")}
            </p>
            <label className="continuation-dialog-consent">
              <input
                type="checkbox"
                checked={continuationConfirmed}
                onChange={(event) => setContinuationConfirmed(event.target.checked)}
              />
              <span>{t("jobDetail.continuation.confirmation")}</span>
            </label>
            {continuationError ? <p className="form-error" role="alert">{continuationError}</p> : null}
            {continuationMutation.isError ? (
              <p className="form-error" role="alert">
                {localeSafeError(continuationMutation.error, locale, {
                  zh: t("jobDetail.continuation.failed"),
                  en: t("jobDetail.continuation.failed"),
                })}
              </p>
            ) : null}
            <div className="confirm-dialog-actions">
              <button
                type="button"
                className="btn"
                disabled={continuationMutation.isPending}
                onClick={() => {
                  setContinuationApiKey("");
                  setShowContinuationDialog(false);
                  window.setTimeout(() => continuationReturnFocusRef.current?.focus(), 0);
                }}
              >
                {t("jobDetail.continuation.close")}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!continuationConfirmed || continuationMutation.isPending}
                onClick={submitContinuation}
              >
                {continuationMutation.isPending
                  ? t("jobDetail.continuation.starting")
                  : t("jobDetail.continuation.confirmStart")}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function QualificationAndExplorationCard({
  job,
  onContinue,
}: {
  job: Job;
  onContinue: () => void;
}) {
  const { t } = useI18n();
  if (job.job_kind === "continue_exploration") {
    return (
      <SectionCard
        title={t("jobDetail.continuation.resultTitle")}
        description={t("jobDetail.continuation.childIsolation")}
      >
        <div className="qualification-card-actions">
          {job.continuation_parent_job_id ? (
            <Link className="btn" to={`/jobs/${job.continuation_parent_job_id}`}>
              {t("jobDetail.continuation.openFirstQualified")}
            </Link>
          ) : null}
        </div>
      </SectionCard>
    );
  }
  if (!job.first_qualified_candidate_id) {
    if (
      job.status === "COMPLETED"
      && job.optimization_outcome === "success"
      && job.completion_policy === undefined
    ) {
      return (
        <Alert tone="warning" title={t("jobDetail.continuation.legacyTitle")}>
          {t("jobDetail.continuation.legacyBody")}
        </Alert>
      );
    }
    return null;
  }
  return (
    <SectionCard
      title={t("jobDetail.firstQualified.title")}
      description={t("jobDetail.firstQualified.body")}
    >
      <ul className="kv-list qualification-receipt-list">
        <li>
          <span className="kv-key">{t("jobDetail.firstQualified.candidate")}</span>
          <span className="kv-value"><code>{job.first_qualified_candidate_id}</code></span>
        </li>
        <li>
          <span className="kv-key">{t("jobDetail.firstQualified.frozenAt")}</span>
          <span className="kv-value">{formatDateTime(job.first_qualified_at ?? null)}</span>
        </li>
        <li>
          <span className="kv-key">{t("jobDetail.firstQualified.providerTurns")}</span>
          <span className="kv-value">
            {t("jobDetail.firstQualified.providerTurnsValue", {
              attempted: job.provider_turns_attempted ?? 0,
              succeeded: job.provider_turns_succeeded ?? 0,
            })}
          </span>
        </li>
      </ul>
      <div className="qualification-card-actions">
        {job.continue_exploration_requested ? (
          <span className="completion-policy-badge">
            {t("jobDetail.continuation.alreadyStarted")}
          </span>
        ) : (
          <button type="button" className="btn btn-primary" onClick={onContinue}>
            {t("jobDetail.continuation.openDialog")}
          </button>
        )}
        <span className="form-hint">{t("jobDetail.firstQualified.immutable")}</span>
      </div>
    </SectionCard>
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
    <SectionCard title={t("jobDetail.execution")}>
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
          <span className="kv-key">{t("jobDetail.completionPolicy")}</span>
          <span className="kv-value">
            {job.completion_policy === "exploration_budget_stop"
              ? t("jobDetail.completionPolicy.explorationBudget")
              : job.completion_policy === "first_qualified_stop"
                ? t("jobDetail.completionPolicy.firstQualified")
                : t("jobDetail.completionPolicy.basic")}
          </span>
        </li>
        {job.provider_turn_cap !== undefined ? (
          <li>
            <span className="kv-key">{t("jobDetail.providerTurnBudget")}</span>
            <span className="kv-value">
              {t("jobDetail.providerTurnBudgetValue", {
                attempted: job.provider_turns_attempted ?? 0,
                succeeded: job.provider_turns_succeeded ?? 0,
                cap: job.provider_turn_cap,
              })}
            </span>
          </li>
        ) : null}
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
  if (
    job.status === "QUEUED"
    || job.status === "RUNNING"
    || job.status === "AGGREGATING"
    || job.status === "FINALIZING"
  ) return null;
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
    if (
      job.optimization_outcome === "exploration_improved"
      || job.optimization_outcome === "exploration_no_improvement"
      || job.optimization_outcome === "exploration_budget_exhausted"
    ) {
      const messageKey = job.optimization_outcome === "exploration_improved"
        ? "jobDetail.continuation.improved"
        : job.optimization_outcome === "exploration_no_improvement"
          ? "jobDetail.continuation.noImprovement"
          : "jobDetail.continuation.budgetExhausted";
      return (
        <Alert
          tone={job.optimization_outcome === "exploration_improved" ? "success" : "warning"}
          title={t("jobDetail.continuation.resultTitle")}
        >
          {t(messageKey)}
        </Alert>
      );
    }
    if (job.optimization_outcome === "success") {
      if (job.first_qualified_candidate_id) return null;
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
    return <Loading label={t("jobDetail.loadingReport")} />;
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

  return null;
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
  const recommendationValidated = reportHasValidatedRecommendation(job, report);
  const diagnosticFallback = !recommendationValidated;
  const isContinuation = job.job_kind === "continue_exploration";
  const isFirstQualified = Boolean(job.first_qualified_candidate_id);
  return (
    <SectionCard
      title={diagnosticFallback
        ? t("jobDetail.diagnosticParameters")
        : isContinuation
          ? t("jobDetail.continuation.resultTitle")
          : isFirstQualified
            ? t("jobDetail.firstQualified.parametersTitle")
            : t("jobDetail.bestParameters")}
      description={
        diagnosticFallback
          ? t("jobDetail.diagnosticParametersDescription")
          : isContinuation
            ? t("jobDetail.continuation.parametersDescription")
            : null
      }
    >
      <div className="best-parameters-head">
        <span
          className={`candidate-tag ${
            diagnosticFallback || baselineWon
              ? "candidate-tag-baseline"
              : "candidate-tag-optimizer"
          }`}
        >
          {diagnosticFallback
            ? t("jobDetail.noValidatedWinner")
            : isContinuation
              ? t("jobDetail.continuation.validatedCandidate")
              : isFirstQualified
                ? t("jobDetail.firstQualified.candidateTag")
                : baselineWon
                  ? t("jobDetail.baselineWinner")
                  : t("jobDetail.optimizerWinner")}
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

function reportHasValidatedRecommendation(job: Job, report: JobReport): boolean {
  const selectedCandidateMatches = Boolean(
    job.best_candidate_id && report.best_candidate_id === job.best_candidate_id,
  );
  if (!selectedCandidateMatches) return false;
  return job.simulator_backend_requested !== "real_cli"
    || Boolean(report.winner_freeze_receipt_id);
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
      title={eventLines.length > 0
        ? `${t("jobDetail.diagnostics")} (${events.length})`
        : t("jobDetail.diagnostics")}
      description={
        eventLines.length > 0 ? null : t("jobDetail.diagnosticsFallback")
      }
    >
      <pre className="log-panel">{lines.join("\n")}</pre>
    </SectionCard>
  );
}
