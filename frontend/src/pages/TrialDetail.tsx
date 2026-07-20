import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import { MetricCard } from "../components/MetricCard";
import { StatusBadge } from "../components/StatusBadge";
import { Alert } from "../components/Alert";
import { Loading, ErrorState } from "../components/States";
import type { Artifact, Trial } from "../types/api";
import { formatDateTime, formatNumber } from "../utils/format";
import { ArtifactsPanel } from "../components/ArtifactsPanel";
import {
  TrajectoryReplay,
} from "../components/TrajectoryReplay";
import { GazeboLivePanel } from "../components/GazeboLivePanel";
import { selectReplayArtifactsForTrial } from "../components/trajectoryReplayUtils";
import { useI18n } from "../i18n/I18nProvider";

export function TrialDetail() {
  const { t } = useI18n();
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

  if (trialQuery.isLoading) return <Loading label={t("trial.loading")} />;
  if (trialQuery.isError || !trialQuery.data) {
    return (
      <ErrorState
        title={t("trial.notFound")}
        description={
          trialQuery.error instanceof ApiClientError
            ? trialQuery.error.message
            : t("trial.notFoundBody")
        }
        action={
          <Link to="/" className="btn">
            {t("trial.backDashboard")}
          </Link>
        }
      />
    );
  }

  const trial = trialQuery.data;
  const artifacts = artifactsQuery.data ?? [];
  const replayArtifacts = selectReplayArtifactsForTrial(artifacts, trial.id);

  return (
    <section className="stack-md">
      <TrialHeader trial={trial} />
      <TrialMetadata trial={trial} />
      <TrialMetricsSection trial={trial} />
      <TrajectoryReplay
        artifacts={replayArtifacts}
        meta={{
          scenario: trial.scenario_type,
          candidate_id: trial.candidate_id,
        }}
      />
      <GazeboLivePanel />
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
  const { t } = useI18n();
  return (
    <header className="page-header">
      <div>
        <h1>
          {t("trial.title")} <code>{trial.id}</code>
        </h1>
        <p className="page-header-subtitle">
          {t("trial.partOfJob")}{" "}
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
  const { t } = useI18n();
  return (
    <SectionCard title={t("trial.metadata")}>
      <ul className="kv-list">
        <li>
          <span className="kv-key">{t("trial.candidateId")}</span>
          <span className="kv-value">
            <code>{trial.candidate_id}</code>
          </span>
        </li>
        <li>
          <span className="kv-key">{t("trial.seed")}</span>
          <span className="kv-value">{trial.seed}</span>
        </li>
        <li>
          <span className="kv-key">{t("trial.scenarioType")}</span>
          <span className="kv-value">{trial.scenario_type}</span>
        </li>
        <li>
          <span className="kv-key">{t("trial.attemptCount")}</span>
          <span className="kv-value">{trial.attempt_count}</span>
        </li>
        <li>
          <span className="kv-key">{t("trial.worker")}</span>
          <span className="kv-value">{trial.worker_id ?? "—"}</span>
        </li>
        <li>
          <span className="kv-key">{t("trial.simulatorBackend")}</span>
          <span className="kv-value">{trial.simulator_backend ?? "—"}</span>
        </li>
        <li>
          <span className="kv-key">{t("trial.queuedAt")}</span>
          <span className="kv-value">{formatDateTime(trial.queued_at)}</span>
        </li>
        <li>
          <span className="kv-key">{t("trial.startedAt")}</span>
          <span className="kv-value">{formatDateTime(trial.started_at)}</span>
        </li>
        <li>
          <span className="kv-key">{t("trial.finishedAt")}</span>
          <span className="kv-value">{formatDateTime(trial.finished_at)}</span>
        </li>
      </ul>
    </SectionCard>
  );
}

function TrialMetricsSection({ trial }: { trial: Trial }) {
  const { t } = useI18n();
  if (!trial.metrics) {
    return (
      <SectionCard title={t("trial.metrics")}>
        <Alert tone="warning">
          {trial.status === "FAILED" ? t("trial.metricsFailed") : t("trial.metricsUnavailable")}
        </Alert>
      </SectionCard>
    );
  }
  const m = trial.metrics;
  return (
    <SectionCard title={t("trial.metrics")}>
      <div className="metric-grid">
        <MetricCard label={t("trial.score")} value={formatNumber(m.score)} />
        <MetricCard label={t("trial.rmse")} value={`${formatNumber(m.rmse)} m`} />
        <MetricCard label={t("trial.maxError")} value={`${formatNumber(m.max_error)} m`} />
        <MetricCard label={t("trial.overshoot")} value={m.overshoot_count} />
        <MetricCard
          label={t("trial.completionTime")}
          value={`${formatNumber(m.completion_time)} s`}
        />
        <MetricCard label={t("trial.finalError")} value={`${formatNumber(m.final_error)} m`} />
        <MetricCard
          label={t("trial.pass")}
          value={m.pass_flag ? t("common.yes") : t("common.no")}
          tone={m.pass_flag ? "positive" : "negative"}
        />
        <MetricCard
          label={t("trial.instability")}
          value={m.instability_flag ? t("common.yes") : t("common.no")}
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
  const { t } = useI18n();
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
  return (
    <ArtifactsPanel
      title={t("artifacts.title")}
      description={t("trial.artifactsDescription", { scenario: trial.scenario_type, seed: trial.seed })}
      isLoading={isLoading}
      emptyDescription={t("trial.artifactsEmpty")}
      sections={[
        {
          heading: t("trial.trialArtifacts", { count: trialArtifacts.length }),
          artifacts: trialArtifacts,
          emptyNote:
            trial.simulator_backend === "mock"
              ? t("trial.mockArtifactsEmpty")
              : t("trial.trialArtifactsEmpty"),
        },
        {
          heading: t("trial.jobArtifacts", { count: jobArtifacts.length }),
          artifacts: jobArtifacts,
          emptyNote: t("trial.jobArtifactsEmpty"),
        },
      ]}
    />
  );
}

function FailureDetails({ trial }: { trial: Trial }) {
  const { t } = useI18n();
  if (trial.status !== "FAILED") return null;
  return (
    <SectionCard title={t("trial.failureDetails")}>
      <Alert tone="danger" title={trial.failure_code ?? t("trial.failed")}>
        {trial.failure_reason ?? t("trial.noFailureReason")}
      </Alert>
      {trial.log_excerpt ? (
        <pre className="log-panel">{trial.log_excerpt}</pre>
      ) : null}
    </SectionCard>
  );
}
