import type { Job, JobStatus } from "../types/api";
import { isDesktopRuntime } from "./bridge";

const LEGACY_NOTIFICATION_STORAGE_KEY = "dronedream:notify-experiment-complete";
const NOTIFICATION_STORAGE_KEY = "dronedream:notification-preferences-v2";
export const EXPERIMENT_NOTIFICATION_CHANGE_EVENT =
  "dronedream:experiment-notification-change";

export interface ExperimentNotificationPreferences {
  enabled: boolean;
  taskResults: boolean;
  attentionRequired: boolean;
  qualificationResults: boolean;
  environmentIssues: boolean;
}

export const DEFAULT_EXPERIMENT_NOTIFICATION_PREFERENCES:
ExperimentNotificationPreferences = Object.freeze({
  enabled: false,
  taskResults: true,
  attentionRequired: true,
  qualificationResults: true,
  environmentIssues: true,
});

const TERMINAL_JOB_STATUSES = new Set<JobStatus>([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
]);

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

export function getExperimentNotificationPreferences(): ExperimentNotificationPreferences {
  const raw = window.localStorage.getItem(NOTIFICATION_STORAGE_KEY);
  if (raw) {
    try {
      const candidate = JSON.parse(raw) as Partial<ExperimentNotificationPreferences>;
      if (
        isBoolean(candidate.enabled)
        && isBoolean(candidate.taskResults)
        && isBoolean(candidate.attentionRequired)
        && isBoolean(candidate.qualificationResults)
        && isBoolean(candidate.environmentIssues)
      ) {
        return { ...candidate } as ExperimentNotificationPreferences;
      }
    } catch {
      // Corrupt local preferences fail closed to the disabled default.
    }
    return { ...DEFAULT_EXPERIMENT_NOTIFICATION_PREFERENCES };
  }
  const legacyEnabled = window.localStorage.getItem(LEGACY_NOTIFICATION_STORAGE_KEY) === "true";
  return { ...DEFAULT_EXPERIMENT_NOTIFICATION_PREFERENCES, enabled: legacyEnabled };
}

export function setExperimentNotificationPreferences(
  preferences: ExperimentNotificationPreferences,
): void {
  window.localStorage.setItem(NOTIFICATION_STORAGE_KEY, JSON.stringify(preferences));
  window.localStorage.removeItem(LEGACY_NOTIFICATION_STORAGE_KEY);
  window.dispatchEvent(new CustomEvent(EXPERIMENT_NOTIFICATION_CHANGE_EVENT));
}

export function experimentNotificationsEnabled(): boolean {
  return getExperimentNotificationPreferences().enabled;
}

export function setExperimentNotificationsEnabled(enabled: boolean): void {
  setExperimentNotificationPreferences({
    ...getExperimentNotificationPreferences(),
    enabled,
  });
}

export async function requestExperimentNotificationPermission(): Promise<boolean> {
  if (!isDesktopRuntime()) return false;
  const { isPermissionGranted, requestPermission } = await import(
    "@tauri-apps/plugin-notification"
  );
  if (await isPermissionGranted()) return true;
  return (await requestPermission()) === "granted";
}

async function sendDesktopNotification(title: string, body: string): Promise<boolean> {
  if (!isDesktopRuntime()) return false;
  const { isPermissionGranted, sendNotification } = await import(
    "@tauri-apps/plugin-notification"
  );
  if (!(await isPermissionGranted())) return false;
  sendNotification({ title, body });
  return true;
}

export async function sendExperimentCompletionNotification(
  job: Pick<Job, "display_name" | "first_qualified_candidate_id" | "id" | "status">
    & Partial<Pick<Job, "optimization_outcome">>,
  locale: "en" | "zh-CN",
  preferences = getExperimentNotificationPreferences(),
): Promise<boolean> {
  if (!preferences.enabled || !TERMINAL_JOB_STATUSES.has(job.status)) return false;
  const name = job.display_name?.trim() || job.id.slice(0, 8);
  const attentionOutcomes = new Set([
    "exploration_budget_exhausted",
    "llm_failed",
    "no_usable_candidate",
    "simulator_unavailable",
  ]);
  const needsAttention = (
    job.status === "FAILED"
    || (job.optimization_outcome !== undefined
      && job.optimization_outcome !== null
      && attentionOutcomes.has(job.optimization_outcome))
  );
  const qualified = job.status === "COMPLETED" && Boolean(job.first_qualified_candidate_id);

  if (needsAttention) {
    if (!preferences.attentionRequired) return false;
    return sendDesktopNotification(
      locale === "zh-CN" ? "DroneDream · SIM 需要处理" : "DroneDream · SIM needs attention",
      locale === "zh-CN" ? `${name}：调优任务失败，请检查失败原因。` : `${name} failed. Review the failure evidence.`,
    );
  }
  if (qualified && preferences.qualificationResults) {
    return sendDesktopNotification(
      locale === "zh-CN" ? "DroneDream · SIM 资格验证" : "DroneDream · SIM qualification",
      locale === "zh-CN" ? `${name}：候选参数已通过资格验证。` : `${name} produced a qualified candidate.`,
    );
  }
  if (!preferences.taskResults) return false;
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
  return sendDesktopNotification(
    locale === "zh-CN" ? "DroneDream · SIM 调优任务" : "DroneDream · SIM tuning task",
    locale === "zh-CN" ? `${name}：${status}` : `${name} ${status}`,
  );
}

export async function sendEnvironmentIssueNotification(
  locale: "en" | "zh-CN",
  preferences = getExperimentNotificationPreferences(),
): Promise<boolean> {
  if (!preferences.enabled || !preferences.environmentIssues) return false;
  return sendDesktopNotification(
    locale === "zh-CN" ? "DroneDream · SIM 运行环境异常" : "DroneDream · SIM environment issue",
    locale === "zh-CN"
      ? "此前正常的本地运行环境未通过最新检查，请打开运行环境设置查看。"
      : "The previously healthy local environment did not pass its latest check.",
  );
}
