import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import { Loading, ErrorState } from "../components/States";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";

export function Batches() {
  const query = useQuery({
    queryKey: ["batches"],
    queryFn: () => apiClient.listBatches(),
  });

  return (
    <section className="stack-md">
      <header className="page-header">
        <div>
          <h1>Batches</h1>
          <p className="page-header-subtitle">Manage grouped experiment jobs.</p>
        </div>
        <div className="page-header-actions">
          <Link to="/batches/new" className="btn btn-primary">+ New Batch</Link>
        </div>
      </header>

      <SectionCard title="Batch History">
        {query.isLoading ? (
          <Loading label="Loading batches…" />
        ) : query.isError ? (
          <ErrorState description="Failed to load batches." />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Progress</th>
              </tr>
            </thead>
            <tbody>
              {(query.data?.items ?? []).map((batch) => (
                <tr key={batch.id}>
                  <td>
                    <Link to={`/batches/${batch.id}`}>{batch.name}</Link>
                  </td>
                  <td><StatusBadge status={batch.status} /></td>
                  <td>{batch.progress.terminal_jobs}/{batch.progress.total_jobs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>
    </section>
  );
}
