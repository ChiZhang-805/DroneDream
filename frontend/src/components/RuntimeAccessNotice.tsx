import { Link } from "react-router-dom";

import { useDesktopRuntimeAccess } from "../desktop/access";
import { useI18n } from "../i18n/I18nProvider";
import { Alert } from "./Alert";

export function RuntimeAccessNotice({
  page,
}: {
  page: "dashboard" | "history" | "ece498";
}) {
  const runtimeAccess = useDesktopRuntimeAccess();
  const { t } = useI18n();
  const checking = runtimeAccess.status === "checking";

  return (
    <Alert
      tone={checking ? "info" : "warning"}
      title={checking
        ? t("runtimeGate.checkingTitle")
        : t("runtimeGate.previewTitle")}
    >
      <p className="runtime-access-copy">
        {checking
          ? t("runtimeGate.checkingBody")
          : page === "dashboard"
            ? t("runtimeGate.dashboardPreviewBody")
            : page === "history"
              ? t("runtimeGate.historyPreviewBody")
              : t("runtimeGate.ece498PreviewBody")}
      </p>
      {!checking ? (
        <Link className="btn btn-primary" to="/desktop/setup">
          {t("runtimeGate.openSetup")}
        </Link>
      ) : null}
    </Alert>
  );
}
