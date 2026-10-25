import { ArchiveRestore, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { clearExperimentDraft } from "../features/experiment/draftStorage";
import {
  EXPERIMENT_WORKSPACES_CHANGED_EVENT,
  isExperimentWorkspaceNameAvailable,
  listExperimentWorkspaces,
  removeExperimentWorkspace,
  updateExperimentWorkspace,
  type ExperimentWorkspace,
} from "../features/experiment/workspaceRegistry";

interface ArchivedConversationManagerProps {
  ownerId: string;
  locale: "en" | "zh-CN";
  edition: BrandEditionId;
}

const COPY = {
  en: {
    heading: "Archived conversations",
    restore: "Restore",
    remove: "Remove",
    delete: "Delete permanently",
    nameInUse:
      "This name is already used by an active conversation. Choose a different name, or archive the existing conversation first.",
    removeConfirmation: (name: string) =>
      `Remove “${name}” from Conversations? The job and trials will remain in History.`,
    deleteConfirmation: (name: string) =>
      `Permanently delete draft “${name}”? This cannot be undone.`,
  },
  zh: {
    heading: "已归档对话",
    restore: "恢复",
    remove: "移除",
    delete: "永久删除",
    nameInUse: "当前已有同名的未归档对话。请使用其他名称，或先归档已有对话。",
    removeConfirmation: (name: string) =>
      `从对话列表移除“${name}”？任务和试验记录仍会保留在历史中。`,
    deleteConfirmation: (name: string) =>
      `永久删除草稿“${name}”？此操作无法撤销。`,
  },
} as const;

export function ArchivedConversationManager({
  ownerId,
  locale,
  edition,
}: ArchivedConversationManagerProps) {
  const copy = COPY[locale === "zh-CN" ? "zh" : "en"];
  const [conversations, setConversations] = useState<ExperimentWorkspace[]>([]);
  const refresh = useCallback(
    () => setConversations(
      listExperimentWorkspaces(ownerId, edition).filter((workspace) => workspace.archived),
    ),
    [edition, ownerId],
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
      window.removeEventListener(EXPERIMENT_WORKSPACES_CHANGED_EVENT, handleChanged);
      window.removeEventListener("storage", refresh);
    };
  }, [ownerId, refresh]);

  if (conversations.length === 0) return null;

  return (
    <section className="account-archived-experiments" aria-label={copy.heading}>
      <strong>{copy.heading}</strong>
      <div className="account-archived-list">
        {conversations.map((conversation) => {
          const removesJobLink = Boolean(conversation.jobId);
          const removalLabel = removesJobLink ? copy.remove : copy.delete;
          return (
            <div key={conversation.id} className="account-archived-row">
              <span title={conversation.name}>{conversation.name}</span>
              <button
                type="button"
                className="btn"
                aria-label={`${copy.restore}: ${conversation.name}`}
                title={copy.restore}
                onClick={() => {
                  if (!isExperimentWorkspaceNameAvailable(
                    ownerId,
                    conversation.name,
                    edition,
                    conversation.id,
                  )) {
                    window.alert(copy.nameInUse);
                    return;
                  }
                  updateExperimentWorkspace(ownerId, conversation.id, {
                    archived: false,
                  }, edition);
                  refresh();
                }}
              >
                <ArchiveRestore aria-hidden="true" />
              </button>
              <button
                type="button"
                className="btn danger"
                aria-label={`${removalLabel}: ${conversation.name}`}
                title={removalLabel}
                onClick={() => {
                  const confirmed = window.confirm(
                    removesJobLink
                      ? copy.removeConfirmation(conversation.name)
                      : copy.deleteConfirmation(conversation.name),
                  );
                  if (!confirmed) return;
                  if (!conversation.jobId) clearExperimentDraft(conversation.id);
                  removeExperimentWorkspace(ownerId, conversation.id, edition);
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
