import {
  Building2,
  CircleUserRound,
  Crown,
  Eye,
  Save,
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
  setOrganizationJoinPassword,
  setOrganizationPlan,
  transferOrganizationFounder,
  updateOrganizationName,
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
    plan: "Business plan",
    planControl: "Plan",
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
    name: "Name",
    nameControl: "Organization name",
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
    code: "Code",
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
    password: "Password",
    passwordControl: "Organization password",
    passwordHelp: "Use this password when joining the organization.",
    passwordConfigured: "Configured",
    passwordMissing: "Not configured",
    savePassword: "Save password",
    saveName: "Save organization name",
    organizationDetails: "Organization details",
    deleteMember: "Delete member",
  },
  "zh-CN": {
    title: "企业管理",
    members: "成员",
    delegated: "委托管理员",
    plan: "企业套餐",
    planControl: "套餐",
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
    name: "名称",
    nameControl: "组织名称",
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
    code: "代号",
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
    password: "密码",
    passwordControl: "组织密码",
    passwordHelp: "加入组织时需要输入此密码。",
    passwordConfigured: "已设置",
    passwordMissing: "未设置",
    savePassword: "保存密码",
    saveName: "保存组织名称",
    organizationDetails: "组织信息",
    deleteMember: "删除成员",
  },
} as const;

function roleLabel(
  role: OrganizationRole,
  copy: typeof content.en | typeof content["zh-CN"],
): string {
  return role === "owner" ? copy.owner : role === "admin" ? copy.admin : copy.member;
}

function OrganizationAvatar({ member, large = false }: {
  member: Pick<OrganizationMember, "avatar_url" | "display_name">;
  large?: boolean;
}) {
  return (
    <span className={`organization-avatar${large ? " is-large" : ""}`}>
      {member.avatar_url ? (
        <img src={member.avatar_url} alt={`${member.display_name} avatar`} loading="lazy" referrerPolicy="no-referrer" />
      ) : (
        <CircleUserRound aria-hidden="true" />
      )}
    </span>
  );
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
  type SaveAction = "organization-name" | "organization-plan" | "organization-password" | "member-role" | "member-plan";
  const [savingActions, setSavingActions] = useState<ReadonlySet<SaveAction>>(() => new Set());
  const markSaving = (action: SaveAction, saving: boolean) => setSavingActions((current) => {
    const next = new Set(current);
    if (saving) next.add(action);
    else next.delete(action);
    return next;
  });
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
  const [organizationPassword, setOrganizationPassword] = useState("");
  const [organizationStructure, setOrganizationStructure] = useState<OrganizationStructure>("flat");
  const [founderPlan, setFounderPlan] = useState<OrganizationPlan>(requestedPlan);
  const [departmentName, setDepartmentName] = useState("");
  const [onboardingMode, setOnboardingMode] = useState<"choose" | "create" | "join">("choose");
  const [organizationQuery, setOrganizationQuery] = useState("");
  const [organizationResults, setOrganizationResults] = useState<OrganizationSearchResult[]>([]);
  const [joinPlan, setJoinPlan] = useState<OrganizationPlan>(requestedPlan);
  const [joinPassword, setJoinPassword] = useState("");
  const [joinRequested, setJoinRequested] = useState(false);
  const [organizationDialogOpen, setOrganizationDialogOpen] = useState(false);
  const [organizationDraftName, setOrganizationDraftName] = useState("");
  const [organizationDraftPlan, setOrganizationDraftPlan] = useState<OrganizationPlan>("free");
  const [organizationDraftPassword, setOrganizationDraftPassword] = useState("");
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const organizationDialogRef = useRef<HTMLElement>(null);
  const organizationCloseRef = useRef<HTMLButtonElement>(null);
  const captureDetailsTrigger = useModalFocus({
    open: Boolean(selected),
    dialogRef,
    initialFocusRef: closeRef,
    onClose: () => setSelected(null),
  });
  const captureOrganizationTrigger = useModalFocus({
    open: organizationDialogOpen,
    dialogRef: organizationDialogRef,
    initialFocusRef: organizationCloseRef,
    onClose: () => setOrganizationDialogOpen(false),
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
    if (!selected || savingActions.has("member-plan") || selected.role === "owner") return;
    markSaving("member-plan", true);
    try { updateSnapshot(await setOrganizationMemberPlan(selected.id, selectedPlan)); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { markSaving("member-plan", false); }
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
    if (!organizationName.trim() || organizationPassword.length < 8 || busy) return;
    setBusy(true);
    try {
      updateSnapshot(await createOrganization({
        name: organizationName.trim(), description: organizationDescription.trim(),
        structure: organizationStructure, plan: founderPlan, password: organizationPassword,
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
    try { await requestOrganizationJoin(organization.public_code, joinPlan, joinPassword); setJoinRequested(true); setError(null); }
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
    if (!selected || savingActions.has("member-role") || selected.role === "owner") return;
    markSaving("member-role", true);
    setError(null);
    try {
      updateSnapshot(await setOrganizationMemberRole(selected.id, selectedRole));
    } catch (reason) {
      setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable);
    } finally {
      markSaving("member-role", false);
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

  const canRemove = (member: OrganizationMember) => member.role !== "owner" && (
    snapshot?.actor.role === "owner" || member.role === "member"
  );

  const removeMemberFromRow = async (member: OrganizationMember) => {
    if (!canRemove(member) || busy) return;
    setBusy(true);
    setError(null);
    try { updateSnapshot(await removeOrganizationMember(member.id)); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { setBusy(false); }
  };

  const openOrganizationDialog = () => {
    if (!snapshot) return;
    captureOrganizationTrigger();
    setOrganizationDraftName(snapshot.organization.name);
    setOrganizationDraftPlan(snapshot.organization.plan);
    setOrganizationDraftPassword(snapshot.organization.join_password ?? "");
    setOrganizationDialogOpen(true);
  };

  const saveOrganizationName = async () => {
    if (!snapshot || snapshot.actor.role !== "owner" || !organizationDraftName.trim() || savingActions.has("organization-name")) return;
    markSaving("organization-name", true);
    try { updateSnapshot(await updateOrganizationName(organizationDraftName.trim())); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { markSaving("organization-name", false); }
  };

  const saveOrganizationPlan = async () => {
    if (!snapshot || snapshot.actor.role !== "owner" || savingActions.has("organization-plan")) return;
    markSaving("organization-plan", true);
    try { updateSnapshot(await setOrganizationPlan(organizationDraftPlan)); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { markSaving("organization-plan", false); }
  };

  const saveOrganizationPassword = async () => {
    if (!snapshot || snapshot.actor.role !== "owner" || organizationDraftPassword.length < 8 || savingActions.has("organization-password")) return;
    markSaving("organization-password", true);
    try { updateSnapshot(await setOrganizationJoinPassword(organizationDraftPassword)); }
    catch (reason) { setError(reason instanceof OrganizationConsoleError ? reason.message : copy.unavailable); }
    finally { markSaving("organization-password", false); }
  };

  if (loading) {
    return <main className="organization-page site-shell" aria-busy="true">{copy.loading}</main>;
  }
  if (!snapshot && canCreate) {
    return <main className="organization-page site-shell"><section className={`organization-onboarding is-${onboardingMode}`} aria-labelledby="organization-create-title">
      <header><Building2 aria-hidden="true" /><div><h1 id="organization-create-title">{onboardingMode === "choose" ? copy.choosePath : onboardingMode === "join" ? copy.joinExisting : copy.createTitle}</h1><p>{copy.createIntro}</p></div>{onboardingMode === "create" ? <span>{wizardStep} / 2</span> : null}</header>
      {onboardingMode === "choose" ? <div className="organization-path-options"><button type="button" onClick={() => setOnboardingMode("create")}><Crown aria-hidden="true" /><strong>{copy.createNew}</strong></button><button type="button" onClick={() => setOnboardingMode("join")}><Users aria-hidden="true" /><strong>{copy.joinExisting}</strong></button></div> : onboardingMode === "join" ? <div className="organization-wizard-fields"><label><span>{copy.searchOrganization}</span><input autoFocus value={organizationQuery} onChange={(event) => setOrganizationQuery(event.target.value)} /></label><label><span>{copy.password}</span><input aria-label={copy.passwordControl} type="password" maxLength={72} value={joinPassword} onChange={(event) => setJoinPassword(event.target.value)} /></label><label><span>{copy.memberPlan}</span><select value={joinPlan} onChange={(event) => setJoinPlan(event.target.value as OrganizationPlan)}><option value="free">Business Free</option><option value="plus">Business Plus</option><option value="pro">Business Pro</option></select></label><div className="organization-wizard-actions"><button type="button" className="is-secondary" onClick={() => setOnboardingMode("choose")}>{copy.back}</button><button type="button" onClick={() => void searchForOrganizations()}>{copy.search}</button></div>{joinRequested ? <p>{copy.requestSent}</p> : organizationResults.map((organization) => <article className="organization-search-result" key={organization.public_code}><div><strong>{organization.name}</strong><span>{organization.public_code} · Business {organization.plan.toUpperCase()}</span><small>{organization.description}</small></div><button type="button" disabled={!joinPassword || (organization.plan === "free" && joinPlan !== "free") || (organization.plan === "plus" && joinPlan === "pro")} onClick={() => void requestJoin(organization)}>{copy.requestJoin}</button></article>)}</div> : wizardStep === 1 ? <div className="organization-wizard-fields">
        <label><span>{copy.name}</span><input aria-label={copy.nameControl} autoFocus maxLength={120} value={organizationName} onChange={(event) => setOrganizationName(event.target.value)} /></label>
        <label><span>{copy.description}</span><textarea maxLength={500} rows={4} value={organizationDescription} onChange={(event) => setOrganizationDescription(event.target.value)} /></label>
        <label><span>{copy.password}</span><input aria-label={copy.passwordControl} type="password" minLength={8} maxLength={72} value={organizationPassword} onChange={(event) => setOrganizationPassword(event.target.value)} /><small>{copy.passwordHelp}</small></label>
        <div className="organization-wizard-actions"><button type="button" className="is-secondary" onClick={() => setOnboardingMode("choose")}>{copy.back}</button><button type="button" disabled={!organizationName.trim() || organizationPassword.length < 8} onClick={() => setWizardStep(2)}>{copy.next}</button></div>
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
        <button type="button" className="organization-settings-trigger" onClick={openOrganizationDialog}><Building2 aria-hidden="true" />{copy.title}</button>
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
                  <td><OrganizationAvatar member={member} /><span><strong>{member.display_name}</strong><small>{member.email}</small></span></td>
                  <td><span className={`organization-role is-${member.role}`}>{roleLabel(member.role, copy)}</span></td>
                  <td><strong>{member.plan.toUpperCase()}</strong></td>
                  <td><EditionLicenseStrip licenses={member.licenses} locale={locale} /></td>
                  <td>{date.format(new Date(member.created_at))}</td>
                  <td>{member.last_sign_in_at ? date.format(new Date(member.last_sign_in_at)) : copy.noSignIn}</td>
                  <td><div className="organization-row-actions"><button type="button" className="organization-details-button" onClick={() => openDetails(member)}><Eye aria-hidden="true" /><span>{copy.details}</span></button><button type="button" className="organization-row-delete" aria-label={`${copy.deleteMember}: ${member.display_name}`} title={copy.deleteMember} disabled={busy || !canRemove(member)} onClick={() => void removeMemberFromRow(member)}><Trash2 aria-hidden="true" /></button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {organizationDialogOpen ? <div className="organization-dialog-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setOrganizationDialogOpen(false); }}>
        <section ref={organizationDialogRef} className="organization-member-dialog organization-information-dialog" role="dialog" aria-modal="true" aria-labelledby="organization-information-title" tabIndex={-1}>
          <header><div><span className="organization-avatar is-large"><Building2 aria-hidden="true" /></span><div><h2 id="organization-information-title">{copy.organizationDetails}</h2><span>{snapshot.organization.public_code}</span></div></div><button ref={organizationCloseRef} type="button" aria-label={copy.close} onClick={() => setOrganizationDialogOpen(false)}><X aria-hidden="true" /></button></header>
          <div className="organization-member-profile"><dl>
            <div><dt>{copy.members}</dt><dd>{snapshot.members.length}</dd></div>
            <div><dt>{copy.delegated}</dt><dd>{adminCount} / {snapshot.admin_limit}</dd></div>
            <div><dt>{copy.code}</dt><dd>{snapshot.organization.public_code}</dd></div>
            <div><dt>{copy.password}</dt><dd>{snapshot.organization.join_password ?? copy.passwordMissing}</dd></div>
          </dl></div>
          {snapshot.actor.role === "owner" ? <div className="organization-member-actions">
            <div className="organization-profile-field is-inline"><label htmlFor="organization-profile-name">{copy.name}</label><input id="organization-profile-name" aria-label={copy.nameControl} maxLength={120} value={organizationDraftName} onChange={(event) => setOrganizationDraftName(event.target.value)} /><button type="button" aria-label={savingActions.has("organization-name") ? copy.saving : copy.saveName} title={copy.saveName} disabled={savingActions.has("organization-name") || !organizationDraftName.trim() || organizationDraftName.trim() === snapshot.organization.name} onClick={() => void saveOrganizationName()}><Save aria-hidden="true" /></button></div>
            <div className="organization-profile-field is-inline"><label htmlFor="organization-profile-plan">{copy.plan}</label><select id="organization-profile-plan" aria-label={copy.planControl} value={organizationDraftPlan} onChange={(event) => setOrganizationDraftPlan(event.target.value as OrganizationPlan)}><option value="free">Business Free</option><option value="plus">Business Plus</option><option value="pro">Business Pro</option></select><button type="button" aria-label={savingActions.has("organization-plan") ? copy.saving : copy.savePlan} title={copy.savePlan} disabled={savingActions.has("organization-plan") || organizationDraftPlan === snapshot.organization.plan} onClick={() => void saveOrganizationPlan()}><Save aria-hidden="true" /></button></div>
            <div className="organization-profile-field is-inline"><label htmlFor="organization-profile-password">{copy.password}</label><input id="organization-profile-password" aria-label={copy.passwordControl} type="text" minLength={8} maxLength={72} value={organizationDraftPassword} onChange={(event) => setOrganizationDraftPassword(event.target.value)} /><button type="button" aria-label={savingActions.has("organization-password") ? copy.saving : copy.savePassword} title={copy.savePassword} disabled={savingActions.has("organization-password") || organizationDraftPassword.length < 8 || organizationDraftPassword === snapshot.organization.join_password} onClick={() => void saveOrganizationPassword()}><Save aria-hidden="true" /></button></div>
          </div> : null}
          {error ? <p className="organization-error" role="alert">{error}</p> : null}
        </section>
      </div> : null}

      {selected ? (
        <div className="organization-dialog-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSelected(null);
        }}>
          <section ref={dialogRef} className="organization-member-dialog" role="dialog" aria-modal="true" aria-labelledby="organization-member-title" tabIndex={-1}>
            <header><div><OrganizationAvatar member={selected} large /><div><h2 id="organization-member-title">{selected.display_name}</h2><span>{selected.email}</span></div></div><button ref={closeRef} type="button" aria-label={copy.close} onClick={() => setSelected(null)}><X aria-hidden="true" /></button></header>
            <div className="organization-member-profile">
              <dl>
                <div><dt>{copy.role}</dt><dd>{roleLabel(selected.role, copy)}</dd></div>
                <div><dt>{copy.plan}</dt><dd>{selected.plan.toUpperCase()}</dd></div>
                <div><dt>{copy.created}</dt><dd>{date.format(new Date(selected.created_at))}</dd></div>
                <div><dt>{copy.lastSignIn}</dt><dd>{selected.last_sign_in_at ? date.format(new Date(selected.last_sign_in_at)) : copy.noSignIn}</dd></div>
                <div className="organization-member-applications"><dt>{copy.apps}</dt><dd><EditionLicenseStrip licenses={selected.licenses} locale={locale} /></dd></div>
              </dl>
            </div>
            {canManageSelected ? (
              <div className="organization-member-actions">
                {canManageAdmins ? <div className="organization-member-edit-row"><label htmlFor="organization-member-role">{copy.role}</label><select id="organization-member-role" value={selectedRole} onChange={(event) => setSelectedRole(event.target.value as "admin" | "member")}><option value="member">{copy.member}</option><option value="admin">{copy.admin}</option></select><button type="button" className="organization-save-button" aria-label={savingActions.has("member-role") ? copy.saving : copy.saveRole} title={copy.saveRole} onClick={() => void saveRole()} disabled={savingActions.has("member-role") || selectedRole === selected.role}><Save aria-hidden="true" /></button></div> : null}
                <div className="organization-member-edit-row"><label htmlFor="organization-member-plan">{copy.memberPlan}</label><select id="organization-member-plan" value={selectedPlan} onChange={(event) => setSelectedPlan(event.target.value as OrganizationPlan)}><option value="free">Business Free</option>{snapshot.organization.plan !== "free" ? <option value="plus">Business Plus</option> : null}{snapshot.organization.plan === "pro" ? <option value="pro">Business Pro</option> : null}</select><button type="button" className="organization-save-button" aria-label={savingActions.has("member-plan") ? copy.saving : copy.savePlan} title={copy.savePlan} onClick={() => void savePlan()} disabled={savingActions.has("member-plan") || selectedPlan === selected.plan}><Save aria-hidden="true" /></button></div>
                {canManageAdmins && snapshot.organization.structure_model !== "flat" && selected.role !== "owner" ? <div className="organization-member-edit-row is-department"><label htmlFor="organization-member-department">{copy.assignDepartment}</label><select id="organization-member-department" value={snapshot.departments.find((department) => [...department.manager_user_ids, ...department.member_user_ids].includes(selected.id))?.id ?? ""} onChange={(event) => void assignDepartment(event.target.value)}><option value="" disabled>{copy.unassigned}</option>{snapshot.departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></div> : null}
                {snapshot.actor.can_transfer_founder && selected.role === "admin" ? <><button type="button" onClick={() => void transferFounder()} disabled={busy}>{transferArmed ? copy.confirmTransfer : copy.transfer}</button><small>{copy.transferHelp}</small></> : null}
                <div className="organization-member-danger-row"><button type="button" className="is-danger" onClick={() => void removeMember()} disabled={busy}><Trash2 aria-hidden="true" />{busy ? copy.removing : removalArmed ? copy.confirmRemove : copy.remove}</button>{removalArmed ? <small>{copy.downgrade}</small> : null}</div>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </main>
  );
}
