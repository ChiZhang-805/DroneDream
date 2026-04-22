import type { JobStatus } from "../types/api";

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function isActiveJobStatus(status: JobStatus): boolean {
  return (
    status === "CREATED" ||
    status === "QUEUED" ||
    status === "RUNNING" ||
    status === "AGGREGATING"
  );
}

export function formatNumber(value: number, digits = 2): string {
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(digits);
}
