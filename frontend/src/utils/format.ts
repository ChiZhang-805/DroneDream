import type { JobStatus } from "../types/api";

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const yyyy = d.getFullYear();
  const month = d.getMonth() + 1;
  const day = d.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}/${month}/${day} ${hh}:${mm}`;
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
