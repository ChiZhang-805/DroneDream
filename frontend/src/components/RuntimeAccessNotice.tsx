import { openAppSettings } from "../appSettings";
import { useDesktopRuntimeAccess } from "../desktop/access";
import { useI18n } from "../i18n/I18nProvider";
import { Alert } from "./Alert";

export function RuntimeAccessNotice({
  page,
}: {
  page: "dashboard" | "history";
}) {
  const runtimeAccess = useDesktopRuntimeAccess();
  const { t } = useI18n();
  const checking = runtimeAccess.status === "checking";
  const starting = runtimeAccess.status === "starting";
  const startFailed = runtimeAccess.status === "startFailed";
  const busy = checking || starting;

  return (
    <Alert
      tone={busy ? "info" : "warning"}
      title={checking
        ? t("runtimeGate.checkingTitle")
        : starting
          ? t("runtimeGate.startingTitle")
          : startFailed
            ? t("runtimeGate.startFailedTitle")
            : t("runtimeGate.previewTitle")}
    >
      <p className="runtime-access-copy">
        {checking
          ? t("runtimeGate.checkingBody")
          : starting
            ? t("runtimeGate.startingBody")
            : startFailed
              ? t("runtimeGate.startFailedBody")
              : page === "dashboard"
                ? t("runtimeGate.dashboardPreviewBody")
                : t("runtimeGate.historyPreviewBody")}
      </p>
      {!busy ? (
        <button className="btn btn-primary" type="button" onClick={openAppSettings}>
          {t("runtimeGate.openSetup")}
        </button>
      ) : null}
    </Alert>
  );
}
