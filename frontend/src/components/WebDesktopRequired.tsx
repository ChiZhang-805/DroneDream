import { Alert } from "./Alert";
import { useI18n } from "../i18n/I18nProvider";
import { fallbackRelease } from "../site/release";

interface WebDesktopRequiredProps {
  compact?: boolean;
}

export function WebDesktopRequired({ compact = false }: WebDesktopRequiredProps) {
  const { t } = useI18n();

  return (
    <Alert tone="info" title={t("webConsole.previewTitle")}>
      <p>{t("webConsole.desktopRequired")}</p>
      <a
        className={`btn btn-primary${compact ? " btn-small" : ""}`}
        href={fallbackRelease.downloadUrl}
        download={fallbackRelease.fileName}
      >
        {t("webConsole.downloadDesktop", { version: fallbackRelease.version })}
      </a>
    </Alert>
  );
}
