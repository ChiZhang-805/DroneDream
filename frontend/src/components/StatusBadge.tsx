import type { JobStatus, TrialStatus } from "../types/api";
import { useI18n } from "../i18n/I18nProvider";
import { statusTranslationKey } from "./statusLabels";

type AnyStatus = JobStatus | TrialStatus;

const STATUS_TONE: Record<AnyStatus, string> = {
  CREATED: "info",
  QUEUED: "info",
  PENDING: "info",
  RUNNING: "active",
  AGGREGATING: "active",
  FINALIZING: "active",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "muted",
};

export function StatusBadge({ status }: { status: AnyStatus }) {
  const { t } = useI18n();
  const tone = STATUS_TONE[status] ?? "muted";
  return (
    <span className={`status-badge status-${tone}`} data-status={status}>
      {t(statusTranslationKey(status))}
    </span>
  );
}
