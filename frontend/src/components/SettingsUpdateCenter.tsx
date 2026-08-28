import {
  CircleAlert,
  CircleCheckBig,
  Download,
  RefreshCcw,
  type LucideIcon,
} from "lucide-react";

import { useAppUpdaterState } from "../desktop/updaterContext";
import { localeSafeError, useI18n } from "../i18n/I18nProvider";

type SettingsUpdateTone = "current" | "busy" | "attention" | "error";

export function SettingsUpdateCenter({
  onOpenRuntimeBase,
  runtimeBaseActionDisabled = false,
}: {
  onOpenRuntimeBase: () => void | Promise<void>;
  runtimeBaseActionDisabled?: boolean;
}) {
  const { locale, t } = useI18n();
  const updater = useAppUpdaterState();
  const candidates = updater.componentUpdates?.candidates.filter((candidate) => (
    candidate.available
  )) ?? [];
  const progress = updater.progress === null
    ? null
    : Math.max(0, Math.min(100, updater.progress));
  const localizedError = updater.error
    ? localeSafeError(updater.error, locale, {
        zh: "更新暂时无法完成。",
        en: "The update could not be completed.",
      })
    : null;
  const copy = locale === "zh-CN"
    ? {
        stateLabel: "软件版本状态：",
        current: "已是最新版本",
        checking: "正在检查",
        oldVersion: "旧版本",
        downloading: "正在下载",
        installing: "正在安装",
        reconciling: "正在同步组件",
        deferred: "等待重试",
        failed: "检查失败",
        runtimeRequired: "Runtime Base 需要更新",
      }
    : {
        stateLabel: "software version state:",
        current: "up-to-date",
        checking: "checking",
        oldVersion: "old-version",
        downloading: "downloading",
        installing: "installing",
        reconciling: "reconciling components",
        deferred: "retry required",
        failed: "check failed",
        runtimeRequired: "Runtime Base update required",
      };

  let stateValue = copy.current;
  let tone: SettingsUpdateTone = "current";
  let StatusIcon: LucideIcon = CircleCheckBig;
  let actionLabel: string | null = t("settings.updates.checkNow");
  let action: (() => void | Promise<void>) | null = () => { void updater.checkForUpdates(); };
  let actionPrimary = false;
  let actionDisabled = false;

  if (updater.status === "checking") {
    stateValue = copy.checking;
    tone = "busy";
    StatusIcon = RefreshCcw;
    actionLabel = t("updater.checking");
    action = null;
    actionDisabled = true;
  } else if (updater.status === "available") {
    stateValue = `${copy.oldVersion}${updater.availableVersion ? ` · v${updater.availableVersion}` : ""}`;
    tone = "attention";
    StatusIcon = Download;
    actionLabel = localizedError
      ? t("settings.updates.retry")
      : t("settings.updates.installApp");
    action = () => { void updater.installAvailableUpdate(); };
    actionPrimary = updater.updateRequired;
  } else if (updater.status === "downloading") {
    stateValue = `${copy.downloading}${progress === null ? "" : ` · ${progress}%`}`;
    tone = "busy";
    StatusIcon = Download;
    actionLabel = null;
    action = null;
  } else if (updater.status === "installing") {
    stateValue = `${copy.installing}${progress === null ? "" : ` · ${progress}%`}`;
    tone = "busy";
    StatusIcon = RefreshCcw;
    actionLabel = null;
    action = null;
  } else if (updater.status === "reconcilingEngine") {
    stateValue = copy.reconciling;
    tone = "busy";
    StatusIcon = RefreshCcw;
    actionLabel = null;
    action = null;
  } else if (updater.status === "engineUpdateDeferred") {
    stateValue = copy.deferred;
    tone = "attention";
    StatusIcon = RefreshCcw;
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.reconcileEnginePack(); };
  } else if (updater.status === "engineError") {
    stateValue = copy.failed;
    tone = "error";
    StatusIcon = CircleAlert;
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.reconcileEnginePack(); };
  } else if (updater.status === "componentAvailable") {
    const versions = [...new Set(candidates.map((candidate) => `v${candidate.version}`))];
    stateValue = `${copy.oldVersion}${versions.length > 0 ? ` · ${versions.join(" / ")}` : ""}`;
    tone = "attention";
    StatusIcon = Download;
    actionLabel = t("settings.updates.installPacks");
    action = () => { void updater.installComponentUpdates(); };
    actionPrimary = candidates.some((candidate) => candidate.urgency === "required");
  } else if (updater.status === "installingComponents") {
    stateValue = `${copy.installing}${progress === null ? "" : ` · ${progress}%`}`;
    tone = "busy";
    StatusIcon = RefreshCcw;
    actionLabel = null;
    action = null;
  } else if (updater.status === "componentUpdateDeferred") {
    stateValue = copy.deferred;
    tone = "attention";
    StatusIcon = RefreshCcw;
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.checkForUpdates(); };
  } else if (updater.status === "componentError") {
    stateValue = copy.failed;
    tone = "error";
    StatusIcon = CircleAlert;
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.checkForUpdates(); };
  } else if (updater.status === "runtimeBaseRequired") {
    stateValue = copy.runtimeRequired;
    tone = "error";
    StatusIcon = Download;
    actionLabel = t("settings.updates.openRuntimeBase");
    action = onOpenRuntimeBase;
    actionPrimary = true;
    actionDisabled = runtimeBaseActionDisabled;
  } else if (updater.status === "error") {
    stateValue = copy.failed;
    tone = "error";
    StatusIcon = CircleAlert;
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.checkForUpdates(); };
  }

  return (
    <section className="settings-update-center settings-runtime-module" aria-labelledby="settings-updates-title">
      <div className="settings-update-heading">
        <h3 id="settings-updates-title">{t("settings.updates.title")}</h3>
        {actionLabel ? (
          <button
            type="button"
            className={`btn settings-update-action${actionPrimary ? " btn-primary" : ""}`}
            disabled={actionDisabled}
            onClick={() => { void action?.(); }}
          >
            {actionLabel}
          </button>
        ) : null}
      </div>
      <div
        className={`settings-update-state settings-update-state-${tone}`}
        role="status"
        aria-label={`${copy.stateLabel} ${stateValue}`}
        aria-live="polite"
        aria-busy={tone === "busy"}
        title={localizedError ?? undefined}
      >
        <span className="settings-update-icon" aria-hidden="true">
          <StatusIcon />
        </span>
        <p className="settings-update-copy">
          <span>{copy.stateLabel}</span>
          <strong>{stateValue}</strong>
        </p>
        {progress !== null && [
          "downloading",
          "installing",
          "installingComponents",
        ].includes(updater.status) ? (
          <progress
            className="sr-only"
            max={100}
            value={progress}
            aria-label={t("settings.updates.progressLabel")}
          />
        ) : null}
        {localizedError ? <span className="sr-only">{localizedError}</span> : null}
      </div>
    </section>
  );
}
