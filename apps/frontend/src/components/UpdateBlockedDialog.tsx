import { AlertTriangle, X } from "lucide-react";

import type { AppUpdateBlock } from "../desktop/updater";
import "./UpdateBlockedDialog.css";

interface UpdateBlockedDialogProps {
  block: AppUpdateBlock | null | undefined;
  locale: "en" | "zh-CN";
  onClose: () => void;
}

export function UpdateBlockedDialog({
  block,
  locale,
  onClose,
}: UpdateBlockedDialogProps) {
  if (!block) return null;
  const chinese = locale === "zh-CN";
  const title = block.kind === "running"
    ? chinese ? "暂时无法更新" : "Update paused"
    : chinese ? "无法确认运行状态" : "Running state unavailable";
  const body = block.kind === "running"
    ? chinese
      ? "检测到仍在运行的仿真或真机任务。请先结束或停止任务，再重新点击更新。"
      : "A simulation or real-device task is still running. Finish or stop it, then start the update again."
    : chinese
      ? "暂时无法可靠确认是否存在运行中的任务。为避免中断实验，本次更新没有开始。"
      : "DroneDream could not safely verify active work, so the update did not start."
  return (
    <div className="update-blocked-backdrop" role="presentation">
      <section
        className="update-blocked-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="update-blocked-title"
      >
        <header>
          <AlertTriangle aria-hidden="true" />
          <h2 id="update-blocked-title">{title}</h2>
          <button type="button" onClick={onClose} aria-label={chinese ? "关闭" : "Close"}>
            <X aria-hidden="true" />
          </button>
        </header>
        <p>{body}</p>
        {block.runningJobs.length > 0 ? (
          <ul>{block.runningJobs.map((job) => <li key={job.id}>{job.name}</li>)}</ul>
        ) : null}
        <button type="button" className="update-blocked-confirm" onClick={onClose}>
          {chinese ? "知道了" : "OK"}
        </button>
      </section>
    </div>
  );
}
