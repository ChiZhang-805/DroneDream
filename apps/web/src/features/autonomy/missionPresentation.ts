import type { AutonomyWorkspaceState } from "./workspaceStore";

// 功能：
//   从用户正文选择中英文；纯数字或符号沿用对话语言，不读取系统区域设置。
// 输入：
//   text：用户消息；previous：上一条有效用户消息的语言。
// 输出：
//   chinese：本次回复是否使用中文。
export function taskUsesChinese(text: string, previous = false): boolean {
  const body = text.replace(/https?:\/\/\S+/gu, "").trim();
  const han = body.match(/\p{Script=Han}/gu)?.length ?? 0;
  const words = body.match(/[a-zA-Z]+/gu)?.length ?? 0;
  if (!han && !words) return previous;
  return han > 0 && (/^\p{Script=Han}/u.test(body) || han >= Math.max(2, words * 2) || !words);
}

// 功能：
//   按用户消息顺序恢复对话语言，使重新打开会话后仍不受界面语言影响。
// 输入：
//   workspace：会话快照。
// 输出：
//   chinese：最近一条有效用户消息确定的语言。
export function conversationUsesChinese(workspace: AutonomyWorkspaceState): boolean {
  return workspace.mission.messages.filter((item) => item.role === "user")
    .reduce((previous, item) => taskUsesChinese(item.content, previous), taskUsesChinese(workspace.mission.intent));
}

// 功能：
//   在模型命名尚未成功时提供简短活动名，不把整句请求当作标题，也不宣称任务已完成。
// 输入：
//   message：首次用户需求。
// 输出：
//   title：与用户消息语言一致的临时短标题。
export function provisionalMissionTitle(message: string): string {
  const chinese = taskUsesChinese(message);
  if (/取餐|外卖|takeout|food|meal/iu.test(message)) return chinese ? "去取餐点取餐" : "Meal pickup";
  if (/快递|取件|parcel|package/iu.test(message)) return chinese ? "领取快递" : "Parcel pickup";
  if (/巡检|检查|inspect/iu.test(message)) return chinese ? "区域巡检" : "Area inspection";
  const shortMessage = message.trim().replace(/\s+/gu, " ");
  if (shortMessage.length > 0 && shortMessage.length <= 12) return shortMessage;
  return chinese ? "自主飞行任务" : "Autonomous flight task";
}

const ACTION_TITLES: Record<string, [string, string]> = {
  takeoff: ["起飞", "Take off"], navigate: ["飞往目标地点", "Fly to the destination"],
  traverse: ["通过指定通道", "Follow the passage"], pickup: ["取餐或取物", "Collect the item"],
  return: ["返回出发地点", "Return to the starting point"], land: ["安全降落", "Land safely"],
  inspect: ["检查目标区域", "Inspect the target area"], hold: ["保持悬停", "Hold position"],
  resolve: ["确认目标地点", "Identify the destination"], abort: ["终止任务", "Abort the mission"],
  "delivery.precontact-hold": ["接近取物点并悬停", "Approach and hover at pickup"],
  "delivery.confirm-custody": ["确认物品已装载", "Confirm item attachment"],
  "delivery.verify-loaded-stability": ["检查载物后的稳定性", "Check loaded stability"],
};

// 功能：
//   仅转换展示标题，不修改实际任务动作、依赖、风险和执行参数。
// 输入：
//   action：已绑定动作；label：原始标签；chinese：对话语言；intent：用户任务。
// 输出：
//   title：一行可读的步骤说明。
export function missionStepTitle(action: string, label: string, chinese: boolean, intent: string): string {
  const pickupMeal = /取餐|外卖|takeout|food|meal/iu.test(intent);
  if (action === "pickup" && pickupMeal) return chinese ? "领取外卖" : "Collect the meal";
  const title = ACTION_TITLES[action];
  if (title) return title[chinese ? 0 : 1];
  if (label.trim() && !/task node|任务节点/iu.test(label) && taskUsesChinese(label) === chinese) return label;
  return chinese ? "执行任务步骤" : "Perform the task step";
}
