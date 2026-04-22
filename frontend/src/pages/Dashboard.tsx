import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import { JOB_STATUSES } from "../types/api";
import type { JobStatus } from "../types/api";
import { MetricCard } from "../components/MetricCard";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";
import { DataTable, type Column } from "../components/DataTable";
import { Loading, Empty, ErrorState } from "../components/States";
import type { Job } from "../types/api";
import { formatDateTime } from "../utils/format";

const JOB_COLUMNS: Column<Job>[] = [
  {
    key: "id",
    header: "Job ID",
    render: (j) => (
      <Link to={`/jobs/${j.id}`} className="mono-link">
        <code>{j.id}</code>
      </Link>
    ),
  },
  { key: "track_type", header: "Track Type", render: (j) => j.track_type },
  {
    key: "status",
    header: "Status",
    render: (j) => <StatusBadge status={j.status} />,
  },
  {
    key: "objective_profile",
    header: "Objective Profile",
    render: (j) => j.objective_profile,
  },
  {
    key: "created_at",
    header: "Created At",
    render: (j) => formatDateTime(j.created_at),
  },
  {
    key: "updated_at",
    header: "Updated At",
    render: (j) => formatDateTime(j.updated_at),
  },
  {
    key: "action",
    header: "Action",
    align: "right",
    render: (j) => <Link to={`/jobs/${j.id}`}>View</Link>,
  },
];

export function Dashboard() {
  const jobsQuery = useQuery({
    queryKey: ["jobs", "dashboard"],
    queryFn: () => apiClient.listJobs({ page: 1, page_size: 10 }),
  });

  return (
    <section className="stack-md">
      <header className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="page-header-subtitle">
            Kick off a new optimization run or review recent jobs.
          </p>
        </div>
        <div className="page-header-actions">
          <Link to="/jobs/new" className="btn btn-primary">
            + New Job
          </Link>
        </div>
      </header>

      {jobsQuery.isLoading ? (
        <Loading label="Loading jobs…" />
      ) : jobsQuery.isError ? (
        <ErrorState
          description={
            jobsQuery.error instanceof ApiClientError
              ? jobsQuery.error.message
              : "Failed to load jobs."
          }
          action={
            <button
              className="btn"
              onClick={() => jobsQuery.refetch()}
              type="button"
            >
              Retry
            </button>
          }
        />
      ) : (
        <DashboardBody jobs={jobsQuery.data?.items ?? []} />
      )}
    </section>
  );
}

function DashboardBody({ jobs }: { jobs: Job[] }) {
  const counts = countByStatus(jobs);

  return (
    <>
      <SectionCard title="Status summary">
        <div className="metric-grid">
          <MetricCard
            label="Total jobs"
            value={jobs.length}
            sub="last 10 jobs"
          />
          <MetricCard
            label="Active"
            value={
              (counts.RUNNING ?? 0) +
              (counts.QUEUED ?? 0) +
              (counts.AGGREGATING ?? 0) +
              (counts.CREATED ?? 0)
            }
            sub="CREATED + QUEUED + RUNNING + AGGREGATING"
            tone="muted"
          />
          <MetricCard
            label="Completed"
            value={counts.COMPLETED ?? 0}
            tone="positive"
          />
          <MetricCard
            label="Failed"
            value={counts.FAILED ?? 0}
            tone={(counts.FAILED ?? 0) > 0 ? "negative" : "muted"}
          />
          <MetricCard
            label="Cancelled"
            value={counts.CANCELLED ?? 0}
            tone="muted"
          />
        </div>
      </SectionCard>

      <SectionCard
        title="Recent jobs"
        actions={<Link to="/history">View all</Link>}
      >
        <DataTable
          columns={JOB_COLUMNS}
          rows={jobs}
          rowKey={(j) => j.id}
          emptyState={
            <Empty
              title="No jobs yet"
              description="Create your first optimization job to get started."
              action={
                <Link to="/jobs/new" className="btn btn-primary">
                  + New Job
                </Link>
              }
            />
          }
        />
      </SectionCard>
    </>
  );
}

function countByStatus(jobs: Job[]): Partial<Record<JobStatus, number>> {
  const counts: Partial<Record<JobStatus, number>> = {};
  for (const s of JOB_STATUSES) counts[s] = 0;
  for (const j of jobs) counts[j.status] = (counts[j.status] ?? 0) + 1;
  return counts;
}
