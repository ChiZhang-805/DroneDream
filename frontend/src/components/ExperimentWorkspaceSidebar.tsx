import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  listExperimentWorkspaces,
  removeExperimentWorkspace,
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
    empty: "Your experiments and recent runs appear here together.",
    noArchived: "No archived experiments.",
    delete: "Delete permanently",
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
  },
} as const;

interface ContextMenuState {
  workspaceId: string;
  x: number;
  y: number;
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
    const jobId = decodeURIComponent(pathname.slice("/jobs/".length));
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
      >
        {visible.map((workspace) => (
          <div
            key={workspace.id}
            className={`app-workspace-row${
              selectedId === workspace.id ? " active" : ""
            }`}
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
              >
                <input
                  ref={renameInputRef}
                  value={renameValue}
                  maxLength={255}
                  onChange={(event) => setRenameValue(event.target.value)}
                  onBlur={() => void commitRename(workspace)}
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
        ))}
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
        {workspaces.map((workspace) => (
          <div key={workspace.id} className="account-archived-row">
            <span title={workspace.name}>{workspace.name}</span>
            <button
              type="button"
              className="btn"
              aria-label={`${copy.restore}: ${workspace.name}`}
              title={copy.restore}
              onClick={() => {
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
              aria-label={`${copy.delete}: ${workspace.name}`}
              title={copy.delete}
              onClick={() => {
                if (!workspace.jobId) clearExperimentDraft(workspace.id);
                removeExperimentWorkspace(ownerId, workspace.id);
                refresh();
              }}
            >
              <Trash2 aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
