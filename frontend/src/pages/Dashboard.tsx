import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import { JOB_STATUSES } from "../types/api";
import type { JobStatus, ObjectiveProfile, TrackType } from "../types/api";
import { MetricCard } from "../components/MetricCard";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";
import { DataTable, type Column } from "../components/DataTable";
import { Loading, ErrorState } from "../components/States";
import { RuntimeAccessNotice } from "../components/RuntimeAccessNotice";
import { useDesktopRuntimeAccess } from "../desktop/access";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";
import type { Job } from "../types/api";
import { formatDateTime } from "../utils/format";
import { openAppSettings } from "../appSettings";

type Translator = ReturnType<typeof useI18n>["t"];

const TRACK_LABELS: Record<TrackType, TranslationKey> = {
  hover: "wizard.track.hover",
  circle: "wizard.track.circle",
  u_turn: "wizard.track.uTurn",
  lemniscate: "wizard.track.lemniscate",
  custom: "wizard.track.custom",
};

const OBJECTIVE_LABELS: Record<ObjectiveProfile, TranslationKey> = {
  stable: "wizard.objective.stable",
  fast: "wizard.objective.fast",
  smooth: "wizard.objective.smooth",
  robust: "wizard.objective.robust",
  custom: "wizard.objective.custom",
};

function buildJobColumns(t: Translator): Column<Job>[] {
  return [
  {
    key: "id",
    header: t("dashboard.jobId"),
    render: (j) => (
      <Link to={`/jobs/${j.id}`} className="mono-link">
        <code>{j.id}</code>
      </Link>
    ),
  },
  {
    key: "track_type",
    header: t("dashboard.trackType"),
    render: (j) => t(TRACK_LABELS[j.track_type]),
  },
  {
    key: "status",
    header: t("dashboard.status"),
    render: (j) => <StatusBadge status={j.status} />,
  },
  {
    key: "objective_profile",
    header: t("dashboard.objectiveProfile"),
    render: (j) => t(OBJECTIVE_LABELS[j.objective_profile]),
  },
  {
    key: "created_at",
    header: t("dashboard.createdAt"),
    render: (j) => formatDateTime(j.created_at),
  },
  {
    key: "updated_at",
    header: t("dashboard.updatedAt"),
    render: (j) => formatDateTime(j.updated_at),
  },
  {
    key: "action",
    header: t("dashboard.action"),
    align: "right",
    render: (j) => <Link to={`/jobs/${j.id}`}>{t("dashboard.view")}</Link>,
  },
  ];
}

export function Dashboard() {
  const runtimeAccess = useDesktopRuntimeAccess();
  const { t } = useI18n();
  const jobsQuery = useQuery({
    queryKey: ["jobs", "dashboard"],
    queryFn: async () => {
      const [recentPage, ...statusPages] = await Promise.all([
        apiClient.listJobs({ page: 1, page_size: 5 }),
        ...JOB_STATUSES.map((status) =>
          apiClient.listJobs({ page: 1, page_size: 1, status })
        ),
      ]);
      const counts: Partial<Record<JobStatus, number>> = {};
      JOB_STATUSES.forEach((status, index) => {
        counts[status] = statusPages[index]?.total ?? 0;
      });
      return {
        recentJobs: recentPage.items,
        totalJobs: JOB_STATUSES.reduce(
          (total, status) => total + (counts[status] ?? 0),
          0,
        ),
        counts,
      };
    },
    enabled: runtimeAccess.canUseRuntime,
  });
  const runtimeNetworkUnavailable =
    jobsQuery.error instanceof ApiClientError &&
    (jobsQuery.error.code === "NETWORK_ERROR" || jobsQuery.error.httpStatus === 0);

  return (
    <section className="dashboard-page">
      <header className="page-header dashboard-header">
        <div>
          <h1>{t("dashboard.title")}</h1>
        </div>
        <div className="page-header-actions">
          {runtimeAccess.canUseRuntime ? (
            <Link to="/jobs/new" className="btn btn-primary">
              {t("dashboard.newJob")}
            </Link>
          ) : runtimeAccess.status === "checking" || runtimeAccess.status === "starting" ? (
            <button type="button" className="btn btn-primary" disabled>
              {runtimeAccess.status === "starting"
                ? t("runtimeGate.startingShort")
                : t("runtimeGate.checkingShort")}
            </button>
          ) : (
            <button type="button" className="btn btn-primary" onClick={openAppSettings}>
              {t("runtimeGate.openSetup")}
            </button>
          )}
        </div>
      </header>

      {!runtimeAccess.canUseRuntime ? (
        <RuntimeAccessNotice page="dashboard" />
      ) : jobsQuery.isLoading ? (
        <Loading label={t("dashboard.loading")} />
      ) : runtimeNetworkUnavailable ? (
        <div className="dashboard-runtime-fallback">
          <RuntimeAccessNotice page="dashboard" />
          <DashboardBody recentJobs={[]} totalJobs={0} counts={{}} />
        </div>
      ) : jobsQuery.isError ? (
        <ErrorState
          description={
            jobsQuery.error instanceof ApiClientError
              ? jobsQuery.error.message
              : t("dashboard.loadFailed")
          }
          action={
            <button
              className="btn"
              onClick={() => jobsQuery.refetch()}
              type="button"
            >
              {t("dashboard.retry")}
            </button>
          }
        />
      ) : (
        <DashboardBody
          recentJobs={jobsQuery.data?.recentJobs ?? []}
          totalJobs={jobsQuery.data?.totalJobs ?? 0}
          counts={jobsQuery.data?.counts ?? {}}
        />
      )}
    </section>
  );
}

function DashboardBody({
  recentJobs,
  totalJobs,
  counts,
}: {
  recentJobs: Job[];
  totalJobs: number;
  counts: Partial<Record<JobStatus, number>>;
}) {
  const { t } = useI18n();
  const columns = buildJobColumns(t);

  return (
    <div className="dashboard-body">
      <SectionCard title={t("dashboard.statusSummary")}>
        <div className="metric-grid">
          <MetricCard
            label={t("dashboard.totalJobs")}
            value={totalJobs}
          />
          <MetricCard
            label={t("dashboard.active")}
            value={
              (counts.RUNNING ?? 0) +
              (counts.QUEUED ?? 0) +
              (counts.AGGREGATING ?? 0) +
              (counts.FINALIZING ?? 0) +
              (counts.CREATED ?? 0)
            }
            tone="muted"
          />
          <MetricCard
            label={t("dashboard.completed")}
            value={counts.COMPLETED ?? 0}
            tone="positive"
          />
          <MetricCard
            label={t("dashboard.failed")}
            value={counts.FAILED ?? 0}
            tone={(counts.FAILED ?? 0) > 0 ? "negative" : "muted"}
          />
          <MetricCard
            label={t("dashboard.cancelled")}
            value={counts.CANCELLED ?? 0}
            tone="muted"
          />
        </div>
      </SectionCard>

      <SectionCard
        title={t("dashboard.recentJobs")}
        actions={(
          <Link to="/history" className="dashboard-view-all">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 12h13M14 7l5 5-5 5" />
            </svg>
            <span>{t("dashboard.viewAll")}</span>
          </Link>
        )}
      >
        {recentJobs.length > 0 ? (
          <DataTable
            columns={columns}
            rows={recentJobs}
            rowKey={(j) => j.id}
          />
        ) : (
          <div className="dashboard-empty-jobs" aria-hidden="true" />
        )}
      </SectionCard>
    </div>
  );
}
