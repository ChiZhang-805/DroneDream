import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import type { Job, JobStatus, ObjectiveProfile, TrackType } from "../types/api";
import {
  JOB_STATUSES,
  OBJECTIVE_PROFILES,
  TRACK_TYPES,
} from "../types/api";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";
import { DataTable, type Column } from "../components/DataTable";
import { Loading, Empty, ErrorState } from "../components/States";
import { formatDateTime } from "../utils/format";

const COLUMNS: Column<Job>[] = [
  {
    key: "id",
    header: "Job ID",
    render: (j) => (
      <Link to={`/jobs/${j.id}`}>
        <code>{j.id}</code>
      </Link>
    ),
  },
  { key: "track_type", header: "Track Type", render: (j) => j.track_type },
  {
    key: "objective_profile",
    header: "Objective Profile",
    render: (j) => j.objective_profile,
  },
  {
    key: "status",
    header: "Status",
    render: (j) => <StatusBadge status={j.status} />,
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

export function History() {
  const [statusFilter, setStatusFilter] = useState<JobStatus | "ALL">("ALL");
  const [trackFilter, setTrackFilter] = useState<TrackType | "ALL">("ALL");
  const [objectiveFilter, setObjectiveFilter] = useState<
    ObjectiveProfile | "ALL"
  >("ALL");

  const query = useQuery({
    queryKey: ["jobs", "history"],
    queryFn: () => apiClient.listJobs({ page: 1, page_size: 100 }),
  });

  const allJobs = useMemo(() => query.data?.items ?? [], [query.data]);
  const filtered = useMemo(() => {
    return allJobs.filter(
      (j) =>
        (statusFilter === "ALL" || j.status === statusFilter) &&
        (trackFilter === "ALL" || j.track_type === trackFilter) &&
        (objectiveFilter === "ALL" || j.objective_profile === objectiveFilter),
    );
  }, [allJobs, statusFilter, trackFilter, objectiveFilter]);

  return (
    <section className="stack-md">
      <header className="page-header">
        <div>
          <h1>History / Reports</h1>
          <p className="page-header-subtitle">
            Every job you have created, filterable by status, track, and
            objective.
          </p>
        </div>
        <div className="page-header-actions">
          <Link to="/jobs/new" className="btn btn-primary">
            + New Job
          </Link>
        </div>
      </header>

      <SectionCard title="Filters">
        <div className="filter-bar">
          <div className="form-field">
            <label htmlFor="filter-status">Status</label>
            <select
              id="filter-status"
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter(e.target.value as JobStatus | "ALL")
              }
            >
              <option value="ALL">All</option>
              {JOB_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="filter-track">Track Type</label>
            <select
              id="filter-track"
              value={trackFilter}
              onChange={(e) =>
                setTrackFilter(e.target.value as TrackType | "ALL")
              }
            >
              <option value="ALL">All</option>
              {TRACK_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="filter-objective">Objective</label>
            <select
              id="filter-objective"
              value={objectiveFilter}
              onChange={(e) =>
                setObjectiveFilter(e.target.value as ObjectiveProfile | "ALL")
              }
            >
              <option value="ALL">All</option>
              {OBJECTIVE_PROFILES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => {
              setStatusFilter("ALL");
              setTrackFilter("ALL");
              setObjectiveFilter("ALL");
            }}
          >
            Clear filters
          </button>
        </div>
      </SectionCard>

      <SectionCard title="Jobs">
        {query.isLoading ? (
          <Loading label="Loading jobs…" />
        ) : query.isError ? (
          <ErrorState
            description={
              query.error instanceof ApiClientError
                ? query.error.message
                : "Failed to load jobs."
            }
            action={
              <button
                className="btn"
                type="button"
                onClick={() => query.refetch()}
              >
                Retry
              </button>
            }
          />
        ) : (
          <DataTable
            columns={COLUMNS}
            rows={filtered}
            rowKey={(j) => j.id}
            emptyState={
              <Empty
                title={
                  allJobs.length === 0
                    ? "No jobs yet"
                    : "No jobs match the filters"
                }
                description={
                  allJobs.length === 0
                    ? "Create your first optimization job from New Job."
                    : "Try clearing some filters to broaden the results."
                }
                action={
                  allJobs.length === 0 ? (
                    <Link to="/jobs/new" className="btn btn-primary">
                      + New Job
                    </Link>
                  ) : undefined
                }
              />
            }
          />
        )}
      </SectionCard>
    </section>
  );
}
