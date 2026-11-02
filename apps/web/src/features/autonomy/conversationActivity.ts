import { useSyncExternalStore } from "react";
import type { BrandEditionId } from "../../brand/edition-brand.generated";

const pending = new Set<string>();
const listeners = new Set<() => void>();
export interface PreparationProgressEvent { stage: string; zh: string; en: string; sequence?: number; elapsed_ms?: number }
const progress = new Map<string, PreparationProgressEvent[]>();
const NO_PROGRESS: PreparationProgressEvent[] = [];

// 功能：
//   将真实阶段摘要绑定到活动会话，结束后的迟到轮询不能复活进度。
// 输入：
//   ownerId：账户；edition：版本；id：会话；event：后端或本机实际阶段事件。
// 输出：
//   无返回值。
export function publishAutonomyProgress(ownerId: string, edition: BrandEditionId, id: string, event: PreparationProgressEvent): void {
  const key = activityKey(ownerId, edition, id);
  if (!pending.has(key)) return;
  progress.set(key, [...(progress.get(key) ?? []), event].slice(-128));
  listeners.forEach((listener) => listener());
}

// 功能：
//   订阅当前会话的真实处理摘要，账户或页面切换时不串用内容。
// 输入：
//   ownerId：账户；edition：版本；id：会话。
// 输出：
//   events：当前请求的有序摘要。
export function useAutonomyProgress(ownerId: string, edition: BrandEditionId, id: string | null): PreparationProgressEvent[] {
  return useSyncExternalStore(subscribe, () => id ? progress.get(activityKey(ownerId, edition, id)) ?? NO_PROGRESS : NO_PROGRESS, () => NO_PROGRESS);
}

// 功能：
//   构建账户、版本与会话绑定的请求键，防止切换页面后重复提交同一会话。
// 输入：
//   ownerId：账户标识；edition：软件版本；id：会话标识。
// 输出：
//   key：进程内请求键。
function activityKey(ownerId: string, edition: BrandEditionId, id: string): string {
  return JSON.stringify([ownerId, edition, id]);
}

// 功能：
//   注册活动状态监听并返回对应的清理函数。
// 输入：
//   listener：订阅回调。
// 输出：
//   unsubscribe：仅移除此回调的函数。
function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

// 功能：
//   独占本会话的一次规划请求；切换页面不解除，进程重启不遗留假忙状态。
// 输入：
//   ownerId：账户标识；edition：软件版本；id：会话标识。
// 输出：
//   release：请求结束时调用的释放函数，已在规划时为 null。
export function acquireAutonomyPlanning(ownerId: string, edition: BrandEditionId, id: string): (() => void) | null {
  const key = activityKey(ownerId, edition, id);
  if (pending.has(key)) return null;
  pending.add(key);
  progress.set(key, [{ stage: "assets", zh: "已收到任务，正在核对地图、无人机和模型连接。当前只准备计划，不执行飞行。", en: "Task received. Checking the map, aircraft and model connection. Preparing a plan only; no flight will start." }]);
  listeners.forEach((listener) => listener());
  let released = false;
  return () => {
    if (released) return;
    released = true;
    pending.delete(key);
    progress.delete(key);
    listeners.forEach((listener) => listener());
  };
}

// 功能：
//   为当前页面订阅会话规划状态，使页面返回后仍显示正在处理。
// 输入：
//   ownerId：账户标识；edition：软件版本；id：会话标识。
// 输出：
//   planning：本会话是否存在进行中的规划请求。
export function useAutonomyPlanning(ownerId: string, edition: BrandEditionId, id: string | null): boolean {
  return useSyncExternalStore(subscribe, () => Boolean(id && pending.has(activityKey(ownerId, edition, id))), () => false);
}
