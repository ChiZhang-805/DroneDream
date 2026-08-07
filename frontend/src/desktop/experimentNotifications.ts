import type { Job, JobStatus } from "../types/api";
import { isDesktopRuntime } from "./bridge";

const NOTIFICATION_STORAGE_KEY = "dronedream:notify-experiment-complete";
export const EXPERIMENT_NOTIFICATION_CHANGE_EVENT =
  "dronedream:experiment-notification-change";

const TERMINAL_JOB_STATUSES = new Set<JobStatus>([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
]);

export function experimentNotificationsEnabled(): boolean {
  return window.localStorage.getItem(NOTIFICATION_STORAGE_KEY) === "true";
}

export function setExperimentNotificationsEnabled(enabled: boolean): void {
  window.localStorage.setItem(NOTIFICATION_STORAGE_KEY, String(enabled));
  window.dispatchEvent(new CustomEvent(EXPERIMENT_NOTIFICATION_CHANGE_EVENT));
}

export async function requestExperimentNotificationPermission(): Promise<boolean> {
  if (!isDesktopRuntime()) return false;
  const { isPermissionGranted, requestPermission } = await import(
    "@tauri-apps/plugin-notification"
  );
  if (await isPermissionGranted()) return true;
  return (await requestPermission()) === "granted";
}

export async function sendExperimentCompletionNotification(
  job: Pick<Job, "display_name" | "id" | "status">,
  locale: "en" | "zh-CN",
): Promise<boolean> {
  if (!isDesktopRuntime() || !TERMINAL_JOB_STATUSES.has(job.status)) return false;
  const { isPermissionGranted, sendNotification } = await import(
    "@tauri-apps/plugin-notification"
  );
  if (!(await isPermissionGranted())) return false;
  const name = job.display_name?.trim() || job.id.slice(0, 8);
  const status = locale === "zh-CN"
    ? job.status === "COMPLETED"
      ? "已完成"
      : job.status === "FAILED"
        ? "失败"
        : "已取消"
    : job.status === "COMPLETED"
      ? "completed"
      : job.status === "FAILED"
        ? "failed"
        : "cancelled";
  sendNotification({
    title: locale === "zh-CN" ? "DroneDream · SIM 调优任务" : "DroneDream · SIM tuning task",
    body: locale === "zh-CN" ? `${name}：${status}` : `${name} ${status}`,
  });
  return true;
}
