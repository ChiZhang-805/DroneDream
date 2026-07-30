import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Archive,
  ArchiveRestore,
  Check,
  ChevronDown,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from "lucide-react";

import { apiClient } from "../api/client";
import {
  clearExperimentDraft,
  renameExperimentDraft,
} from "../features/experiment/draftStorage";
import {
  EXPERIMENT_WORKSPACES_CHANGED_EVENT,
  experimentWorkspacePath,
  isExperimentWorkspaceNameAvailable,
  listExperimentWorkspaces,
  removeExperimentWorkspace,
  reorderExperimentWorkspace,
  updateExperimentWorkspace,
  type ExperimentWorkspace,
} from "../features/experiment/workspaceRegistry";

interface ExperimentWorkspaceSidebarProps {
  ownerId: string;
  locale: "en" | "zh-CN";
}

const COPY = {
  en: {
    heading: "Experiments",
    archived: "Archived",
    scrollDown: "Show more experiments",
    rename: "Rename",
    pin: "Pin",
    unpin: "Unpin",
    archive: "Archive",
    restore: "Restore",
    remove: "Remove",
    empty: "Experiments will appear here.",
    noArchived: "No archived experiments.",
    delete: "Delete permanently",
    nameInUse:
      "This name is already used by an active experiment. Choose a different name, or archive the existing experiment first.",
    removeConfirmation: (name: string) =>
      `Remove “${name}” from Experiments? The job and trials will remain in History.`,
    deleteConfirmation: (name: string) =>
      `Permanently delete draft “${name}”? This cannot be undone.`,
  },
  zh: {
    heading: "实验",
    archived: "已归档",
    scrollDown: "查看更多实验",
    rename: "重命名",
    pin: "置顶",
    unpin: "取消置顶",
    archive: "归档",
    restore: "恢复",
    remove: "移除",
    empty: "新建实验后会显示在这里。",
    noArchived: "暂无已归档实验。",
    delete: "永久删除",
    nameInUse: "当前已有同名的未归档实验。请使用其他名称，或先归档已有实验。",
    removeConfirmation: (name: string) =>
      `从实验列表移除“${name}”？任务和试验记录仍会保留在历史中。`,
    deleteConfirmation: (name: string) =>
      `永久删除草稿“${name}”？此操作无法撤销。`,
  },
} as const;

interface ContextMenuState {
  workspaceId: string;
  x: number;
  y: number;
}

interface WorkspaceDragState {
  workspaceId: string;
  insertionIndex: number | null;
}

function activeWorkspaceId(
  workspaces: ExperimentWorkspace[],
  pathname: string,
  search: string,
): string | null {
  if (pathname === "/jobs/new") {
    return new URLSearchParams(search).get("experiment");
  }
  if (pathname.startsWith("/jobs/")) {
    let jobId: string;
    try {
      jobId = decodeURIComponent(pathname.slice("/jobs/".length));
    } catch {
      return null;
    }
    return workspaces.find((workspace) => workspace.jobId === jobId)?.id ?? null;
  }
  return null;
}

export function ExperimentWorkspaceSidebar({
  ownerId,
  locale,
}: ExperimentWorkspaceSidebarProps) {
  const location = useLocation();
  const copy = COPY[locale === "zh-CN" ? "zh" : "en"];
  const [workspaces, setWorkspaces] = useState<ExperimentWorkspace[]>([]);
  const [canScrollDown, setCanScrollDown] = useState(false);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [dragState, setDragState] = useState<WorkspaceDragState | null>(null);
  const dragStateRef = useRef<WorkspaceDragState | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(
    () => setWorkspaces(listExperimentWorkspaces(ownerId)),
    [ownerId],
  );

  useEffect(() => {
    refresh();
    const handleChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ ownerId?: string }>).detail;
      if (!detail?.ownerId || detail.ownerId === ownerId) refresh();
    };
    window.addEventListener(EXPERIMENT_WORKSPACES_CHANGED_EVENT, handleChanged);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(
        EXPERIMENT_WORKSPACES_CHANGED_EVENT,
        handleChanged,
      );
      window.removeEventListener("storage", refresh);
    };
  }, [ownerId, refresh]);

  useEffect(() => {
    if (!contextMenu) return undefined;
    const close = (event: PointerEvent) => {
      if (
        event.target instanceof Node
        && !menuRef.current?.contains(event.target)
      ) {
        setContextMenu(null);
      }
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setContextMenu(null);
    };
    const closeOnBlur = () => setContextMenu(null);
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("blur", closeOnBlur);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("blur", closeOnBlur);
    };
  }, [contextMenu]);

  useEffect(() => {
    if (renamingId) renameInputRef.current?.select();
  }, [renamingId]);

  const visible = useMemo(
    () => workspaces.filter((workspace) => !workspace.archived),
    [workspaces],
  );
  const selectedId = activeWorkspaceId(
    workspaces,
    location.pathname,
    location.search,
  );
  const selectedForMenu = workspaces.find(
    (workspace) => workspace.id === contextMenu?.workspaceId,
  );
  const remainingDuringDrag = dragState
    ? visible.filter((workspace) => workspace.id !== dragState.workspaceId)
    : [];
  const previewBeforeId = dragState?.insertionIndex !== null
    && dragState?.insertionIndex !== undefined
    ? remainingDuringDrag[dragState.insertionIndex]?.id ?? null
    : null;
  const previewAtEnd = Boolean(
    dragState
    && dragState.insertionIndex === remainingDuringDrag.length,
  );

  const updateScrollAffordance = useCallback(() => {
    const list = listRef.current;
    if (!list) {
      setCanScrollDown(false);
      return;
    }
    setCanScrollDown(
      list.scrollHeight - list.scrollTop - list.clientHeight > 3,
    );
  }, []);

  useEffect(() => {
    const frame = window.requestAnimationFrame(updateScrollAffordance);
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(updateScrollAffordance);
    if (listRef.current) observer?.observe(listRef.current);
    window.addEventListener("resize", updateScrollAffordance);
    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", updateScrollAffordance);
    };
  }, [updateScrollAffordance, visible.length]);

  async function commitRename(workspace: ExperimentWorkspace): Promise<void> {
    const nextName = renameValue.trim().replace(/\s+/gu, " ").slice(0, 255);
    if (!nextName) {
      setRenamingId(null);
      return;
    }
    if (
      !isExperimentWorkspaceNameAvailable(ownerId, nextName, workspace.id)
    ) {
      renameInputRef.current?.setCustomValidity(copy.nameInUse);
      renameInputRef.current?.reportValidity();
      renameInputRef.current?.focus();
      return;
    }
    if (workspace.jobId) {
      try {
        const job = await apiClient.getJob(workspace.jobId);
        await apiClient.updateJob(
          workspace.jobId,
          { display_name: nextName },
          job.control_version,
        );
      } catch {
        return;
      }
    } else {
      renameExperimentDraft(workspace.id, nextName);
    }
    updateExperimentWorkspace(ownerId, workspace.id, { name: nextName });
    setRenamingId(null);
    refresh();
  }

  function startRename(workspace: ExperimentWorkspace): void {
    setContextMenu(null);
    setRenamingId(workspace.id);
    setRenameValue(workspace.name);
  }

  function updateDragState(nextState: WorkspaceDragState | null): void {
    dragStateRef.current = nextState;
    setDragState(nextState);
  }

  function clearDragState(): void {
    if (listRef.current) {
      delete listRef.current.dataset.workspaceDropIndex;
      delete listRef.current.dataset.workspaceDragId;
    }
    updateDragState(null);
  }

  return (
    <section className="app-workspaces" aria-label={copy.heading}>
      <header className="app-workspaces-header">
        <span>{copy.heading}</span>
        {canScrollDown ? (
          <button
            type="button"
            aria-label={copy.scrollDown}
            title={copy.scrollDown}
            onClick={() => {
              listRef.current?.scrollBy({
                top: Math.max(140, (listRef.current?.clientHeight ?? 0) * 0.72),
                behavior: "smooth",
              });
            }}
          >
            <ChevronDown aria-hidden="true" />
          </button>
        ) : null}
      </header>

      <div
        ref={listRef}
        className="app-workspace-list"
        onScroll={updateScrollAffordance}
        onDragOver={(event) => {
          const currentDragState = dragStateRef.current;
          if (!currentDragState) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
          const rows = Array.from(
            event.currentTarget.querySelectorAll<HTMLElement>(
              ".app-workspace-row:not(.is-drag-source)",
            ),
          );
          const insertionIndex = rows.findIndex(
            (row) => event.clientY < row.getBoundingClientRect().top
              + row.getBoundingClientRect().height / 2,
          );
          const nextIndex = insertionIndex < 0 ? rows.length : insertionIndex;
          event.currentTarget.dataset.workspaceDropIndex = String(nextIndex);
          if (currentDragState.insertionIndex !== nextIndex) {
            updateDragState({
              ...currentDragState,
              insertionIndex: nextIndex,
            });
          }
        }}
        onDrop={(event) => {
          const currentDragState = dragStateRef.current;
          const workspaceId = currentDragState?.workspaceId
            || event.dataTransfer.getData("text/plain")
            || event.currentTarget.dataset.workspaceDragId;
          const insertionIndex = currentDragState?.insertionIndex
            ?? Number.parseInt(
              event.currentTarget.dataset.workspaceDropIndex ?? "",
              10,
            );
          if (!workspaceId || !Number.isInteger(insertionIndex)) {
            clearDragState();
            return;
          }
          event.preventDefault();
          const reordered = reorderExperimentWorkspace(
            ownerId,
            workspaceId,
            insertionIndex,
          );
          setWorkspaces(reordered);
          clearDragState();
        }}
      >
        {visible.map((workspace) => (
          <Fragment key={workspace.id}>
            {previewBeforeId === workspace.id ? (
              <div className="app-workspace-drop-preview" aria-hidden="true" />
            ) : null}
            <div
              data-workspace-id={workspace.id}
              draggable={renamingId !== workspace.id}
              className={`app-workspace-row${
                selectedId === workspace.id ? " active" : ""
              }${dragState?.workspaceId === workspace.id ? " is-drag-source" : ""}`}
              onDragStart={(event) => {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", workspace.id);
                if (listRef.current) {
                  listRef.current.dataset.workspaceDragId = workspace.id;
                  delete listRef.current.dataset.workspaceDropIndex;
                }
                updateDragState({
                  workspaceId: workspace.id,
                  insertionIndex: null,
                });
                setContextMenu(null);
              }}
              onDragEnd={clearDragState}
              onContextMenu={(event) => {
                event.preventDefault();
                setContextMenu({
                  workspaceId: workspace.id,
                  x: Math.max(8, Math.min(event.clientX, window.innerWidth - 190)),
                  y: Math.max(8, Math.min(event.clientY, window.innerHeight - 150)),
                });
              }}
            >
            {renamingId === workspace.id ? (
              <form
                className="app-workspace-rename"
                onSubmit={(event) => {
                  event.preventDefault();
                  void commitRename(workspace);
                }}
                onBlur={(event) => {
                  const nextTarget = event.relatedTarget;
                  if (
                    nextTarget instanceof Node
                    && event.currentTarget.contains(nextTarget)
                  ) return;
                  void commitRename(workspace);
                }}
              >
                <input
                  ref={renameInputRef}
                  value={renameValue}
                  maxLength={255}
                  onChange={(event) => {
                    event.currentTarget.setCustomValidity("");
                    setRenameValue(event.target.value);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") setRenamingId(null);
                  }}
                  aria-label={copy.rename}
                />
                <button type="submit" aria-label={copy.rename}>
                  <Check aria-hidden="true" />
                </button>
              </form>
            ) : (
              <>
                <Link
                  to={experimentWorkspacePath(workspace)}
                  title={workspace.name}
                >
                  <span className="app-workspace-label">
                    <strong>{workspace.name}</strong>
                  </span>
                  {workspace.pinned ? (
                    <span
                      className="app-workspace-pinned-indicator"
                      title={copy.unpin}
                      aria-label={copy.unpin}
                    >
                      <Pin aria-hidden="true" />
                    </span>
                  ) : null}
                </Link>
                <span className="app-workspace-actions">
                  <button
                    type="button"
                    className={workspace.pinned ? "is-active" : undefined}
                    aria-label={workspace.pinned ? copy.unpin : copy.pin}
                    title={workspace.pinned ? copy.unpin : copy.pin}
                    onClick={() => {
                      updateExperimentWorkspace(ownerId, workspace.id, {
                        pinned: !workspace.pinned,
                      });
                      refresh();
                    }}
                  >
                    {workspace.pinned ? (
                      <PinOff aria-hidden="true" />
                    ) : (
                      <Pin aria-hidden="true" />
                    )}
                  </button>
                  <button
                    type="button"
                    aria-label={copy.archive}
                    title={copy.archive}
                    onClick={() => {
                      updateExperimentWorkspace(ownerId, workspace.id, {
                        archived: true,
                      });
                      refresh();
                    }}
                  >
                    <Archive aria-hidden="true" />
                  </button>
                </span>
              </>
            )}
            </div>
          </Fragment>
        ))}
        {previewAtEnd ? (
          <div className="app-workspace-drop-preview" aria-hidden="true" />
        ) : null}
        {visible.length === 0 ? (
          <p className="app-workspaces-empty">{copy.empty}</p>
        ) : null}
      </div>

      {contextMenu && selectedForMenu ? (
        <div
          ref={menuRef}
          className="app-workspace-menu"
          role="menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => startRename(selectedForMenu)}
          >
            <Pencil aria-hidden="true" />
            {copy.rename}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              updateExperimentWorkspace(ownerId, selectedForMenu.id, {
                pinned: !selectedForMenu.pinned,
              });
              setContextMenu(null);
              refresh();
            }}
          >
            {selectedForMenu.pinned ? (
              <PinOff aria-hidden="true" />
            ) : (
              <Pin aria-hidden="true" />
            )}
            {selectedForMenu.pinned ? copy.unpin : copy.pin}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              updateExperimentWorkspace(ownerId, selectedForMenu.id, {
                archived: true,
              });
              setContextMenu(null);
              refresh();
            }}
          >
            <Archive aria-hidden="true" />
            {copy.archive}
          </button>
        </div>
      ) : null}
    </section>
  );
}

export function ArchivedExperimentManager({
  ownerId,
  locale,
}: ExperimentWorkspaceSidebarProps) {
  const copy = COPY[locale === "zh-CN" ? "zh" : "en"];
  const [workspaces, setWorkspaces] = useState<ExperimentWorkspace[]>([]);
  const refresh = useCallback(
    () => setWorkspaces(
      listExperimentWorkspaces(ownerId).filter((workspace) => workspace.archived),
    ),
    [ownerId],
  );

  useEffect(() => {
    refresh();
    const handleChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ ownerId?: string }>).detail;
      if (!detail?.ownerId || detail.ownerId === ownerId) refresh();
    };
    window.addEventListener(EXPERIMENT_WORKSPACES_CHANGED_EVENT, handleChanged);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(
        EXPERIMENT_WORKSPACES_CHANGED_EVENT,
        handleChanged,
      );
      window.removeEventListener("storage", refresh);
    };
  }, [ownerId, refresh]);

  if (workspaces.length === 0) return null;

  return (
    <section className="account-archived-experiments">
      <strong>{copy.archived}</strong>
      <div className="account-archived-list">
        {workspaces.map((workspace) => {
          const removesJobLink = Boolean(workspace.jobId);
          const removalLabel = removesJobLink ? copy.remove : copy.delete;
          return (
            <div key={workspace.id} className="account-archived-row">
              <span title={workspace.name}>{workspace.name}</span>
              <button
                type="button"
                className="btn"
                aria-label={`${copy.restore}: ${workspace.name}`}
                title={copy.restore}
                onClick={() => {
                  if (
                    !isExperimentWorkspaceNameAvailable(
                      ownerId,
                      workspace.name,
                      workspace.id,
                    )
                  ) {
                    window.alert(copy.nameInUse);
                    return;
                  }
                  updateExperimentWorkspace(ownerId, workspace.id, {
                    archived: false,
                  });
                  refresh();
                }}
              >
                <ArchiveRestore aria-hidden="true" />
              </button>
              <button
                type="button"
                className="btn danger"
                aria-label={`${removalLabel}: ${workspace.name}`}
                title={removalLabel}
                onClick={() => {
                  const confirmed = window.confirm(
                    removesJobLink
                      ? copy.removeConfirmation(workspace.name)
                      : copy.deleteConfirmation(workspace.name),
                  );
                  if (!confirmed) return;
                  if (!workspace.jobId) clearExperimentDraft(workspace.id);
                  removeExperimentWorkspace(ownerId, workspace.id);
                  refresh();
                }}
              >
                <Trash2 aria-hidden="true" />
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
