import { SectionCard } from "./SectionCard";
import { Alert } from "./Alert";

interface GazeboLivePanelProps {
  viewerUrl?: string;
}

export function GazeboLivePanel({ viewerUrl }: GazeboLivePanelProps) {
  const resolvedUrl =
    viewerUrl ?? (import.meta.env.VITE_GAZEBO_VIEWER_URL as string | undefined);
  const trimmedUrl = resolvedUrl?.trim() ?? "";

  if (!trimmedUrl) {
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
        <iframe
          title="Gazebo live view"
          src={trimmedUrl}
          className="gazebo-live-iframe"
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      </div>
    </SectionCard>
  );
}
