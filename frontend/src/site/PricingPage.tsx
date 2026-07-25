import { Check, ShieldCheck, Sparkles, Users, X } from "lucide-react";
import { useState } from "react";

type SiteLocale = "en" | "zh-CN";
type Audience = "individual" | "business";

interface PricingPageProps {
  locale: SiteLocale;
  authenticated: boolean;
  onRequireAccount: () => void;
}

interface Plan {
  name: string;
  price: number;
  featured?: boolean;
  features: readonly string[];
}

const pricingContent = {
  en: {
    eyebrow: "DRONEDREAM PLANS",
    title: "Choose the right workspace for every flight.",
    mobileTitle: "Choose your workspace.",
    intro:
      "Start free and upgrade only when experiments, collaboration, or evidence retention need more room.",
    individual: "Individual",
    business: "Business",
    month: "/ month",
    userMonth: "/ user / month",
    current: "Current plan",
    choose: "Choose",
    upgrade: "Upgrade",
    recommended: "Recommended",
    close: "Close payment dialog",
    paymentTitle: "Choose a payment method",
    paymentIntro: "Review the selected plan and choose how you want to pay.",
    wechat: "WeChat Pay",
    alipay: "Alipay",
    continue: "Continue to payment",
    unavailable: "Merchant payment activation is in progress.",
    plans: {
      individual: [
        {
          name: "Free",
          price: 0,
          features: [
            "Create reviewable experiment drafts locally",
            "Configure each study through five guided steps",
            "Edit custom tracks in 2D and 3D views",
            "Keep run history, logs, and evidence together",
            "Export configurations and comparison reports",
            "Join the public engineering community",
          ],
        },
        {
          name: "Plus",
          price: 20,
          featured: true,
          features: [
            "Everything in Free",
            "Increase Tuning Chat and voice capacity",
            "Compare more experiments in one workspace",
            "Export longer evidence and report histories",
            "Receive new optimizer workflows earlier",
            "Use priority experiment-draft assistance",
          ],
        },
        {
          name: "Pro",
          price: 200,
          features: [
            "Everything in Plus",
            "Use the highest individual model allowance",
            "Retain evidence for advanced long studies",
            "Review larger experiment portfolios together",
            "Receive priority help for complex tuning",
            "Access advanced reports and integrations",
          ],
        },
      ],
      business: [
        {
          name: "Business Free",
          price: 0,
          features: [
            "Evaluate the workflow with a small team",
            "Create shared reviewable experiment drafts",
            "Use local simulation and evidence storage",
            "Compare results with consistent templates",
            "Export configurations and reports together",
            "Join the public engineering community",
          ],
        },
        {
          name: "Business Plus",
          price: 20,
          featured: true,
          features: [
            "Everything in Business Free",
            "Share experiment templates and review roles",
            "Keep team activity and governed exports",
            "Increase assistant allowance per member",
            "Retain longer project evidence histories",
            "Receive new optimizer workflows earlier",
          ],
        },
        {
          name: "Business Pro",
          price: 200,
          features: [
            "Everything in Business Plus",
            "Apply advanced access and audit controls",
            "Retain evidence for long engineering programs",
            "Integrate governed reports and services",
            "Receive priority deployment guidance",
            "Support larger engineering organizations",
          ],
        },
      ],
    },
  },
  "zh-CN": {
    eyebrow: "DRONEDREAM 套餐",
    title: "为每一次飞行选择合适的工作空间。",
    mobileTitle: "选择飞行工作空间。",
    intro:
      "从免费版开始；当实验规模、协作或证据留存需求增加时，再按需升级。",
    individual: "个人",
    business: "商业",
    month: "/ 月",
    userMonth: "/ 用户 / 月",
    current: "当前套餐",
    choose: "选择",
    upgrade: "升级",
    recommended: "推荐",
    close: "关闭支付弹窗",
    paymentTitle: "选择付款方式",
    paymentIntro: "确认所选套餐，并选择希望使用的付款方式。",
    wechat: "微信支付",
    alipay: "支付宝",
    continue: "继续付款",
    unavailable: "商户支付能力正在接入。",
    plans: {
      individual: [
        {
          name: "Free",
          price: 0,
          features: [
            "在本地创建并审查实验草稿",
            "通过五个环节完成实验配置",
            "在二维和三维视图中编辑轨迹",
            "统一保留历史、日志和实验依据",
            "导出实验配置与对比报告",
            "加入公开的工程交流社区",
          ],
        },
        {
          name: "Plus",
          price: 20,
          featured: true,
          features: [
            "包含 Free 的全部内容",
            "提高调优对话与语音使用额度",
            "在同一工作区比较更多实验",
            "导出更长的实验依据与报告历史",
            "更早获得新的优化策略工作流",
            "优先获得实验草稿辅助能力",
          ],
        },
        {
          name: "Pro",
          price: 200,
          features: [
            "包含 Plus 的全部内容",
            "使用最高的个人模型额度",
            "长期保留高级实验研究依据",
            "集中审查更大的实验组合",
            "优先获得复杂调优研究支持",
            "使用高级报告与集成能力",
          ],
        },
      ],
      business: [
        {
          name: "Business Free",
          price: 0,
          features: [
            "由小型团队评估完整工作流",
            "共同创建并审查实验草稿",
            "使用本地仿真和实验依据存储",
            "通过统一模板比较实验结果",
            "共同导出实验配置与报告",
            "加入公开的工程交流社区",
          ],
        },
        {
          name: "Business Plus",
          price: 20,
          featured: true,
          features: [
            "包含 Business Free 的全部内容",
            "共享实验模板与审查角色",
            "保留团队活动和受控导出记录",
            "提高每位成员的助手使用额度",
            "延长项目实验依据的留存时间",
            "更早获得新的优化策略工作流",
          ],
        },
        {
          name: "Business Pro",
          price: 200,
          features: [
            "包含 Business Plus 的全部内容",
            "应用高级访问与审计控制",
            "长期留存工程项目实验依据",
            "集成受控报告与外部服务",
            "优先获得部署与集成指导",
            "支持更大规模的工程组织",
          ],
        },
      ],
    },
  },
} as const;

export function PricingPage({
  locale,
  authenticated,
  onRequireAccount,
}: PricingPageProps) {
  const copy = pricingContent[locale];
  const [audience, setAudience] = useState<Audience>("individual");
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<"wechat" | "alipay">("wechat");
  const plans = copy.plans[audience] as readonly Plan[];

  const choosePlan = (plan: Plan) => {
    if (plan.price === 0) return;
    if (!authenticated) {
      onRequireAccount();
      return;
    }
    setSelectedPlan(plan);
  };

  return (
    <div className="site-portal pricing-page">
      <header className="portal-page-heading">
        <p className="site-eyebrow">{copy.eyebrow}</p>
        <h1 aria-label={copy.title}>
          <span aria-hidden="true" className="portal-title-desktop">{copy.title}</span>
          <span aria-hidden="true" className="portal-title-mobile">{copy.mobileTitle}</span>
        </h1>
        <p>{copy.intro}</p>
      </header>

      <div className="pricing-audience" role="tablist" aria-label={copy.title}>
        <button
          type="button"
          role="tab"
          aria-selected={audience === "individual"}
          onClick={() => setAudience("individual")}
        >
          <Sparkles aria-hidden="true" />
          {copy.individual}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={audience === "business"}
          onClick={() => setAudience("business")}
        >
          <Users aria-hidden="true" />
          {copy.business}
        </button>
      </div>

      <div className="pricing-grid">
        {plans.map((plan, index) => (
          <article
            key={plan.name}
            className={`pricing-card${plan.featured ? " is-featured" : ""}`}
          >
            {plan.featured ? <span className="pricing-badge">{copy.recommended}</span> : null}
            <header>
              <h2>{plan.name}</h2>
              <p>
                <strong><span>¥</span>{plan.price}</strong>
                <span>{audience === "business" ? copy.userMonth : copy.month}</span>
              </p>
            </header>
            <button
              type="button"
              className={plan.featured ? "is-primary" : ""}
              disabled={index === 0}
              onClick={() => choosePlan(plan)}
            >
              {index === 0 ? copy.current : `${copy.upgrade} ${plan.name}`}
            </button>
            <ul>
              {plan.features.map((feature) => (
                <li key={feature}><Check aria-hidden="true" /><span>{feature}</span></li>
              ))}
            </ul>
          </article>
        ))}
      </div>

      {selectedPlan ? (
        <div className="payment-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSelectedPlan(null);
        }}>
          <section className="payment-dialog" role="dialog" aria-modal="true" aria-labelledby="payment-title">
            <header>
              <div>
                <ShieldCheck aria-hidden="true" />
                <h2 id="payment-title">{copy.paymentTitle}</h2>
              </div>
              <button type="button" aria-label={copy.close} onClick={() => setSelectedPlan(null)}>
                <X aria-hidden="true" />
              </button>
            </header>
            <p>{copy.paymentIntro}</p>
            <div className="payment-plan-summary">
              <strong>{selectedPlan.name}</strong>
              <span>¥{selectedPlan.price} {audience === "business" ? copy.userMonth : copy.month}</span>
            </div>
            <div className="payment-methods">
              <button
                type="button"
                aria-label={copy.wechat}
                aria-pressed={paymentMethod === "wechat"}
                onClick={() => setPaymentMethod("wechat")}
              >
                <span className="payment-method-logo is-wechat">微</span>
                {copy.wechat}
              </button>
              <button
                type="button"
                aria-label={copy.alipay}
                aria-pressed={paymentMethod === "alipay"}
                onClick={() => setPaymentMethod("alipay")}
              >
                <span className="payment-method-logo is-alipay">支</span>
                {copy.alipay}
              </button>
            </div>
            <button type="button" className="payment-continue" disabled>
              {copy.continue}
            </button>
            <p className="payment-state">{copy.unavailable}</p>
          </section>
        </div>
      ) : null}
    </div>
  );
}
