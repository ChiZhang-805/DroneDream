import { MapPinned } from "lucide-react";
import type { AutonomyMapRefinementState } from "./mapRefinement";

export function MapRefinementNotice({ state, chinese, disabled, onContinue, onReviewMap }: {
  state: AutonomyMapRefinementState;
  chinese: boolean;
  disabled: boolean;
  onContinue: () => void;
  onReviewMap: () => void;
}) {
  const needsMap = state.nextAction === "supply-registered-map-view";
  return (
    <aside className="autonomy-map-refinement" role="status" data-state="awaiting-observation">
      <div className="autonomy-map-refinement-heading">
        <MapPinned aria-hidden="true" />
        <strong>{chinese ? "需要补充地图细节" : "More map detail needed"}</strong>
      </div>
      <p>{needsMap
        ? chinese
          ? "请在地图页面补充与当前地图坐标对齐的图像来源，然后继续规划。"
          : "Add an image source aligned with this map’s coordinates in Maps, then continue planning."
        : chinese
          ? "请检查地图中尚未确认的连接路径。补充更清楚的地图来源，或选择支持图像分析的模型后，继续当前任务。"
          : "Review the connecting paths that are still unclear. Add a clearer map source or select a model with visual analysis, then continue this task."}</p>
      <p className="autonomy-map-refinement-summary">{chinese
        ? `已检查 ${state.observationCount} 份观察记录${state.requestCount ? `，还有 ${state.requestCount} 处区域需要复查` : ""}。当前正在等待补充信息。`
        : `${state.observationCount} review ${state.observationCount === 1 ? "record" : "records"}${state.requestCount ? `; ${state.requestCount} ${state.requestCount === 1 ? "area needs" : "areas need"} more detail` : ""}. Waiting for additional information.`}</p>
      {state.message ? <details><summary>{chinese ? "查看复查说明" : "Review details"}</summary><p>{state.message}</p></details> : null}
      <div className="autonomy-map-refinement-actions">
        <button type="button" className="btn" onClick={onReviewMap} disabled={disabled}>{chinese ? "查看地图" : "Review map"}</button>
        <button type="button" className="btn primary" onClick={onContinue} disabled={disabled}>{chinese ? "继续规划" : "Continue planning"}</button>
      </div>
    </aside>
  );
}
