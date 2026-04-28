import { SectionCard } from "./SectionCard";
import { Alert } from "./Alert";

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
  const resolvedUrl =
    viewerUrl ?? (import.meta.env.VITE_GAZEBO_VIEWER_URL as string | undefined);
  const normalizedUrl = normalizeNoVncViewerUrl(resolvedUrl ?? "");

  if (!normalizedUrl) {
    return null;
  }

  return (
    <SectionCard
      title="Gazebo live view"
      description="Optional noVNC embedding for Runpod demo/debug mode."
    >
      <div className="stack-sm">
        <Alert tone="warning">
          Gazebo live view is optional and intended for Runpod demo/debug mode.
          Normal optimization remains headless.
        </Alert>
        <div className="gazebo-live-frame-wrap">
          <iframe
            title="Gazebo live view"
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
