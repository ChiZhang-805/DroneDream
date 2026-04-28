import { FormEvent, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { apiClient, ApiClientError } from "../api/client";
import type { JobCreateRequest } from "../types/api";
import { SectionCard } from "../components/SectionCard";

export function BatchCreate() {
  const navigate = useNavigate();
  const [name, setName] = useState("batch-experiment");
  const [description, setDescription] = useState("");
  const [jobsJson, setJobsJson] = useState("[]");
  const [validationError, setValidationError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: async () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(jobsJson);
      } catch {
        throw new Error("Jobs JSON must be valid JSON array.");
      }
      if (!Array.isArray(parsed)) {
        throw new Error("Jobs JSON must be an array.");
      }
      if (parsed.length < 1 || parsed.length > 50) {
        throw new Error("Jobs array size must be between 1 and 50.");
      }
      return apiClient.createBatch({
        name,
        description: description || null,
        jobs: parsed as JobCreateRequest[],
      });
    },
    onSuccess: (batch) => navigate(`/batches/${batch.id}`),
  });

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setValidationError(null);
    try {
      await createMutation.mutateAsync();
    } catch (err) {
      if (err instanceof Error) {
        setValidationError(err.message);
      }
    }
  };

  return (
    <section className="stack-md">
      <header className="page-header">
        <div>
          <h1>Create Batch</h1>
          <p className="page-header-subtitle">Submit multiple jobs in one request.</p>
        </div>
      </header>
      <SectionCard title="Batch payload">
        <form className="stack-sm" onSubmit={onSubmit}>
          <div className="form-field">
            <label htmlFor="batch-name">Batch Name</label>
            <input id="batch-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="form-field">
            <label htmlFor="batch-description">Description</label>
            <textarea
              id="batch-description"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="form-field">
            <label htmlFor="batch-jobs-json">Jobs JSON Array</label>
            <textarea
              id="batch-jobs-json"
              rows={14}
              value={jobsJson}
              onChange={(e) => setJobsJson(e.target.value)}
            />
          </div>
          {validationError ? <p style={{ color: "#b42318" }}>{validationError}</p> : null}
          {createMutation.error instanceof ApiClientError ? (
            <p style={{ color: "#b42318" }}>{createMutation.error.message}</p>
          ) : null}
          <button className="btn btn-primary" type="submit" disabled={createMutation.isPending}>
            Create Batch
          </button>
        </form>
      </SectionCard>
    </section>
  );
}
