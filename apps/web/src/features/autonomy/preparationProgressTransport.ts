import { getAgentCorePreparationProgress } from "./agentCore";
import type { PreparationProgressEvent } from "./conversationActivity";

// 功能：
//   串行轮询真实进度，按序号去重；结束后忽略在途回包，不取消业务请求。
// 输入：
//   threadId：会话；requestId：请求；publish：摘要接收器。
// 输出：
//   stop：停止后续轮询的函数。
export function followPreparationProgress(threadId: string, requestId: string, publish: (event: PreparationProgressEvent) => void): () => void {
  let active = true;
  let cursor = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let failures = 0;
  const poll = async () => {
    try {
      const result = await getAgentCorePreparationProgress(threadId, requestId, cursor);
      if (!active) return;
      for (const event of result.events) {
        if (!Number.isSafeInteger(event.sequence) || event.sequence! <= cursor || typeof event.stage !== "string" || typeof event.zh !== "string" || typeof event.en !== "string") continue;
        cursor = event.sequence!;
        publish(event);
      }
      failures = 0;
      if (["completed", "failed"].includes(result.state)) return;
    } catch {
      if (!active) return;
      failures += 1;
      if (failures === 3) publish({ stage: "connection", zh: "暂时无法获取最新进度，任务请求仍在等待返回。不会将连接中断显示为处理成功。", en: "Latest progress is temporarily unavailable; the task request is still pending. A connection failure is not a successful result." });
    }
    if (active) timer = setTimeout(() => void poll(), Math.min(1000 * Math.max(1, failures), 5000));
  };
  void poll();
  return () => { active = false; if (timer) clearTimeout(timer); };
}
