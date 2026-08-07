import {
  CheckCircle2,
  Send,
  Upload,
} from "lucide-react";
import {
  type FormEvent,
  useState,
} from "react";

import {
  CloudModelAccessError,
  submitBusinessUpgradeApplication,
  type BusinessUpgradeApplicationRequest,
} from "../features/settings/cloudModelAccess";

type SiteLocale = "en" | "zh-CN";

interface BusinessUpgradePageProps {
  locale: SiteLocale;
  authenticated: boolean;
  accountEmail: string;
  onRequireAccount: () => void;
  sensitiveCloudActionsEnabled?: boolean;
}

const employeeRanges = ["1-10", "11-50", "51-200", "201-1000", "1000+"] as const;

const copy = {
  en: {
    eyebrow: "BUSINESS ACCOUNT",
    title: "Upgrade a company account",
    ownerEmail: "Company owner email",
    legalName: "Company legal name",
    domain: "Company email domain",
    website: "Company website",
    country: "Country or region",
    role: "Your role or title",
    employees: "Employee count",
    registration: "Registration or tax number",
    plan: "Business plan",
    proof: "Company proof attachment",
    proofHint: "Registration certificate, tax document, official website proof, or purchasing authorization.",
    plus: "Business Plus",
    pro: "Business Pro",
    submit: "Submit for review",
    signIn: "Sign in before applying",
    submitted: "Application submitted",
    disabled: "Business account requests require the secure DroneDream cloud endpoint.",
    failed: "The business account request could not be submitted.",
  },
  "zh-CN": {
    eyebrow: "企业账号",
    title: "升级为公司账号",
    ownerEmail: "公司主账号邮箱",
    legalName: "公司法定名称",
    domain: "公司邮箱域名",
    website: "公司官网",
    country: "国家或地区",
    role: "你的职位或角色",
    employees: "员工规模",
    registration: "注册号或税号",
    plan: "企业套餐",
    proof: "公司证明附件",
    proofHint: "营业执照、税务文件、官网证明或采购授权均可。",
    plus: "企业 Plus",
    pro: "企业 Pro",
    submit: "提交审核",
    signIn: "请先登录再申请",
    submitted: "申请已提交",
    disabled: "企业账号申请需要安全的 DroneDream 云端入口。",
    failed: "企业账号申请暂时无法提交。",
  },
} as const;

function initialForm(accountEmail: string): BusinessUpgradeApplicationRequest {
  return {
    target_owner_email: accountEmail,
    company_legal_name: "",
    company_domain: "",
    company_website: "",
    country_region: "",
    applicant_role: "",
    employee_count_range: "11-50",
    registration_number: "",
    requested_plan_id: "plus",
    proof_file_names: [],
    note: "",
  };
}

export function BusinessUpgradePage({
  locale,
  authenticated,
  accountEmail,
  onRequireAccount,
  sensitiveCloudActionsEnabled = true,
}: BusinessUpgradePageProps) {
  const text = copy[locale];
  const [form, setForm] = useState(() => initialForm(accountEmail));
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const update = <Key extends keyof BusinessUpgradeApplicationRequest>(
    key: Key,
    value: BusinessUpgradeApplicationRequest[Key],
  ) => setForm((current) => ({ ...current, [key]: value }));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);
    if (!authenticated) {
      onRequireAccount();
      return;
    }
    if (!sensitiveCloudActionsEnabled) {
      setMessage(text.disabled);
      return;
    }
    setPending(true);
    try {
      await submitBusinessUpgradeApplication(form);
      setSubmitted(true);
      setMessage(text.submitted);
    } catch (error) {
      setMessage(
        error instanceof CloudModelAccessError ? error.message : text.failed,
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="site-portal business-upgrade-page">
      <header className="portal-page-heading">
        <p className="site-eyebrow">{text.eyebrow}</p>
        <h1>{text.title}</h1>
      </header>
      <form className="business-upgrade-form" onSubmit={(event) => void submit(event)}>
        <label>
          <span>{text.ownerEmail}</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={form.target_owner_email}
            onChange={(event) => update("target_owner_email", event.target.value)}
          />
        </label>
        <label>
          <span>{text.legalName}</span>
          <input
            required
            minLength={2}
            maxLength={160}
            autoComplete="organization"
            value={form.company_legal_name}
            onChange={(event) => update("company_legal_name", event.target.value)}
          />
        </label>
        <label>
          <span>{text.domain}</span>
          <input
            required
            maxLength={120}
            placeholder="company.com"
            value={form.company_domain}
            onChange={(event) => update("company_domain", event.target.value)}
          />
        </label>
        <label>
          <span>{text.website}</span>
          <input
            type="url"
            required
            maxLength={240}
            placeholder="https://company.com"
            value={form.company_website}
            onChange={(event) => update("company_website", event.target.value)}
          />
        </label>
        <label>
          <span>{text.country}</span>
          <input
            required
            maxLength={80}
            autoComplete="country-name"
            value={form.country_region}
            onChange={(event) => update("country_region", event.target.value)}
          />
        </label>
        <label>
          <span>{text.role}</span>
          <input
            required
            maxLength={100}
            autoComplete="organization-title"
            value={form.applicant_role}
            onChange={(event) => update("applicant_role", event.target.value)}
          />
        </label>
        <label>
          <span>{text.employees}</span>
          <select
            value={form.employee_count_range}
            onChange={(event) =>
              update(
                "employee_count_range",
                event.target.value as BusinessUpgradeApplicationRequest["employee_count_range"],
              )}
          >
            {employeeRanges.map((range) => (
              <option key={range} value={range}>{range}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{text.registration}</span>
          <input
            required
            maxLength={120}
            value={form.registration_number}
            onChange={(event) => update("registration_number", event.target.value)}
          />
        </label>
        <label>
          <span>{text.plan}</span>
          <select
            value={form.requested_plan_id}
            onChange={(event) =>
              update(
                "requested_plan_id",
                event.target.value as BusinessUpgradeApplicationRequest["requested_plan_id"],
              )}
          >
            <option value="plus">{text.plus}</option>
            <option value="pro">{text.pro}</option>
          </select>
        </label>
        <label>
          <span>{text.proof}</span>
          <input
            type="file"
            required
            aria-label={text.proof}
            accept=".pdf,.png,.jpg,.jpeg"
            onChange={(event) =>
              update(
                "proof_file_names",
                Array.from(event.target.files ?? [], (file) => file.name),
              )}
          />
          <small>{text.proofHint}</small>
        </label>
        <button type="submit" disabled={pending || submitted}>
          {submitted ? <CheckCircle2 aria-hidden="true" /> : <Send aria-hidden="true" />}
          {submitted ? text.submitted : authenticated ? text.submit : text.signIn}
        </button>
        {message ? (
          <p className="business-upgrade-message" role={submitted ? "status" : "alert"}>
            {submitted ? <CheckCircle2 aria-hidden="true" /> : <Upload aria-hidden="true" />}
            {message}
          </p>
        ) : null}
      </form>
    </div>
  );
}
