import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { Loading, ErrorState } from "../components/States";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";

export function BatchDetail() {
  const { batchId = "" } = useParams();
  const navigate = useNavigate();

  const batchQuery = useQuery({
    queryKey: ["batch", batchId],
    queryFn: () => apiClient.getBatch(batchId),
  });
  const jobsQuery = useQuery({
    queryKey: ["batch", batchId, "jobs"],
    queryFn: () => apiClient.listBatchJobs(batchId),
  });

  const cancelMutation = useMutation({
    mutationFn: () => apiClient.cancelBatch(batchId),
    onSuccess: async () => {
      await batchQuery.refetch();
      await jobsQuery.refetch();
    },
  });

  const completedIds = useMemo(
    () => (jobsQuery.data ?? []).filter((j) => j.status === "COMPLETED").map((j) => j.id),
    [jobsQuery.data],
  );

  if (batchQuery.isLoading || jobsQuery.isLoading) {
    return <Loading label="Loading batch…" />;
  }
  if (batchQuery.isError || jobsQuery.isError || !batchQuery.data) {
    return <ErrorState description="Failed to load batch detail." />;
  }

  const progress = batchQuery.data.progress;
  const progressPercent = progress.total_jobs
    ? Math.round((progress.terminal_jobs / progress.total_jobs) * 100)
    : 0;

  return (
    <section className="stack-md">
      <header className="page-header">
        <div>
          <h1>{batchQuery.data.name}</h1>
          <p className="page-header-subtitle">{batchQuery.data.description ?? "No description"}</p>
        </div>
        <div className="page-header-actions">
          <StatusBadge status={batchQuery.data.status} />
          <button className="btn" onClick={() => cancelMutation.mutate()}>
            Cancel Batch
          </button>
          <button
            className="btn"
            disabled={completedIds.length < 2}
            onClick={() => navigate(`/compare?job_ids=${encodeURIComponent(completedIds.join(","))}`)}
          >
            Compare completed ({completedIds.length})
          </button>
        </div>
      </header>

      <SectionCard title="Progress">
        <div style={{ border: "1px solid #d0d5dd", borderRadius: 8, height: 12, overflow: "hidden" }}>
          <div style={{ width: `${progressPercent}%`, background: "#1570ef", height: "100%" }} />
        </div>
        <p>
          {progress.terminal_jobs}/{progress.total_jobs} terminal · completed {progress.completed_jobs} ·
          failed {progress.failed_jobs} · cancelled {progress.cancelled_jobs}
        </p>
      </SectionCard>

      <SectionCard title="Child Jobs">
        <table className="data-table">
          <thead>
            <tr>
              <th>Job ID</th>
              <th>Status</th>
              <th>Track</th>
              <th>Objective</th>
            </tr>
          </thead>
          <tbody>
            {(jobsQuery.data ?? []).map((job) => (
              <tr key={job.id}>
                <td>
                  <Link to={`/jobs/${job.id}`}>
                    <code>{job.id}</code>
                  </Link>
                </td>
                <td>
                  <StatusBadge status={job.status} />
                </td>
                <td>{job.track_type}</td>
                <td>{job.objective_profile}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>
    </section>
  );
}
