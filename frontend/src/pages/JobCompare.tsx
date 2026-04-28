import { useMemo } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import { Loading, ErrorState } from "../components/States";
import type { JobCompareItem } from "../types/api";

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
  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const metricKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const item of items) {
      if (!item.optimized_metrics) continue;
      for (const [key, value] of Object.entries(item.optimized_metrics)) {
        if (typeof value === "number" && Number.isFinite(value)) keys.add(key);
      }
    }
    return [...keys];
  }, [items]);
  const bestByMetric = useMemo(() => {
    const best: Record<string, number> = {};
    for (const key of metricKeys) {
      best[key] = Math.min(
        ...items.map((item) => getNumericMetric(item, "optimized_metrics", key)),
      );
    }
    return best;
  }, [items, metricKeys]);

  if (query.isLoading) return <Loading label="Loading comparison..." />;
  if (query.isError) return <ErrorState description="Failed to load comparison" />;

  return (
    <section className="stack-md">
      <header className="page-header">
        <h1>Job Compare</h1>
        <div className="page-header-actions">
          <button
            className="btn"
            type="button"
            onClick={() => void apiClient.downloadCompareJobsCsv(jobIds)}
          >
            Download CSV
          </button>
          <Link className="btn btn-ghost" to="/history">Back</Link>
        </div>
      </header>
      <SectionCard title="Comparison table">
        <table className="data-table">
          <thead><tr><th>Job</th><th>Status</th><th>Backend</th><th>Strategy</th>{metricKeys.map((key) => <th key={key}>Best {key}</th>)}<th>Trials</th></tr></thead>
          <tbody>
            {items.map((item) => {
              return (
                <tr key={item.job_id}>
                  <td><code>{item.job_id}</code></td>
                  <td>{item.status}</td>
                  <td>{item.simulator_backend}</td>
                  <td>{item.optimizer_strategy}</td>
                  {metricKeys.map((metric) => {
                    const value = getNumericMetric(item, "optimized_metrics", metric);
                    const isBest = Number.isFinite(value) && value === bestByMetric[metric];
                    return (
                      <td key={metric} style={{ fontWeight: isBest ? 700 : 400 }}>
                        {Number.isFinite(value) ? value : "—"}
                      </td>
                    );
                  })}
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

function getNumericMetric(
  item: JobCompareItem,
  field: "baseline_metrics" | "optimized_metrics",
  metric: string,
): number {
  const value = item[field]?.[metric];
  return typeof value === "number" && Number.isFinite(value) ? value : Number.POSITIVE_INFINITY;
}
