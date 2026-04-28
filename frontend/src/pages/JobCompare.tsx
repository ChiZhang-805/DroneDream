import { useMemo } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import { Loading, ErrorState } from "../components/States";

function useJobIds(): string[] {
  const location = useLocation();
  return useMemo(() => {
    const params = new URLSearchParams(location.search);
    const raw = params.get("job_ids") ?? "";
    return raw.split(",").map((v) => v.trim()).filter(Boolean);
  }, [location.search]);
}

export function JobCompare() {
  const jobIds = useJobIds();
  const query = useQuery({
    queryKey: ["jobs-compare", jobIds.join(",")],
    queryFn: () => apiClient.compareJobs(jobIds),
    enabled: jobIds.length >= 2,
  });

  if (query.isLoading) return <Loading label="Loading comparison..." />;
  if (query.isError) return <ErrorState description="Failed to load comparison" />;

  const items = query.data?.items ?? [];
  const bestRmse = Math.min(
    ...items.map((i) => Number((i.optimized_metrics?.rmse as number | undefined) ?? Number.POSITIVE_INFINITY)),
  );

  return (
    <section className="stack-md">
      <header className="page-header">
        <h1>Job Compare</h1>
        <div className="page-header-actions">
          <a className="btn" href={apiClient.compareJobsCsvUrl(jobIds)}>
            Download CSV
          </a>
          <Link className="btn btn-ghost" to="/history">Back</Link>
        </div>
      </header>
      <SectionCard title="Comparison table">
        <table className="data-table">
          <thead><tr><th>Job</th><th>Status</th><th>Backend</th><th>Strategy</th><th>Baseline RMSE</th><th>Best RMSE</th><th>Trials</th></tr></thead>
          <tbody>
            {items.map((item) => {
              const rmse = Number((item.optimized_metrics?.rmse as number | undefined) ?? NaN);
              return (
                <tr key={item.job_id}>
                  <td><code>{item.job_id}</code></td>
                  <td>{item.status}</td>
                  <td>{item.simulator_backend}</td>
                  <td>{item.optimizer_strategy}</td>
                  <td>{String(item.baseline_metrics?.rmse ?? "—")}</td>
                  <td style={{ fontWeight: rmse === bestRmse ? 700 : 400 }}>{Number.isFinite(rmse) ? rmse : "—"}</td>
                  <td>{item.completed_trial_count}/{item.trial_count}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </SectionCard>
    </section>
  );
}
