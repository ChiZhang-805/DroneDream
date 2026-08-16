import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, ApiClientError } from "../api/client";
import type {
  Job,
  JobStatus,
  ObjectiveProfile,
  OptimizerStrategy,
  SimulatorBackend,
  TrackType,
} from "../types/api";
import {
  JOB_STATUSES,
  OBJECTIVE_PROFILES,
  OPTIMIZER_STRATEGIES,
  SIMULATOR_BACKENDS,
  TRACK_TYPES,
} from "../types/api";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";
import { statusTranslationKey } from "../components/statusLabels";
import { type Column } from "../components/DataTable";
import { Loading, ErrorState } from "../components/States";
import { RuntimeAccessNotice } from "../components/RuntimeAccessNotice";
import { useDesktopRuntimeAccess } from "../desktop/access";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";
import { formatDateTime } from "../utils/format";
import { openAppSettings } from "../appSettings";
import { fetchAllHistoryJobs } from "../features/history/fetchAllHistoryJobs";

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

const OPTIMIZER_LABELS: Record<OptimizerStrategy, TranslationKey> = {
  none: "optimizer.none.label",
  heuristic: "optimizer.heuristic.label",
  gpt: "optimizer.gpt.label",
  llm_harness: "optimizer.llmHarness.label",
  cma_es: "optimizer.cmaEs.label",
  constrained_mobo: "optimizer.constrainedMobo.label",
  multi_fidelity_mobo: "optimizer.multiFidelityMobo.label",
  turbo: "optimizer.turbo.label",
  saasbo: "optimizer.saasbo.label",
  surrogate_cma_es: "optimizer.surrogateCmaEs.label",
  bipop_cma_es: "optimizer.bipopCmaEs.label",
  optimizer_portfolio: "optimizer.portfolio.label",
};

const DELETABLE_JOB_STATUSES: ReadonlySet<JobStatus> = new Set([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
]);

function buildColumns(t: Translator): Column<Job>[] {
  return [
    {
      key: "track_type",
      header: t("history.trackType"),
      render: (j) => t(TRACK_LABELS[j.track_type]),
    },
    {
      key: "objective_profile",
      header: t("history.objectiveProfile"),
      render: (j) => t(OBJECTIVE_LABELS[j.objective_profile]),
    },
    {
      key: "status",
      header: t("history.status"),
      render: (j) => <StatusBadge status={j.status} />,
    },
    {
      key: "created_at",
      header: t("history.createdAt"),
      render: (j) => formatDateTime(j.created_at),
    },
    {
      key: "action",
      header: t("history.action"),
      align: "right",
      render: (j) => <Link to={`/jobs/${j.id}`}>{t("history.view")}</Link>,
    },
  ];
}

export function History() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const runtimeAccess = useDesktopRuntimeAccess();
  const { t } = useI18n();
  const [statusFilter, setStatusFilter] = useState<JobStatus | "ALL">("ALL");
  const [trackFilter, setTrackFilter] = useState<TrackType | "ALL">("ALL");
  const [objectiveFilter, setObjectiveFilter] = useState<
    ObjectiveProfile | "ALL"
  >("ALL");
  const [queryFilter, setQueryFilter] = useState("");
  const [backendFilter, setBackendFilter] = useState<SimulatorBackend | "ALL">("ALL");
  const [optimizerFilter, setOptimizerFilter] = useState<OptimizerStrategy | "ALL">("ALL");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [editingNames, setEditingNames] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Job | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const savingNameIdsRef = useRef<Set<string>>(new Set());
  const deletingRef = useRef(false);
  const deleteCancelRef = useRef<HTMLButtonElement>(null);
  const deleteDialogRef = useRef<HTMLDivElement>(null);
  const columns = useMemo(() => buildColumns(t), [t]);

  useEffect(() => {
    if (!deleteTarget) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    deleteCancelRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [deleteTarget]);

  useEffect(() => {
    if (!deleteTarget) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isDeleting) {
        setDeleteTarget(null);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(deleteDialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? []);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteTarget, isDeleting]);

  async function saveName(job: Job, rawName: string) {
    if (savingNameIdsRef.current.has(job.id)) return;
    savingNameIdsRef.current.add(job.id);
    const nextName = rawName.trim();
    setSaveError(null);
    try {
      await apiClient.updateJob(
        job.id,
        { display_name: nextName === "" ? null : nextName },
        job.control_version,
      );
      setEditingId(null);
      await query.refetch();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : t("history.saveFailed"));
    } finally {
      savingNameIdsRef.current.delete(job.id);
    }
  }

  const query = useQuery({
    queryKey: ["jobs", "history"],
    queryFn: fetchAllHistoryJobs,
    enabled: runtimeAccess.canUseRuntime,
  });

  const allJobs = useMemo(() => query.data ?? [], [query.data]);
  const filtered = useMemo(() => {
    const normalizedQuery = queryFilter.trim().toLocaleLowerCase();
    return allJobs.filter(
      (j) =>
        (normalizedQuery === "" || [j.display_name, j.id]
          .filter(Boolean)
          .some((value) => value!.toLocaleLowerCase().includes(normalizedQuery))) &&
        (statusFilter === "ALL" || j.status === statusFilter) &&
        (trackFilter === "ALL" || j.track_type === trackFilter) &&
        (objectiveFilter === "ALL" || j.objective_profile === objectiveFilter) &&
        (backendFilter === "ALL" || j.simulator_backend_requested === backendFilter) &&
        (optimizerFilter === "ALL" || j.optimizer_strategy === optimizerFilter),
    );
  }, [allJobs, backendFilter, objectiveFilter, optimizerFilter, queryFilter, statusFilter, trackFilter]);
  const canCompare = selectedIds.length >= 2 && selectedIds.length <= 10;
  async function confirmDelete() {
    if (!deleteTarget || deletingRef.current) return;
    deletingRef.current = true;
    setDeleteError(null);
    setIsDeleting(true);
    try {
      await apiClient.deleteJob(
        deleteTarget.id,
        deleteTarget.control_version,
      );
      setSelectedIds((prev) => prev.filter((id) => id !== deleteTarget.id));
      if (editingId === deleteTarget.id) setEditingId(null);
      setEditingNames((prev) => {
        const next = { ...prev };
        delete next[deleteTarget.id];
        return next;
      });
      setDeleteTarget(null);
      await query.refetch();
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : t("history.deleteFailed"));
    } finally {
      deletingRef.current = false;
      setIsDeleting(false);
    }
  }

  return (
    <section className="history-page">
      <header className="page-header history-header">
        <div>
          <h1>{t("history.title")}</h1>
        </div>
        <div className="page-header-actions">
          {runtimeAccess.canUseRuntime ? (
            <Link to="/jobs/new" className="btn btn-primary">
              {t("history.newJob")}
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

      {!runtimeAccess.canUseRuntime ? <RuntimeAccessNotice page="history" /> : null}
      <div className="history-body">
      <SectionCard title={t("history.filters")}>
        <div className="history-filter-grid">
          <div className="form-field history-filter-search">
            <label htmlFor="filter-query">{t("history.search")}</label>
            <input
              id="filter-query"
              type="search"
              value={queryFilter}
              placeholder={t("history.searchPlaceholder")}
              onChange={(event) => setQueryFilter(event.target.value)}
            />
          </div>
          <div className="form-field">
            <label htmlFor="filter-status">{t("history.status")}</label>
            <select
              id="filter-status"
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter(e.target.value as JobStatus | "ALL")
              }
            >
              <option value="ALL">{t("history.all")}</option>
              {JOB_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(statusTranslationKey(s))}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="filter-track">{t("history.trackType")}</label>
            <select
              id="filter-track"
              value={trackFilter}
              onChange={(e) =>
                setTrackFilter(e.target.value as TrackType | "ALL")
              }
            >
              <option value="ALL">{t("history.all")}</option>
              {TRACK_TYPES.map((track) => (
                <option key={track} value={track}>
                  {t(TRACK_LABELS[track])}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="filter-objective">{t("history.objective")}</label>
            <select
              id="filter-objective"
              value={objectiveFilter}
              onChange={(e) =>
                setObjectiveFilter(e.target.value as ObjectiveProfile | "ALL")
              }
            >
              <option value="ALL">{t("history.all")}</option>
              {OBJECTIVE_PROFILES.map((p) => (
                <option key={p} value={p}>
                  {t(OBJECTIVE_LABELS[p])}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label htmlFor="filter-backend">{t("history.simulatorBackend")}</label>
            <select
              id="filter-backend"
              value={backendFilter}
              onChange={(event) =>
                setBackendFilter(event.target.value as SimulatorBackend | "ALL")
              }
            >
              <option value="ALL">{t("history.all")}</option>
              {SIMULATOR_BACKENDS.map((backend) => (
                <option key={backend} value={backend}>
                  {t(backend === "real_cli" ? "wizard.simulator.realCli" : "wizard.simulator.mock")}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field history-filter-optimizer">
            <label htmlFor="filter-optimizer">{t("history.optimizerStrategy")}</label>
            <select
              id="filter-optimizer"
              value={optimizerFilter}
              onChange={(event) =>
                setOptimizerFilter(event.target.value as OptimizerStrategy | "ALL")
              }
            >
              <option value="ALL">{t("history.all")}</option>
              {OPTIMIZER_STRATEGIES.map((strategy) => (
                <option key={strategy} value={strategy}>
                  {t(OPTIMIZER_LABELS[strategy])}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn btn-ghost history-clear-filters"
            onClick={() => {
              setQueryFilter("");
              setStatusFilter("ALL");
              setTrackFilter("ALL");
              setObjectiveFilter("ALL");
              setBackendFilter("ALL");
              setOptimizerFilter("ALL");
            }}
          >
            {t("history.clearFilters")}
          </button>
        </div>
      </SectionCard>

      <SectionCard
        title={t("history.jobs")}
        actions={(
          <button
            type="button"
            className="btn history-compare-button"
            disabled={!canCompare}
            onClick={() =>
              navigate(`/compare?job_ids=${encodeURIComponent(selectedIds.join(","))}`)
            }
          >
            {t("history.compareSelected", { count: selectedIds.length })}
          </button>
        )}
      >
        {saveError ? <ErrorState description={saveError} /> : null}
        {query.isLoading ? (
          <Loading label={t("history.loading")} />
        ) : query.isError ? (
          <ErrorState
            description={
              query.error instanceof ApiClientError
                ? query.error.message
                : t("history.loadFailed")
            }
            action={
              <button
                className="btn"
                type="button"
                onClick={() => query.refetch()}
              >
                {t("history.retry")}
              </button>
            }
          />
        ) : (
          <div className="data-table-wrapper history-results">
            <table className="data-table history-table-centered">
              <colgroup>
                <col className="history-col-select" />
                <col className="history-col-name" />
                <col className="history-col-track" />
                <col className="history-col-objective" />
                <col className="history-col-status" />
                <col className="history-col-created" />
                <col className="history-col-action" />
                <col className="history-col-delete" />
              </colgroup>
              <thead>
                <tr>
                  <th>{t("history.select")}</th>
                  <th>{t("history.jobName")}</th>
                  {columns.map((c) => <th key={String(c.key)}>{c.header}</th>)}
                  <th>{t("history.delete")}</th>
                </tr>
              </thead>
              <tbody>
              {filtered.map((j) => (
                <tr key={j.id}>
                  <td>
                    <input
                      aria-label={t("history.selectJob", { id: j.id })}
                      type="checkbox"
                      checked={selectedIds.includes(j.id)}
                      disabled={selectedIds.length >= 10 && !selectedIds.includes(j.id)}
                      onChange={(e) =>
                        setSelectedIds((prev) =>
                          e.target.checked
                            ? [...prev, j.id].slice(0, 10)
                            : prev.filter((id) => id !== j.id),
                        )
                      }
                    />
                  </td>
                  <td>
                    <div className="history-job-name-cell">
                    {editingId === j.id ? (
                      <>
                        <input aria-label={t("history.jobNameFor", { id: j.id })} value={editingNames[j.id] ?? (j.display_name ?? "")} onChange={(e) => setEditingNames((prev) => ({ ...prev, [j.id]: e.target.value }))} />
                        <button type="button" className="btn btn-ghost" onClick={() => void saveName(j, editingNames[j.id] ?? (j.display_name ?? ""))}>{t("history.save")}</button>
                        <button type="button" className="btn btn-ghost" onClick={() => { setEditingId(null); setEditingNames((prev) => ({ ...prev, [j.id]: j.display_name ?? "" })); }}>{t("history.cancel")}</button>
                      </>
                    ) : (
                      <>
                        <span>{j.display_name?.trim() || t("history.unnamed")}</span>
                        <button type="button" className="btn btn-ghost" onClick={() => setEditingId(j.id)}>{t("history.edit")}</button>
                      </>
                    )}
                    </div>
                  </td>
                  {columns.map((c) => (
                    <td key={String(c.key)}>{c.render(j)}</td>
                  ))}
                  <td>
                    <button
                      type="button"
                      className="btn btn-danger"
                      disabled={!DELETABLE_JOB_STATUSES.has(j.status)}
                      title={!DELETABLE_JOB_STATUSES.has(j.status) ? t("history.activeCannotDelete") : t("history.deleteJob")}
                      onClick={() => {
                        setDeleteError(null);
                        setDeleteTarget(j);
                      }}
                    >
                      {t("history.delete")}
                    </button>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 ? (
                <tr className="history-empty-row">
                  <td colSpan={columns.length + 3}>{t("history.empty")}</td>
                </tr>
              ) : null}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
      </div>
      {runtimeAccess.canUseRuntime && deleteTarget ? (
        <div className="confirm-dialog-backdrop" role="presentation">
          <div ref={deleteDialogRef} className="confirm-dialog-card" role="dialog" aria-modal="true" aria-labelledby="delete-job-dialog-title">
            <h3 id="delete-job-dialog-title">{t("history.confirmDeleteTitle")}</h3>
            <p>{t("history.confirmDeleteBody", { name: deleteTarget.display_name?.trim() || deleteTarget.id })}</p>
            {deleteError ? <p className="form-error">{deleteError}</p> : null}
            <div className="confirm-dialog-actions">
              <button ref={deleteCancelRef} type="button" className="btn btn-ghost" onClick={() => setDeleteTarget(null)} disabled={isDeleting}>{t("history.cancel")}</button>
              <button type="button" className="btn btn-danger" onClick={() => void confirmDelete()} disabled={isDeleting}>
                {isDeleting ? t("history.deleting") : t("history.confirmDelete")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
