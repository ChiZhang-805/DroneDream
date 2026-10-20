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
  assignOrganizationDepartment,
  createOrganization,
  createOrganizationDepartment,
  getOrganizationAccess,
  getOrganizationSnapshot,
  OrganizationConsoleError,
  removeOrganizationMember,
  requestOrganizationJoin,
  reviewOrganizationJoin,
  searchOrganizations,
  setOrganizationMemberPlan,
  setOrganizationMemberRole,
  setOrganizationPlan,
  transferOrganizationFounder,
  type OrganizationMember,
  type OrganizationPlan,
  type OrganizationRole,
  type OrganizationSnapshot,
  type OrganizationStructure,
  type OrganizationSearchResult,
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
    owner: "Founder",
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
    createTitle: "Create your Business organization",
    createIntro: "Business starts with a shared identity and a clear management structure.",
    name: "Organization name",
    description: "Organization description",
    next: "Continue",
    back: "Back",
    create: "Create organization",
    architecture: "Choose the organization structure",
    flat: "Unified management",
    flatHelp: "Founder and administrators manage members across the organization.",
    single: "Departments · one manager",
    singleHelp: "Each department has one administrator who manages only that department.",
    dual: "Departments · two managers",
    dualHelp: "Each department can have two administrators who manage only that department.",
    founderPlan: "Founder Business plan",
    code: "Organization code",
    transfer: "Transfer Founder role",
    confirmTransfer: "Confirm transfer",
    transferHelp: "The selected administrator becomes Founder. You become an administrator.",
    memberPlan: "Member Business plan",
    savePlan: "Save plan",
    choosePath: "How would you like to use Business?",
    createNew: "Create a new organization",
    joinExisting: "Join an existing organization",
    searchOrganization: "Search by organization name or DD code",
    search: "Search",
    requestJoin: "Request to join",
    requestSent: "Join request sent",
    joinRequests: "Join requests",
    approve: "Approve",
    reject: "Reject",
    departments: "Departments",
    departmentName: "Department name",
    addDepartment: "Add department",
    assignDepartment: "Assign department",
    unassigned: "Not assigned",
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
    owner: "创始人",
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
    createTitle: "创建 Business 组织",
    createIntro: "先建立共享身份，再选择清晰的组织管理架构。",
    name: "组织名称",
    description: "组织简介",
    next: "继续",
    back: "返回",
    create: "创建组织",
    architecture: "选择组织架构",
    flat: "统一管理",
    flatHelp: "创始人和管理员可管理全组织普通成员。",
    single: "部门制 · 单负责人",
    singleHelp: "每个部门由一名管理员负责，且只能管理本部门成员。",
    dual: "部门制 · 双负责人",
    dualHelp: "每个部门可由两名管理员负责，且只能管理本部门成员。",
    founderPlan: "创始人 Business 套餐",
    code: "组织代号",
    transfer: "转交创始人权限",
    confirmTransfer: "确认转交",
    transferHelp: "所选管理员将成为创始人，你会自动降级为管理员。",
    memberPlan: "成员 Business 套餐",
    savePlan: "保存套餐",
    choosePath: "你希望如何开始使用 Business？",
    createNew: "创建新组织",
    joinExisting: "加入已有组织",
    searchOrganization: "按组织名称或 DD 代号搜索",
    search: "搜索",
    requestJoin: "申请加入",
    requestSent: "加入申请已发送",
    joinRequests: "加入申请",
    approve: "批准",
    reject: "拒绝",
    departments: "部门",
    departmentName: "部门名称",
    addDepartment: "添加部门",
    assignDepartment: "分配部门",
    unassigned: "尚未分配",
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
  const requestedPlan = (() => {
    const value = new URLSearchParams(window.location.search).get("plan");
    return value === "free" || value === "plus" || value === "pro" ? value : "pro";
  })();
  const [snapshot, setSnapshot] = useState<OrganizationSnapshot | null>(null);
  const [canCreate, setCanCreate] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState<"admin" | "member">("member");
  const [selected, setSelected] = useState<OrganizationMember | null>(null);
  const [selectedRole, setSelectedRole] = useState<"admin" | "member">("member");
  const [removalArmed, setRemovalArmed] = useState(false);
  const [transferArmed, setTransferArmed] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<OrganizationPlan>("free");
  const [wizardStep, setWizardStep] = useState<1 | 2>(1);
  const [organizationName, setOrganizationName] = useState("");
  const [organizationDescription, setOrganizationDescription] = useState("");
  const [organizationStructure, setOrganizationStructure] = useState<OrganizationStructure>("flat");
  const [founderPlan, setFounderPlan] = useState<OrganizationPlan>(requestedPlan);
  const [departmentName, setDepartmentName] = useState("");
  const [onboardingMode, setOnboardingMode] = useState<"choose" | "create" | "join">("choose");
  const [organizationQuery, setOrganizationQuery] = useState("");
  const [organizationResults, setOrganizationResults] = useState<OrganizationSearchResult[]>([]);
  const [joinPlan, setJoinPlan] = useState<OrganizationPlan>(requestedPlan);
  const [joinRequested, setJoinRequested] = useState(false);
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
    void getOrganizationAccess()
      .then(async (access) => {
        if (!access.organization_id) {
          if (active) setCanCreate(true);
          return null;
        }
        if (!access.authorized) throw new OrganizationConsoleError("ORGANIZATION_PERMISSION_REQUIRED", copy.unavailable, 403);
        return await getOrganizationSnapshot();
      })
      .then((result) => {
        if (!active) return;
        if (result) setSnapshot(result);
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
    setSelectedPlan(member.plan);
    setRemovalArmed(false);
    setTransferArmed(false);
  };

  const savePlan = async () => {
    if (!selected || busy || selected.role === "owner") return;
    setBusy(true);
    try { updateSnapshot(await setOrganizationMemberPlan(selected.id, selectedPlan)); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
  };

  const transferFounder = async () => {
    if (!selected || selected.role !== "admin" || busy) return;
    if (!transferArmed) { setTransferArmed(true); return; }
    setBusy(true);
    try { updateSnapshot(await transferOrganizationFounder(selected.id)); setSelected(null); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); setTransferArmed(false); }
  };

  const submitOrganization = async () => {
    if (!organizationName.trim() || busy) return;
    setBusy(true);
    try {
      updateSnapshot(await createOrganization({
        name: organizationName.trim(), description: organizationDescription.trim(),
        structure: organizationStructure, plan: founderPlan,
      }));
      setCanCreate(false);
    } catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
  };

  const changeFounderPlan = async (plan: OrganizationPlan) => {
    if (busy || !snapshot || snapshot.actor.role !== "owner") return;
    setBusy(true);
    try { updateSnapshot(await setOrganizationPlan(plan)); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
  };

  const addDepartment = async () => {
    if (!departmentName.trim() || busy) return;
    setBusy(true);
    try { updateSnapshot(await createOrganizationDepartment(departmentName.trim())); setDepartmentName(""); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
  };

  const assignDepartment = async (departmentId: string) => {
    if (!selected || !departmentId || busy) return;
    setBusy(true);
    try { updateSnapshot(await assignOrganizationDepartment(departmentId, selected.id)); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
  };

  const searchForOrganizations = async () => {
    if (organizationQuery.trim().length < 2 || busy) return;
    setBusy(true);
    try { setOrganizationResults(await searchOrganizations(organizationQuery.trim())); setError(null); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
  };

  const requestJoin = async (organization: OrganizationSearchResult) => {
    if (busy) return;
    setBusy(true);
    try { await requestOrganizationJoin(organization.public_code, joinPlan); setJoinRequested(true); setError(null); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
  };

  const reviewJoin = async (requestId: string, approved: boolean) => {
    if (busy) return;
    setBusy(true);
    try { updateSnapshot(await reviewOrganizationJoin(requestId, approved)); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
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
  if (!snapshot && canCreate) {
    return <main className="organization-page site-shell"><section className="organization-onboarding" aria-labelledby="organization-create-title">
      <header><Building2 aria-hidden="true" /><div><h1 id="organization-create-title">{onboardingMode === "choose" ? copy.choosePath : onboardingMode === "join" ? copy.joinExisting : copy.createTitle}</h1><p>{copy.createIntro}</p></div>{onboardingMode === "create" ? <span>{wizardStep} / 2</span> : null}</header>
      {onboardingMode === "choose" ? <div className="organization-path-options"><button type="button" onClick={() => setOnboardingMode("create")}><Crown aria-hidden="true" /><strong>{copy.createNew}</strong></button><button type="button" onClick={() => setOnboardingMode("join")}><Users aria-hidden="true" /><strong>{copy.joinExisting}</strong></button></div> : onboardingMode === "join" ? <div className="organization-wizard-fields"><label><span>{copy.searchOrganization}</span><input autoFocus value={organizationQuery} onChange={(event) => setOrganizationQuery(event.target.value)} /></label><label><span>{copy.memberPlan}</span><select value={joinPlan} onChange={(event) => setJoinPlan(event.target.value as OrganizationPlan)}><option value="free">Business Free</option><option value="plus">Business Plus</option><option value="pro">Business Pro</option></select></label><div className="organization-wizard-actions"><button type="button" className="is-secondary" onClick={() => setOnboardingMode("choose")}>{copy.back}</button><button type="button" onClick={() => void searchForOrganizations()}>{copy.search}</button></div>{joinRequested ? <p>{copy.requestSent}</p> : organizationResults.map((organization) => <article className="organization-search-result" key={organization.public_code}><div><strong>{organization.name}</strong><span>{organization.public_code} · Business {organization.plan.toUpperCase()}</span><small>{organization.description}</small></div><button type="button" disabled={(organization.plan === "free" && joinPlan !== "free") || (organization.plan === "plus" && joinPlan === "pro")} onClick={() => void requestJoin(organization)}>{copy.requestJoin}</button></article>)}</div> : wizardStep === 1 ? <div className="organization-wizard-fields">
        <label><span>{copy.name}</span><input autoFocus maxLength={120} value={organizationName} onChange={(event) => setOrganizationName(event.target.value)} /></label>
        <label><span>{copy.description}</span><textarea maxLength={500} rows={4} value={organizationDescription} onChange={(event) => setOrganizationDescription(event.target.value)} /></label>
        <button type="button" disabled={!organizationName.trim()} onClick={() => setWizardStep(2)}>{copy.next}</button>
      </div> : <div className="organization-wizard-fields">
        <fieldset><legend>{copy.architecture}</legend>{([
          ["flat", copy.flat, copy.flatHelp], ["department_single", copy.single, copy.singleHelp], ["department_dual", copy.dual, copy.dualHelp],
        ] as const).map(([value, title, help]) => <label className="organization-structure-option" key={value}><input type="radio" name="structure" checked={organizationStructure === value} onChange={() => setOrganizationStructure(value)} /><span><strong>{title}</strong><small>{help}</small></span></label>)}</fieldset>
        <label><span>{copy.founderPlan}</span><select value={founderPlan} onChange={(event) => setFounderPlan(event.target.value as OrganizationPlan)}><option value="free">Business Free</option><option value="plus">Business Plus</option><option value="pro">Business Pro</option></select></label>
        <div className="organization-wizard-actions"><button type="button" className="is-secondary" onClick={() => setWizardStep(1)}>{copy.back}</button><button type="button" disabled={busy} onClick={() => void submitOrganization()}>{copy.create}</button></div>
      </div>}
      {error ? <p className="organization-error" role="alert">{error}</p> : null}
    </section></main>;
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
        <article><Crown aria-hidden="true" /><span>{copy.plan}</span>{snapshot.actor.role === "owner" ? <select aria-label={copy.founderPlan} value={snapshot.organization.plan} disabled={busy} onChange={(event) => void changeFounderPlan(event.target.value as OrganizationPlan)}><option value="free">Business Free</option><option value="plus">Business Plus</option><option value="pro">Business Pro</option></select> : <strong>Business {snapshot.organization.plan.toUpperCase()}</strong>}</article>
        <article><Building2 aria-hidden="true" /><span>{copy.code}</span><strong>{snapshot.organization.public_code}</strong></article>
      </section>

      {snapshot.organization.structure_model !== "flat" && snapshot.actor.role === "owner" ? <section className="organization-departments-card">
        <header><h2>{copy.departments}</h2><div><input aria-label={copy.departmentName} maxLength={80} value={departmentName} onChange={(event) => setDepartmentName(event.target.value)} /><button type="button" disabled={busy || !departmentName.trim()} onClick={() => void addDepartment()}>{copy.addDepartment}</button></div></header>
        <div>{snapshot.departments.map((department) => <article key={department.id}><strong>{department.name}</strong><span>{department.manager_user_ids.length} Admin · {department.member_user_ids.length} Member</span></article>)}</div>
      </section> : null}

      {snapshot.actor.role === "owner" && snapshot.join_requests.length ? <section className="organization-join-requests"><h2>{copy.joinRequests}</h2>{snapshot.join_requests.map((request) => <article key={request.id}><span><strong>{request.display_name}</strong><small>{request.email} · Business {request.requested_plan.toUpperCase()}</small></span><button type="button" onClick={() => void reviewJoin(request.id, true)}>{copy.approve}</button><button type="button" className="is-secondary" onClick={() => void reviewJoin(request.id, false)}>{copy.reject}</button></article>)}</section> : null}

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
                <label><span>{copy.memberPlan}</span><select value={selectedPlan} onChange={(event) => setSelectedPlan(event.target.value as OrganizationPlan)}><option value="free">Business Free</option>{snapshot.organization.plan !== "free" ? <option value="plus">Business Plus</option> : null}{snapshot.organization.plan === "pro" ? <option value="pro">Business Pro</option> : null}</select></label>
                <button type="button" onClick={() => void savePlan()} disabled={busy || selectedPlan === selected.plan}>{copy.savePlan}</button>
                {canManageAdmins && snapshot.organization.structure_model !== "flat" && selected.role !== "owner" ? <label><span>{copy.assignDepartment}</span><select value={snapshot.departments.find((department) => [...department.manager_user_ids, ...department.member_user_ids].includes(selected.id))?.id ?? ""} onChange={(event) => void assignDepartment(event.target.value)}><option value="" disabled>{copy.unassigned}</option>{snapshot.departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label> : null}
                {snapshot.actor.can_transfer_founder && selected.role === "admin" ? <><button type="button" onClick={() => void transferFounder()} disabled={busy}>{transferArmed ? copy.confirmTransfer : copy.transfer}</button><small>{copy.transferHelp}</small></> : null}
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
