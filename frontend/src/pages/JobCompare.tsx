import { useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { SectionCard } from "../components/SectionCard";
import { Loading, ErrorState } from "../components/States";
import type { JobCompareItem } from "../types/api";
import { useI18n } from "../i18n/I18nProvider";

const HIGHER_IS_BETTER_METRICS = new Set([
  "pass_rate",
  "completion_rate",
  "success_rate",
  "passing_trial_count",
]);

function lowerIsBetter(metric: string): boolean {
  return !HIGHER_IS_BETTER_METRICS.has(metric.toLowerCase());
}

function useJobIds(): string[] {
  const location = useLocation();
  return useMemo(() => {
    const params = new URLSearchParams(location.search);
    const raw = params.get("job_ids") ?? "";
    return raw.split(",").map((v) => v.trim()).filter(Boolean);
  }, [location.search]);
}

export function JobCompare() {
  const { t } = useI18n();
  const jobIds = useJobIds();
  const [downloadError, setDownloadError] = useState(false);
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
      const values = items
        .map((item) => getNumericMetric(item, "optimized_metrics", key))
        .filter((value): value is number => value !== null);
      if (values.length > 0) {
        best[key] = lowerIsBetter(key) ? Math.min(...values) : Math.max(...values);
      }
    }
    return best;
  }, [items, metricKeys]);

  if (jobIds.length < 2) {
    return <ErrorState title={t("jobCompare.notEnoughTitle")} description={t("jobCompare.notEnoughBody")} />;
  }
  if (query.isLoading) return <Loading label={t("jobCompare.loading")} />;
  if (query.isError) return <ErrorState description={t("jobCompare.loadFailed")} />;

  return (
    <section className="stack-md">
      <header className="page-header">
        <h1>{t("jobCompare.title")}</h1>
        <div className="page-header-actions">
          <button
            className="btn"
            type="button"
            onClick={() => {
              setDownloadError(false);
              void apiClient.downloadCompareJobsCsv(jobIds).catch(() => setDownloadError(true));
            }}
          >
            {t("jobCompare.downloadCsv")}
          </button>
          <Link className="btn btn-ghost" to="/history">{t("jobCompare.back")}</Link>
        </div>
      </header>
      {downloadError ? <p className="form-error" role="alert">{t("jobCompare.downloadFailed")}</p> : null}
      <SectionCard title={t("jobCompare.tableTitle")}>
        <table className="data-table">
          <thead><tr><th>{t("jobCompare.job")}</th><th>{t("jobCompare.status")}</th><th>{t("jobCompare.backend")}</th><th>{t("jobCompare.strategy")}</th>{metricKeys.map((key) => <th key={key}>{t("jobCompare.bestMetric", { metric: key })}</th>)}<th>{t("jobCompare.trials")}</th></tr></thead>
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
                    const isBest = value !== null && value === bestByMetric[metric];
                    return (
                      <td key={metric} style={{ fontWeight: isBest ? 700 : 400 }}>
                        {value ?? "—"}
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
): number | null {
  const value = item[field]?.[metric];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
