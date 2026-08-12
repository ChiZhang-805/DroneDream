import {
  Building2,
  Crown,
  Eye,
  ShieldCheck,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { EditionLicenseStrip } from "../components/EditionLicenseStrip";
import {
  addOrganizationMember,
  getOrganizationSnapshot,
  OrganizationConsoleError,
  removeOrganizationMember,
  setOrganizationMemberRole,
  type OrganizationMember,
  type OrganizationRole,
  type OrganizationSnapshot,
} from "../features/organization/organizationConsole";
import { useModalFocus } from "../hooks/useModalFocus";

type SiteLocale = "en" | "zh-CN";

const content = {
  en: {
    title: "Organization",
    members: "Members",
    delegated: "Delegated admins",
    plan: "Plan",
    addMember: "Add member",
    email: "Account email",
    role: "Role",
    member: "Member",
    admin: "Admin",
    owner: "Owner",
    account: "Account",
    apps: "Applications",
    created: "Registered",
    lastSignIn: "Last sign-in",
    details: "View details",
    noSignIn: "Never",
    loading: "Loading organization…",
    unavailable: "Organization management is unavailable.",
    close: "Close member details",
    saveRole: "Save role",
    remove: "Remove from organization",
    confirmRemove: "Confirm removal",
    removing: "Removing…",
    saving: "Saving…",
    adding: "Adding…",
    downgrade: "Individual · Free",
  },
  "zh-CN": {
    title: "企业管理",
    members: "成员",
    delegated: "委托管理员",
    plan: "套餐",
    addMember: "添加成员",
    email: "账户邮箱",
    role: "权限",
    member: "成员",
    admin: "管理员",
    owner: "母账号",
    account: "账户",
    apps: "软件授权",
    created: "注册时间",
    lastSignIn: "最近登录",
    details: "查看详情",
    noSignIn: "从未登录",
    loading: "正在载入企业账户…",
    unavailable: "企业管理暂时不可用。",
    close: "关闭成员详情",
    saveRole: "保存权限",
    remove: "移出企业",
    confirmRemove: "确认移出",
    removing: "正在移出…",
    saving: "正在保存…",
    adding: "正在添加…",
    downgrade: "个人版 · Free",
  },
} as const;

function roleLabel(
  role: OrganizationRole,
  copy: typeof content.en | typeof content["zh-CN"],
): string {
  return role === "owner" ? copy.owner : role === "admin" ? copy.admin : copy.member;
}

export function OrganizationPage({
  locale,
  accountId,
}: {
  locale: SiteLocale;
  accountId: string | null;
}) {
  const copy = content[locale];
  const [snapshot, setSnapshot] = useState<OrganizationSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState<"admin" | "member">("member");
  const [selected, setSelected] = useState<OrganizationMember | null>(null);
  const [selectedRole, setSelectedRole] = useState<"admin" | "member">("member");
  const [removalArmed, setRemovalArmed] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const captureDetailsTrigger = useModalFocus({
    open: Boolean(selected),
    dialogRef,
    initialFocusRef: closeRef,
    onClose: () => setSelected(null),
  });
  const date = useMemo(() => new Intl.DateTimeFormat(
    locale === "zh-CN" ? "zh-CN" : "en",
    { year: "numeric", month: "short", day: "numeric" },
  ), [locale]);

  useEffect(() => {
    let active = true;
    setSnapshot(null);
    setSelected(null);
    setError(null);
    if (!accountId) {
      setLoading(false);
      return () => { active = false; };
    }
    setLoading(true);
    void getOrganizationSnapshot()
      .then((result) => {
        if (!active) return;
        setSnapshot(result);
        setError(null);
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [accountId, copy.unavailable]);

  const updateSnapshot = (next: OrganizationSnapshot) => {
    setSnapshot(next);
    setSelected((current) => current
      ? next.members.find((member) => member.id === current.id) ?? null
      : null);
    setError(null);
  };

  const submitMember = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      updateSnapshot(await addOrganizationMember(email.trim(), newRole));
      setEmail("");
      setNewRole("member");
    } catch (reason) {
      setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable);
    } finally {
      setBusy(false);
    }
  };

  const openDetails = (member: OrganizationMember) => {
    captureDetailsTrigger();
    setSelected(member);
    setSelectedRole(member.role === "admin" ? "admin" : "member");
    setRemovalArmed(false);
  };

  const saveRole = async () => {
    if (!selected || busy || selected.role === "owner") return;
    setBusy(true);
    setError(null);
    try {
      updateSnapshot(await setOrganizationMemberRole(selected.id, selectedRole));
    } catch (reason) {
      setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable);
    } finally {
      setBusy(false);
    }
  };

  const removeMember = async () => {
    if (!selected || busy || selected.role === "owner") return;
    if (!removalArmed) {
      setRemovalArmed(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      updateSnapshot(await removeOrganizationMember(selected.id));
      setSelected(null);
    } catch (reason) {
      setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable);
    } finally {
      setBusy(false);
      setRemovalArmed(false);
    }
  };

  if (loading) {
    return <main className="organization-page site-shell" aria-busy="true">{copy.loading}</main>;
  }
  if (!snapshot) {
    return <main className="organization-page site-shell"><p role="alert">{error ?? copy.unavailable}</p></main>;
  }

  const adminCount = snapshot.members.filter((member) => member.role === "admin").length;
  const canManageAdmins = snapshot.actor.can_manage_admins;
  const canManageSelected = selected?.role !== "owner" && (
    canManageAdmins || selected?.role === "member"
  );

  return (
    <main className="organization-page site-shell">
      <header className="organization-heading">
        <div><Building2 aria-hidden="true" /><h1>{snapshot.organization.name}</h1></div>
        <span>{copy.title}</span>
      </header>

      <section className="organization-summary" aria-label={copy.title}>
        <article><Users aria-hidden="true" /><span>{copy.members}</span><strong>{snapshot.members.length}</strong></article>
        <article><ShieldCheck aria-hidden="true" /><span>{copy.delegated}</span><strong>{adminCount} / {snapshot.admin_limit}</strong></article>
        <article><Crown aria-hidden="true" /><span>{copy.plan}</span><strong>Business {snapshot.organization.plan.toUpperCase()}</strong></article>
      </section>

      <section className="organization-members-card">
        <form className="organization-add-member" onSubmit={(event) => void submitMember(event)}>
          <UserPlus aria-hidden="true" />
          <label><span>{copy.email}</span><input type="email" required maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label><span>{copy.role}</span><select value={newRole} onChange={(event) => setNewRole(event.target.value as "admin" | "member")}><option value="member">{copy.member}</option>{canManageAdmins ? <option value="admin">{copy.admin}</option> : null}</select></label>
          <button type="submit" disabled={busy || !email.trim()}>{busy ? copy.adding : copy.addMember}</button>
        </form>
        {error ? <p className="organization-error" role="alert">{error}</p> : null}

        <div className="organization-member-table">
          <table>
            <thead><tr><th>{copy.account}</th><th>{copy.role}</th><th>{copy.plan}</th><th>{copy.apps}</th><th>{copy.created}</th><th>{copy.lastSignIn}</th><th /></tr></thead>
            <tbody>
              {snapshot.members.map((member) => (
                <tr key={member.id}>
                  <td><span className="organization-avatar">{member.display_name.slice(0, 1).toUpperCase()}</span><span><strong>{member.display_name}</strong><small>{member.email}</small></span></td>
                  <td><span className={`organization-role is-${member.role}`}>{roleLabel(member.role, copy)}</span></td>
                  <td><strong>{member.plan.toUpperCase()}</strong></td>
                  <td><EditionLicenseStrip licenses={member.licenses} locale={locale} /></td>
                  <td>{date.format(new Date(member.created_at))}</td>
                  <td>{member.last_sign_in_at ? date.format(new Date(member.last_sign_in_at)) : copy.noSignIn}</td>
                  <td><button type="button" className="organization-details-button" onClick={() => openDetails(member)}><Eye aria-hidden="true" /><span>{copy.details}</span></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected ? (
        <div className="organization-dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSelected(null);
        }}>
          <section ref={dialogRef} className="organization-member-dialog" role="dialog" aria-modal="true" aria-labelledby="organization-member-title" tabIndex={-1}>
            <header><div><span className="organization-avatar is-large">{selected.display_name.slice(0, 1).toUpperCase()}</span><div><h2 id="organization-member-title">{selected.display_name}</h2><span>{selected.email}</span></div></div><button ref={closeRef} type="button" aria-label={copy.close} onClick={() => setSelected(null)}><X aria-hidden="true" /></button></header>
            <div className="organization-member-profile">
              <dl><div><dt>{copy.role}</dt><dd>{roleLabel(selected.role, copy)}</dd></div><div><dt>{copy.plan}</dt><dd>{selected.plan.toUpperCase()}</dd></div><div><dt>{copy.created}</dt><dd>{date.format(new Date(selected.created_at))}</dd></div><div><dt>{copy.lastSignIn}</dt><dd>{selected.last_sign_in_at ? date.format(new Date(selected.last_sign_in_at)) : copy.noSignIn}</dd></div></dl>
              <EditionLicenseStrip licenses={selected.licenses} locale={locale} />
            </div>
            {canManageSelected ? (
              <div className="organization-member-actions">
                {canManageAdmins ? <label><span>{copy.role}</span><select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value as "admin" | "member")}><option value="member">{copy.member}</option><option value="admin">{copy.admin}</option></select></label> : null}
                {canManageAdmins ? <button type="button" onClick={() => void saveRole()} disabled={busy || selectedRole === selected.role}>{busy ? copy.saving : copy.saveRole}</button> : null}
                <button type="button" className="is-danger" onClick={() => void removeMember()} disabled={busy}><Trash2 aria-hidden="true" />{busy ? copy.removing : removalArmed ? copy.confirmRemove : copy.remove}</button>
                {removalArmed ? <small>{copy.downgrade}</small> : null}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </main>
  );
}
