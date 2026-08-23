import {
  Download,
  RefreshCcw,
  ShieldCheck,
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

  let headline = t("updater.current");
  let detail = t("settings.updates.currentHint");
  let tone: SettingsUpdateTone = "current";
  let StatusIcon: LucideIcon = ShieldCheck;
  let actionLabel: string | null = t("settings.updates.checkNow");
  let action: (() => void | Promise<void>) | null = () => { void updater.checkForUpdates(); };
  let actionPrimary = false;
  let actionDisabled = false;
  const badges: Array<{
    id: "required" | "recommended" | "optional" | "automatic";
    label: string;
  }> = [];

  if (updater.status === "checking") {
    headline = t("updater.checking");
    detail = t("settings.updates.checkingHint");
    tone = "busy";
    StatusIcon = RefreshCcw;
    actionLabel = t("updater.checking");
    action = null;
    actionDisabled = true;
  } else if (updater.status === "available") {
    headline = t("updater.available", { version: updater.availableVersion ?? "" });
    detail = t(updater.updateRequired
      ? "settings.updates.requiredHint"
      : "settings.updates.recommendedHint");
    tone = "attention";
    StatusIcon = Download;
    badges.push({
      id: updater.updateRequired ? "required" : "recommended",
      label: t(updater.updateRequired
        ? "settings.updates.required"
        : "settings.updates.recommended"),
    });
    actionLabel = localizedError
      ? t("settings.updates.retry")
      : t("settings.updates.installApp");
    action = () => { void updater.installAvailableUpdate(); };
    actionPrimary = updater.updateRequired;
  } else if (updater.status === "downloading") {
    headline = t("settings.updates.downloading");
    detail = t("settings.updates.inProgressHint");
    tone = "busy";
    StatusIcon = Download;
    actionLabel = null;
    action = null;
  } else if (updater.status === "installing") {
    headline = t("updater.installing");
    detail = t("settings.updates.inProgressHint");
    tone = "busy";
    StatusIcon = RefreshCcw;
    actionLabel = null;
    action = null;
  } else if (updater.status === "reconcilingEngine") {
    headline = t("updater.engine");
    detail = t("settings.updates.automaticHint");
    tone = "busy";
    StatusIcon = RefreshCcw;
    badges.push({ id: "automatic", label: t("settings.updates.automatic") });
    actionLabel = null;
    action = null;
  } else if (updater.status === "engineUpdateDeferred") {
    headline = t("updater.engineDeferred");
    detail = t("settings.updates.deferredHint");
    tone = "attention";
    StatusIcon = RefreshCcw;
    badges.push({ id: "automatic", label: t("settings.updates.automatic") });
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.reconcileEnginePack(); };
  } else if (updater.status === "engineError") {
    headline = t("settings.updates.engineError");
    detail = t("settings.updates.retryHint");
    tone = "error";
    StatusIcon = RefreshCcw;
    badges.push({ id: "automatic", label: t("settings.updates.automatic") });
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.reconcileEnginePack(); };
  } else if (updater.status === "componentAvailable") {
    const urgency = candidates.some((candidate) => candidate.urgency === "required")
      ? "required"
      : candidates.some((candidate) => candidate.urgency === "recommended")
        ? "recommended"
        : "optional";
    headline = t("settings.updates.packsAvailable");
    detail = t(urgency === "required"
      ? "settings.updates.requiredHint"
      : urgency === "recommended"
        ? "settings.updates.recommendedHint"
        : "settings.updates.optionalHint");
    tone = "attention";
    StatusIcon = Download;
    badges.push({ id: urgency, label: t(`settings.updates.${urgency}`) });
    if (candidates.some((candidate) => candidate.installMode === "automatic")) {
      badges.push({ id: "automatic", label: t("settings.updates.automatic") });
    }
    actionLabel = t("settings.updates.installPacks");
    action = () => { void updater.installComponentUpdates(); };
    actionPrimary = urgency === "required";
  } else if (updater.status === "installingComponents") {
    headline = t("updater.components");
    detail = t("settings.updates.inProgressHint");
    tone = "busy";
    StatusIcon = RefreshCcw;
    if (candidates.some((candidate) => candidate.installMode === "automatic")) {
      badges.push({ id: "automatic", label: t("settings.updates.automatic") });
    }
    actionLabel = null;
    action = null;
  } else if (updater.status === "componentUpdateDeferred") {
    headline = t("settings.updates.packsDeferred");
    detail = t("settings.updates.deferredHint");
    tone = "attention";
    StatusIcon = RefreshCcw;
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.checkForUpdates(); };
  } else if (updater.status === "componentError") {
    headline = t("settings.updates.packsError");
    detail = t("settings.updates.retryHint");
    tone = "error";
    StatusIcon = RefreshCcw;
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.checkForUpdates(); };
  } else if (updater.status === "runtimeBaseRequired") {
    headline = t("updater.runtimeBaseRequired");
    detail = t("settings.updates.runtimeBaseHint");
    tone = "error";
    StatusIcon = Download;
    badges.push({ id: "required", label: t("settings.updates.required") });
    actionLabel = t("settings.updates.openRuntimeBase");
    action = onOpenRuntimeBase;
    actionPrimary = true;
    actionDisabled = runtimeBaseActionDisabled;
  } else if (updater.status === "error") {
    headline = t("updater.error");
    detail = t("settings.updates.retryHint");
    tone = "error";
    StatusIcon = RefreshCcw;
    actionLabel = t("settings.updates.retry");
    action = () => { void updater.checkForUpdates(); };
  }

  return (
    <section className="settings-update-center" aria-labelledby="settings-updates-title">
      <div className="settings-update-heading">
        <div>
          <h3 id="settings-updates-title">{t("settings.updates.title")}</h3>
          <p>{t("settings.updates.description")}</p>
        </div>
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
        aria-live="polite"
        aria-busy={tone === "busy"}
      >
        <span className="settings-update-icon" aria-hidden="true">
          <StatusIcon />
        </span>
        <div className="settings-update-copy">
          <strong>{headline}</strong>
          <small>{detail}</small>
        </div>
        {badges.length > 0 ? (
          <div className="settings-update-badges">
            {badges.map((badge) => (
              <span key={badge.id} data-update-policy={badge.id}>{badge.label}</span>
            ))}
          </div>
        ) : null}
      </div>
      {progress !== null && [
        "downloading",
        "installing",
        "installingComponents",
      ].includes(updater.status) ? (
        <div className="settings-update-progress">
          <progress
            max={100}
            value={progress}
            aria-label={t("settings.updates.progressLabel")}
          />
          <span>{progress}%</span>
        </div>
      ) : null}
      {candidates.length > 0 ? (
        <ul className="settings-update-components" aria-label={t("settings.updates.packList")}>
          {candidates.map((candidate) => (
            <li key={candidate.componentId}>
              <span>
                <strong>{t(candidate.componentId === "capability-pack"
                  ? "settings.updates.capabilityPack"
                  : "settings.updates.assetPack")}</strong>
                <small>v{candidate.version}</small>
              </span>
              <span className="settings-update-component-policies">
                <em data-update-policy={candidate.urgency}>
                  {t(`settings.updates.${candidate.urgency}`)}
                </em>
                {candidate.installMode === "automatic" ? (
                  <em data-update-policy="automatic">{t("settings.updates.automatic")}</em>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {localizedError ? (
        <p className="settings-update-error" role="alert">{localizedError}</p>
      ) : null}
    </section>
  );
}
