import { SectionCard } from "./SectionCard";
import { Alert } from "./Alert";
import { useI18n } from "../i18n/I18nProvider";

interface GazeboLivePanelProps {
  viewerUrl?: string;
}

function normalizeNoVncViewerUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) {
    return "";
  }

  try {
    const url = new URL(trimmed);
    url.searchParams.set("autoconnect", "1");
    url.searchParams.set("resize", "scale");
    url.searchParams.set("view_clip", "0");
    return url.toString();
  } catch {
    return trimmed;
  }
}

export function GazeboLivePanel({ viewerUrl }: GazeboLivePanelProps) {
  const { t } = useI18n();
  const resolvedUrl =
    viewerUrl ?? (import.meta.env.VITE_GAZEBO_VIEWER_URL as string | undefined);
  const normalizedUrl = normalizeNoVncViewerUrl(resolvedUrl ?? "");

  if (!normalizedUrl) {
    return null;
  }

  return (
    <SectionCard
      title={t("gazeboLive.title")}
      description={t("gazeboLive.description")}
    >
      <div className="stack-sm">
        <Alert tone="warning">
          {t("gazeboLive.warning")}
        </Alert>
        <div className="gazebo-live-frame-wrap">
          <iframe
            title={t("gazeboLive.frameTitle")}
            src={normalizedUrl}
            className="gazebo-live-iframe"
            loading="lazy"
            referrerPolicy="no-referrer"
            scrolling="no"
          />
        </div>
      </div>
    </SectionCard>
  );
}
