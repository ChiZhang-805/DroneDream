import { useSyncExternalStore } from "react";
import type { BrandEditionId } from "../../brand/edition-brand.generated";

const pending = new Set<string>();
const listeners = new Set<() => void>();

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
  listeners.forEach((listener) => listener());
  let released = false;
  return () => {
    if (released) return;
    released = true;
    pending.delete(key);
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
