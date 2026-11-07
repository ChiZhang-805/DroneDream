import { Download } from "lucide-react";

import type { AppUpdateStatus } from "../desktop/updater";
import "./UpdateProgressDialog.css";

interface UpdateProgressDialogProps {
  locale: "en" | "zh-CN";
  progress: number | null;
  status: AppUpdateStatus;
}

const ACTIVE_UPDATE_STATES = new Set<AppUpdateStatus>([
  "downloading",
  "installing",
  "reconcilingEngine",
  "installingComponents",
  "upgradingRuntime",
]);

export function UpdateProgressDialog({
  locale,
  progress,
  status,
}: UpdateProgressDialogProps) {
  if (!ACTIVE_UPDATE_STATES.has(status)) return null;
  const percent = progress === null
    ? null
    : Math.max(0, Math.min(100, Math.round(progress)));
  const title = locale === "zh-CN" ? "正在更新 DroneDream" : "Updating DroneDream";
  return (
    <div className="update-progress-backdrop" role="presentation">
      <section
        className="update-progress-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="update-progress-title"
        aria-busy="true"
      >
        <header>
          <span className="update-progress-icon" aria-hidden="true">
            <Download strokeWidth={2} />
          </span>
          <h2 id="update-progress-title">{title}</h2>
        </header>
        <div className="update-progress-track" aria-hidden="true">
          <span
            className={percent === null ? "is-indeterminate" : ""}
            style={percent === null ? undefined : { width: `${percent}%` }}
          />
        </div>
        <progress
          className="update-progress-native"
          max={100}
          value={percent ?? undefined}
          aria-label={title}
        />
        <strong className="update-progress-value">{percent === null ? "…" : `${percent}%`}</strong>
      </section>
    </div>
  );
}
