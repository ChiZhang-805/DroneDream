import type { BrandEditionId } from "../../brand/edition-brand.generated";
import { provisionalMissionTitle } from "./missionPresentation";
import { defaultAutonomyWorkspace, loadAutonomyWorkspace, normalizeAutonomyWorkspace, type AutonomyWorkspaceState } from "./workspaceStore";

const PREFIX = "dronedream:autonomy-conversation:v1";
export const AUTONOMY_CONVERSATIONS_CHANGED = "dronedream:autonomy-conversations-changed";
type ConversationStorage = Pick<Storage, "getItem" | "setItem" | "key" | "length">;

// 功能：
//   独立读取会话管理信息，防止迟到的规划快照覆盖置顶、标题和删除状态。
// 输入：
//   ownerId：账户；edition：版本；id：会话；storage：存储接口。
// 输出：
//   metadata：会话管理信息；损坏时抛错，避免复活已删除会话。
function conversationMetadata(ownerId: string, edition: BrandEditionId, id: string, storage: ConversationStorage) {
  const raw = storage.getItem(`${conversationKey(ownerId, edition, id)}:metadata`);
  const parsed = raw ? JSON.parse(raw) : {};
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("CONVERSATION_METADATA_INVALID");
  return { pinned: parsed.pinned === true, deleted: parsed.deleted === true, title: typeof parsed.title === "string" ? parsed.title : "" };
}

// 功能：
//   持久化置顶、模型短标题或删除标记；删除后拒绝其他更新，保留运行证据。
// 输入：
//   ownerId：账户；edition：版本；id：会话；patch：管理操作；storage：存储接口。
// 输出：
//   无返回值。
export function updateAutonomyConversation(ownerId: string, edition: BrandEditionId, id: string, patch: { pinned?: boolean; title?: string; deleted?: true }, storage: ConversationStorage = window.localStorage): void {
  const current = conversationMetadata(ownerId, edition, id, storage);
  if (current.deleted) return;
  if (!loadAutonomyConversation(ownerId, edition, id, storage)) throw new Error("CONVERSATION_NOT_FOUND");
  const title = patch.title === undefined ? current.title : patch.title.replace(/[\u0000-\u001f\u007f]/gu, " ").replace(/\s+/gu, " ").trim();
  if (patch.title !== undefined && (!title || Array.from(title).length > 32)) throw new Error("CONVERSATION_TITLE_INVALID");
  storage.setItem(`${conversationKey(ownerId, edition, id)}:metadata`, JSON.stringify({ ...current, ...patch, title }));
  window.dispatchEvent(new CustomEvent(AUTONOMY_CONVERSATIONS_CHANGED, { detail: { ownerId, edition, id } }));
}

// 功能：
//   在异步返回和旧草稿迁移前检查删除标记。
// 输入：
//   ownerId：账户；edition：版本；id：会话；storage：存储接口。
// 输出：
//   deleted：会话是否已删除。
export function isAutonomyConversationDeleted(ownerId: string, edition: BrandEditionId, id: string, storage: ConversationStorage = window.localStorage): boolean {
  return conversationMetadata(ownerId, edition, id, storage).deleted;
}

// 功能：
//   隔离账户、软件版本与会话的本机存储；不保存登录凭据或模型密钥。
// 输入：
//   ownerId：账户标识；edition：软件版本；id：可选会话标识。
// 输出：
//   storageKey：会话键或该账户的会话键前缀。
function conversationKey(ownerId: string, edition: BrandEditionId, id = ""): string {
  return `${PREFIX}:${encodeURIComponent(ownerId || "local")}:${edition}:${encodeURIComponent(id)}`;
}

// 功能：
//   保留当前地图、无人机和模型选择，清空上一次会话的消息、计划与执行绑定。
// 输入：
//   previous：当前工作区。
// 输出：
//   workspace：未创建会话的空白工作区。
export function newAutonomyConversation(previous: AutonomyWorkspaceState): AutonomyWorkspaceState {
  return {
    ...previous,
    mission: {
      ...defaultAutonomyWorkspace().mission,
      id: crypto.randomUUID(),
      intent: "",
      planningModel: previous.mission.planningModel,
      aircraftProfileId: previous.aircraft.id,
      mapPackId: previous.mapPack.id,
    },
  };
}

// 功能：
//   写入一个独立会话并通知侧边栏；存储失败直接抛出，不伪装成已保存。
// 输入：
//   ownerId：账户标识；edition：软件版本；workspace：会话快照；storage：存储接口。
// 输出：
//   saved：规范化后的已保存会话快照。
export function saveAutonomyConversation(ownerId: string, edition: BrandEditionId, workspace: AutonomyWorkspaceState, storage: ConversationStorage = window.localStorage): AutonomyWorkspaceState {
  const saved = normalizeAutonomyWorkspace(workspace);
  const id = saved.mission.conversationId;
  if (!id || (!saved.mission.messages.length && !saved.mission.compiledPlan)) throw new Error("AUTONOMY_CONVERSATION_EMPTY");
  if (isAutonomyConversationDeleted(ownerId, edition, id, storage)) return saved;
  // 每份会话单独写入，异步返回只更新其自身，不覆盖另一个会话的记录。
  storage.setItem(conversationKey(ownerId, edition, id), JSON.stringify(saved));
  window.dispatchEvent(new CustomEvent(AUTONOMY_CONVERSATIONS_CHANGED, { detail: { ownerId, edition, id } }));
  return saved;
}

// 功能：
//   读取指定账户的独立会话，拒绝损坏或标识不匹配的记录。
// 输入：
//   ownerId：账户标识；edition：软件版本；id：会话标识；storage：存储接口。
// 输出：
//   workspace：会话快照，缺失或无效时为 null。
export function loadAutonomyConversation(ownerId: string, edition: BrandEditionId, id: string, storage: ConversationStorage = window.localStorage): AutonomyWorkspaceState | null {
  try {
    if (isAutonomyConversationDeleted(ownerId, edition, id, storage)) return null;
    const raw = storage.getItem(conversationKey(ownerId, edition, id));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const workspace = normalizeAutonomyWorkspace(parsed);
    return workspace.mission.conversationId === id
      && (workspace.mission.messages.length > 0 || workspace.mission.compiledPlan)
      ? workspace : null;
  } catch { return null; }
}

// 功能：
//   将原先唯一的任务草稿归入会话列表，不删除原记录、不覆盖已存在的会话。
// 输入：
//   ownerId：账户标识；edition：软件版本；storage：存储接口。
// 输出：
//   无返回值。
export function preserveLegacyAutonomyConversation(ownerId: string, edition: BrandEditionId, storage: ConversationStorage = window.localStorage): void {
  const workspace = loadAutonomyWorkspace(ownerId, edition, storage);
  if (!workspace.mission.messages.length && !workspace.mission.compiledPlan) return;
  const id = workspace.mission.conversationId || "legacy-primary";
  // 损坏的新记录也不静默覆盖，保留原始内容供恢复。
  if (storage.getItem(conversationKey(ownerId, edition, id)) !== null) return;
  saveAutonomyConversation(ownerId, edition, { ...workspace, mission: { ...workspace.mission, conversationId: id } }, storage);
}

// 功能：
//   列出本账户、本版本的有效会话，按最近修改时间排序。
// 输入：
//   ownerId：账户标识；edition：软件版本；storage：存储接口。
// 输出：
//   conversations：包含标识、标题和更新时间的会话摘要列表。
export function listAutonomyConversations(ownerId: string, edition: BrandEditionId, storage: ConversationStorage = window.localStorage) {
  const conversations: Array<{ id: string; title: string; updatedAt: string; pinned: boolean; generatedTitle: boolean }> = [];
  const prefix = conversationKey(ownerId, edition);
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (!key?.startsWith(prefix) || key.endsWith(":metadata")) continue;
    let id: string;
    try { id = decodeURIComponent(key.slice(prefix.length)); } catch { continue; }
    const workspace = loadAutonomyConversation(ownerId, edition, id, storage);
    if (!workspace) continue;
    const firstMessage = workspace.mission.messages.find((message) => message.role === "user");
    const metadata = conversationMetadata(ownerId, edition, id, storage);
    conversations.push({ id, title: metadata.title || provisionalMissionTitle(firstMessage?.content || workspace.mission.intent), updatedAt: workspace.mission.updatedAt, pinned: metadata.pinned, generatedTitle: Boolean(metadata.title) });
  }
  return conversations.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.updatedAt.localeCompare(a.updatedAt) || a.id.localeCompare(b.id));
}

// 功能：
//   为会话生成独立页面地址。
// 输入：
//   id：会话标识。
// 输出：
//   path：不与 Chatbot 新对话入口混用的路由地址。
export function autonomyConversationPath(id: string): string {
  return `/autonomy/conversations/${encodeURIComponent(id)}`;
}

// 功能：
//   识别独立会话页面，忽略地图、实时画面等其他页面。
// 输入：
//   pathname：当前路由路径。
// 输出：
//   id：会话标识，非会话页或无效编码时为 null。
export function autonomyConversationId(pathname: string): string | null {
  const match = /^\/autonomy\/conversations\/([^/]+)(?:\/live)?\/?$/u.exec(pathname);
  try { return match ? decodeURIComponent(match[1]) : null; } catch { return null; }
}
