import type { JobStatus, TrialStatus } from "../types/api";

type AnyStatus = JobStatus | TrialStatus;

const STATUS_TONE: Record<AnyStatus, string> = {
  CREATED: "info",
  QUEUED: "info",
  PENDING: "info",
  RUNNING: "active",
  AGGREGATING: "active",
  COMPLETED: "success",
  FAILED: "danger",
  CANCELLED: "muted",
};

export function StatusBadge({ status }: { status: AnyStatus }) {
  const tone = STATUS_TONE[status] ?? "muted";
  return (
    <span className={`status-badge status-${tone}`} data-status={status}>
      {status}
    </span>
  );
}
