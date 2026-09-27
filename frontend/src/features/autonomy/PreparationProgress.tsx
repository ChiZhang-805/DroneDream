import { useEffect, useState } from "react";
import type { PreparationProgressEvent } from "./conversationActivity";
import "./PreparationProgress.css";

const TITLES: Record<string, [string, string]> = {
  assets: ["正在读取地图与无人机", "Reading map and aircraft"],
  interpretation: ["正在解析资产知识", "Interpreting asset knowledge"],
  naming: ["正在整理任务名称", "Naming the conversation"],
  intent: ["正在理解任务", "Understanding the task"],
  intent_review: ["正在复核任务要求", "Reviewing task requirements"],
  tools: ["正在查询与计算", "Querying and calculating"],
  decomposition: ["正在分解任务步骤", "Decomposing task steps"],
  route: ["正在规划路线", "Planning the route"],
  clearance: ["正在检查三维通行间隙", "Checking 3D route clearance"],
  verification: ["正在校验计划", "Validating the plan"],
  ready: ["正在整理回复", "Preparing the reply"],
  failed: ["正在处理本次结果", "Handling the result"],
  connection: ["正在等待进度连接", "Waiting for progress connection"],
};

// 功能：
//   同一位置切换真实阶段标题，并流式呈现该阶段公开摘要；不延迟最终回复。
// 输入：
//   events：已发生的处理事件；chinese：界面语言。
// 输出：
//   panel：临时进度面板。
export function PreparationProgress({ events, chinese }: { events: PreparationProgressEvent[]; chinese: boolean }) {
  const last = events.at(-1);
  const stage = last?.stage ?? "assets";
  let start = events.length - 1;
  while (start > 0 && events[start - 1].stage === stage) start -= 1;
  const text = events.slice(Math.max(0, start)).map((event) => chinese ? event.zh : event.en).join("\n\n");
  const stageKey = `${stage}:${start}:${chinese}`;
  const [display, setDisplay] = useState({ key: stageKey, count: 0 });
  const characters = Array.from(text);
  const count = display.key === stageKey ? display.count : 0;
  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) { setDisplay({ key: stageKey, count: Array.from(text).length }); return; }
    const length = Array.from(text).length;
    const timer = window.setInterval(() => setDisplay((current) => {
      const next = Math.min(length, (current.key === stageKey ? current.count : 0) + 3);
      if (next === length) window.clearInterval(timer);
      return { key: stageKey, count: next };
    }), 25);
    return () => window.clearInterval(timer);
  }, [stageKey, text]);
  const title = (TITLES[stage] ?? ["正在处理任务", "Processing the task"])[chinese ? 0 : 1];
  return <div className="autonomy-preparation-progress">
    <h3 key={stageKey} aria-live="polite">{title}</h3>
    <div className="autonomy-preparation-detail" aria-hidden="true">{characters.slice(0, count).join("")}<span className="autonomy-progress-cursor" /></div>
    <span className="autonomy-progress-accessible" role="status">{text}</span>
  </div>;
}
