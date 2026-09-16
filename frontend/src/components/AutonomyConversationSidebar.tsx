import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import type { BrandEditionId } from "../brand/edition-brand.generated";
import { AUTONOMY_CONVERSATIONS_CHANGED, autonomyConversationPath, listAutonomyConversations, preserveLegacyAutonomyConversation } from "../features/autonomy/conversationStore";

// 功能：
//   展示独立自主任务会话入口，首条消息保存后立即更新，切换账户时隔离列表。
// 输入：
//   ownerId：账户标识；edition：软件版本；locale：界面语言；onNavigate：导航后回调。
// 输出：
//   sidebar：可重新进入历史会话的侧边栏。
export function AutonomyConversationSidebar({ ownerId, edition, locale, onNavigate }: { ownerId: string; edition: BrandEditionId; locale: string; onNavigate?: () => void }) {
  const location = useLocation();
  const [, setRevision] = useState(0);
  const [error, setError] = useState(false);
  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1);
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (detail?.ownerId === ownerId && detail?.edition === edition) refresh();
    };
    window.addEventListener(AUTONOMY_CONVERSATIONS_CHANGED, onChange);
    window.addEventListener("storage", refresh);
    try { preserveLegacyAutonomyConversation(ownerId, edition); setError(false); refresh(); } catch { setError(true); }
    return () => {
      window.removeEventListener(AUTONOMY_CONVERSATIONS_CHANGED, onChange);
      window.removeEventListener("storage", refresh);
    };
  }, [ownerId, edition]);
  // render 时使用当前 owner，避免账户切换后短暂呈现上一账户标题。
  let conversations: ReturnType<typeof listAutonomyConversations> = [];
  let unavailable = error;
  try { conversations = listAutonomyConversations(ownerId, edition); } catch { unavailable = true; }
  const heading = locale === "zh-CN" ? "对话" : "Conversations";
  return (
    <section className="app-workspaces app-conversations" aria-label={heading}>
      <header className="app-workspaces-header"><span>{heading}</span></header>
      <div className="app-workspace-list">
        {conversations.map((conversation) => {
          const path = autonomyConversationPath(conversation.id);
          return (
            <div key={conversation.id} className={`app-workspace-row${location.pathname === path ? " active" : ""}`}>
              <NavLink to={path} title={conversation.title} onClick={onNavigate}>
                <span className="app-workspace-label"><strong>{conversation.title}</strong></span>
              </NavLink>
            </div>
          );
        })}
      </div>
      {unavailable ? <p role="alert">{locale === "zh-CN" ? "无法读取或保存本机会话。" : "Local conversations could not be read or saved."}</p> : null}
    </section>
  );
}
