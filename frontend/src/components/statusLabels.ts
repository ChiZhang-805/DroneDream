import type { JobStatus, TrialStatus } from "../types/api";
import type { TranslationKey } from "../i18n/I18nProvider";

type AnyStatus = JobStatus | TrialStatus;

const STATUS_LABELS: Record<AnyStatus, TranslationKey> = {
  CREATED: "status.created",
  QUEUED: "status.queued",
  PENDING: "status.pending",
  RUNNING: "status.running",
  AGGREGATING: "status.aggregating",
  FINALIZING: "status.finalizing",
  COMPLETED: "status.completed",
  FAILED: "status.failed",
  CANCELLED: "status.cancelled",
};

export function statusTranslationKey(status: AnyStatus): TranslationKey {
  return STATUS_LABELS[status];
}
