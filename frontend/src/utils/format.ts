import type { JobStatus } from "../types/api";

/** Display in the viewer's local timezone; preserve invalid source text for diagnosis. */
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

/** Finalization still owns a live job lease and must continue polling. */
export function isActiveJobStatus(status: JobStatus): boolean {
  return (
    status === "CREATED" ||
    status === "QUEUED" ||
    status === "RUNNING" ||
    status === "AGGREGATING" ||
    status === "FINALIZING"
  );
}

/** Presentation only: missing/non-finite metrics are not measured zeroes. */
export function formatNumber(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return "—";
  if (Number.isInteger(value)) return value.toString();
  // Restored display preferences must not trigger toFixed's RangeError in a render.
  const precision = Number.isInteger(digits) && digits >= 0 && digits <= 100 ? digits : 2;
  return value.toFixed(precision);
}
