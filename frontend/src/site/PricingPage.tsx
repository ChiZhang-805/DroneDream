import {
  BrainCircuit,
  CreditCard,
  FileOutput,
  Gauge,
  GitCompareArrows,
  KeyRound,
  Route,
  ShieldCheck,
  Sparkles,
  Stamp,
  Users,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { PaymentBrandMark } from "../components/PaymentBrandMark";
import {
  CloudModelAccessError,
  createBillingCheckout,
  getBillingAvailability,
  getManagedModelUsage,
  type BillingAvailability,
  type ManagedModelBillingScope,
  type ManagedModelPlanId,
  type PaymentMethod,
} from "../features/settings/cloudModelAccess";
import { useModalFocus } from "../hooks/useModalFocus";

type SiteLocale = "en" | "zh-CN";
type PaidPlanId = "plus" | "pro";
type Audience = "individual" | "business";
type FeatureKey =
  | "workflow"
  | "harness"
  | "allowance"
  | "byok"
  | "reports"
  | "comparisonWorkspace"
  | "watermarkFree"
  | "premiumRouting"
  | "advancedHarness";

interface PricingPageProps {
  locale: SiteLocale;
  authenticated: boolean;
  onRequireAccount: () => void;
  sensitiveCloudActionsEnabled?: boolean;
}

interface Plan {
  id: "free" | PaidPlanId;
  name: string;
  price: number;
  includedCredits: number;
  featured?: boolean;
}

type SubscriptionKey = `${Audience}-${ManagedModelPlanId}`;

interface DisplayPlan extends Plan {
  billingScope: Audience;
  subscriptionKey: SubscriptionKey;
}

const PLANS: readonly Plan[] = [
  { id: "free", name: "Free", price: 0, includedCredits: 300_000 },
  { id: "plus", name: "Plus", price: 39, includedCredits: 3_000_000, featured: true },
  { id: "pro", name: "Pro", price: 129, includedCredits: 15_000_000 },
];
const BUSINESS_SEAT_PRICES: Record<PaidPlanId, number> = {
  plus: 19,
  pro: 69,
};

function subscriptionKey(
  scope: ManagedModelBillingScope,
  planId: ManagedModelPlanId,
): SubscriptionKey {
  return `${scope}-${planId}`;
}

const FEATURE_KEYS: readonly FeatureKey[] = [
  "workflow",
  "harness",
  "allowance",
  "byok",
  "reports",
  "comparisonWorkspace",
  "watermarkFree",
  "premiumRouting",
  "advancedHarness",
];

const FEATURE_ICONS: Record<FeatureKey, LucideIcon> = {
  workflow: Workflow,
  harness: BrainCircuit,
  allowance: Gauge,
  byok: KeyRound,
  reports: FileOutput,
  comparisonWorkspace: GitCompareArrows,
  watermarkFree: Stamp,
  premiumRouting: Route,
  advancedHarness: Sparkles,
};

const pricingContent = {
  en: {
    title: "Choose the optimization depth for every flight.",
    mobileTitleLines: ["Choose your", "optimization depth."],
    audienceLabel: "Workspace type",
    individual: "Individual",
    business: "Business",
    month: "/ month",
    perUserMonth: "/ user / month",
    current: "Free plan",
    currentPlan: "Current plan",
    currentSubscription: "Current subscription",
    start: "Start free",
    upgrade: "Choose",
    recommended: "Recommended",
    includedStatus: "Included",
    unavailableStatus: "Not included",
    features: {
      workflow: "Complete DroneDream tuning workflow",
      harness: "Core AURORA optimization Harness",
      byok: "BYOK fallback after the included allowance",
      reports: "Experiment and comparison report export",
      comparisonWorkspace: "Expanded multi-experiment comparison workspace",
      watermarkFree: "Watermark-free PDF report export",
      premiumRouting: "Premium managed-model routing",
      advancedHarness: "Advanced AURORA strategy previews",
    },
    businessFeatures: {
      workflow: "Shared DroneDream tuning workspace",
      harness: "Team AURORA optimization Harness",
      byok: "Team BYOK fallback after the included allowance",
      reports: "Shared experiment and comparison report export",
      comparisonWorkspace: "Team multi-experiment comparison workspace",
      watermarkFree: "Team watermark-free PDF report export",
      premiumRouting: "Business managed-model routing",
      advancedHarness: "Shared AURORA strategy previews",
    },
    allowanceFeature: (credits: string) => `${credits} managed AI credits each month`,
    businessAllowanceFeature: (credits: string) => `${credits} managed AI credits per user each month`,
    close: "Close payment dialog",
    paymentTitle: "Payment",
    wechat: "WeChat Pay",
    alipay: "Alipay",
    card: "Credit or debit card",
    continue: "Continue to payment",
    availabilityFailed: "Payment methods are temporarily unavailable.",
    paymentFailed: "The payment order could not be created.",
    qrTitle: "Scan with WeChat to pay",
    qrAlt: "WeChat Pay QR code",
    callbackNote:
      "The plan activates only after DroneDream verifies the payment provider callback.",
  },
  "zh-CN": {
    title: "为每一次飞行选择合适的优化深度。",
    mobileTitleLines: ["为每一次飞行", "选择合适的优化深度"],
    audienceLabel: "工作空间类型",
    individual: "个人",
    business: "商业",
    month: "/ 月",
    perUserMonth: "/ 人 / 月",
    current: "免费套餐",
    currentPlan: "当前套餐",
    currentSubscription: "当前订阅",
    start: "免费开始",
    upgrade: "选择",
    recommended: "推荐",
    includedStatus: "已包含",
    unavailableStatus: "未包含",
    features: {
      workflow: "完整的 DroneDream 调优工作流",
      harness: "AURORA 核心优化 Harness",
      byok: "赠送额度用尽后切换到自己的 API Key",
      reports: "导出实验与对比报告",
      comparisonWorkspace: "扩展的多实验对比工作区",
      watermarkFree: "导出无水印 PDF 报告",
      premiumRouting: "高性能托管模型智能路由",
      advancedHarness: "优先体验 AURORA 高级策略",
    },
    businessFeatures: {
      workflow: "共享 DroneDream 调优工作区",
      harness: "团队 AURORA 优化 Harness",
      byok: "团队额度用尽后切换到自有 API Key",
      reports: "共享实验与对比报告导出",
      comparisonWorkspace: "团队多实验对比工作区",
      watermarkFree: "团队无水印 PDF 报告导出",
      premiumRouting: "商业托管模型路由",
      advancedHarness: "共享 AURORA 高级策略预览",
    },
    allowanceFeature: (credits: string) => `每月 ${credits} 托管模型 AI 额度`,
    businessAllowanceFeature: (credits: string) => `每人每月 ${credits} 托管模型 AI 额度`,
    close: "关闭支付弹窗",
    paymentTitle: "支付",
    wechat: "微信支付",
    alipay: "支付宝",
    card: "信用卡或借记卡",
    continue: "继续付款",
    availabilityFailed: "支付方式暂时不可用。",
    paymentFailed: "暂时无法创建支付订单。",
    qrTitle: "请使用微信扫码支付",
    qrAlt: "微信支付二维码",
    callbackNote:
      "只有 DroneDream 服务端验证支付平台回调后，套餐才会正式生效。",
  },
} as const;

function formatCredits(locale: SiteLocale, value: number): string {
  return new Intl.NumberFormat(locale === "zh-CN" ? "zh-CN" : "en").format(value);
}

export function PricingPage({
  locale,
  authenticated,
  onRequireAccount,
  sensitiveCloudActionsEnabled = true,
}: PricingPageProps) {
  const copy = pricingContent[locale];
  const [audience, setAudience] = useState<Audience>("individual");
  const [selectedPlan, setSelectedPlan] = useState<DisplayPlan | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("wechat");
  const [availability, setAvailability] = useState<BillingAvailability | null>(null);
  const [currentSubscriptionKey, setCurrentSubscriptionKey] =
    useState<SubscriptionKey>("individual-free");
  const [paymentState, setPaymentState] =
    useState<"idle" | "checking" | "creating" | "qr" | "error">("idle");
  const [paymentMessage, setPaymentMessage] = useState<string | null>(null);
  const [wechatQr, setWechatQr] = useState<string | null>(null);
  const paymentDialogRef = useRef<HTMLElement>(null);
  const paymentCloseRef = useRef<HTMLButtonElement>(null);
  const individualAudienceRef = useRef<HTMLButtonElement>(null);
  const businessAudienceRef = useRef<HTMLButtonElement>(null);
  const capturePaymentTrigger = useModalFocus({
    open: Boolean(selectedPlan),
    dialogRef: paymentDialogRef,
    initialFocusRef: paymentCloseRef,
    onClose: () => setSelectedPlan(null),
  });

  useEffect(() => {
    if (!sensitiveCloudActionsEnabled) {
      setAvailability(null);
      setPaymentState("idle");
      setPaymentMessage(null);
      setWechatQr(null);
      return undefined;
    }
    let active = true;
    setPaymentState("checking");
    setPaymentMessage(null);
    setWechatQr(null);
    void getBillingAvailability()
      .then((result) => {
        if (!active) return;
        setAvailability(result);
        setPaymentState("idle");
        setSelectedPlan((current) => {
          if (!current) return null;
          const authoritative = result.plans.find((plan) => plan.id === current.id);
          return authoritative
            ? {
                id: authoritative.id,
                name: authoritative.name,
                price: authoritative.monthly_price_cny_fen / 100,
                includedCredits: authoritative.included_ai_credits,
                featured: authoritative.id === "plus",
                billingScope: current.billingScope,
                subscriptionKey: subscriptionKey(current.billingScope, authoritative.id),
              }
            : current;
        });
        setPaymentMethod((current) => {
          if (result.methods[current]) return current;
          const availableMethod = (["wechat", "alipay", "card"] as const).find(
            (method) => result.methods[method],
          );
          return availableMethod ?? current;
        });
      })
      .catch((error) => {
        if (!active) return;
        void error;
        setAvailability(null);
        setPaymentState("error");
        setPaymentMessage(copy.availabilityFailed);
      });
    return () => {
      active = false;
    };
  }, [
    copy.availabilityFailed,
    sensitiveCloudActionsEnabled,
  ]);

  useEffect(() => {
    if (!authenticated || !sensitiveCloudActionsEnabled) {
      setCurrentSubscriptionKey("individual-free");
      return undefined;
    }
    let active = true;
    void getManagedModelUsage()
      .then((snapshot) => {
        if (!active) return;
        setCurrentSubscriptionKey(subscriptionKey(
          snapshot.account?.billing_scope ?? "individual",
          snapshot.plan.id,
        ));
      })
      .catch(() => {
        if (active) setCurrentSubscriptionKey("individual-free");
      });
    return () => {
      active = false;
    };
  }, [authenticated, sensitiveCloudActionsEnabled]);

  const plans: readonly Plan[] = availability?.plans.length === 3
    ? availability.plans.map((plan) => ({
        id: plan.id,
        name: plan.name,
        price: plan.monthly_price_cny_fen / 100,
        includedCredits: plan.included_ai_credits,
        featured: plan.id === "plus",
      }))
    : PLANS;
  const displayedPlans: DisplayPlan[] = plans.map((plan) => ({
    ...plan,
    price: audience === "business" && plan.id !== "free"
      ? BUSINESS_SEAT_PRICES[plan.id]
      : plan.price,
    billingScope: audience,
    subscriptionKey: subscriptionKey(audience, plan.id),
  }));

  const choosePlan = (plan: DisplayPlan) => {
    if (!sensitiveCloudActionsEnabled) return;
    if (!authenticated) {
      onRequireAccount();
      return;
    }
    if (plan.id === "free") return;
    capturePaymentTrigger();
    setSelectedPlan(plan);
  };

  const startPayment = async () => {
    if (!sensitiveCloudActionsEnabled) return;
    if (!selectedPlan || selectedPlan.id === "free") return;
    setPaymentState("creating");
    setPaymentMessage(null);
    setWechatQr(null);
    try {
      const order = await createBillingCheckout(
        selectedPlan.id,
        paymentMethod,
        selectedPlan.billingScope,
      );
      if (order.checkout.kind === "redirect") {
        window.location.assign(order.checkout.url);
        return;
      }
      const { default: QRCode } = await import("qrcode");
      setWechatQr(await QRCode.toDataURL(order.checkout.code_url, {
        width: 260,
        margin: 2,
        errorCorrectionLevel: "M",
      }));
      setPaymentState("qr");
    } catch (error) {
      setPaymentState("error");
      setPaymentMessage(
        error instanceof CloudModelAccessError
          ? error.message
          : copy.paymentFailed,
      );
    }
  };

  const selectedMethodAvailable = Boolean(
    availability?.enabled && availability.methods[paymentMethod],
  );
  const availabilityUnavailable = availability === null && paymentState === "error";
  const cardMethodAvailable = Boolean(availability?.methods.card);

  const featureLabel = (feature: FeatureKey, plan: Plan): string => {
    if (feature === "allowance") {
      const credits = formatCredits(locale, plan.includedCredits);
      return audience === "business"
        ? copy.businessAllowanceFeature(credits)
        : copy.allowanceFeature(credits);
    }
    if (audience === "business" && feature in copy.businessFeatures) {
      return copy.businessFeatures[feature as keyof typeof copy.businessFeatures];
    }
    return copy.features[feature];
  };

  const featureIncluded = (feature: FeatureKey, plan: Plan): boolean => {
    const planLevel = { free: 0, plus: 1, pro: 2 }[plan.id];
    const minimumLevel: Record<FeatureKey, number> = {
      workflow: 0,
      harness: 0,
      allowance: 0,
      byok: 0,
      reports: 0,
      comparisonWorkspace: 1,
      watermarkFree: 1,
      premiumRouting: 2,
      advancedHarness: 2,
    };
    return planLevel >= minimumLevel[feature];
  };

  const selectAudienceFromKeyboard = (
    event: KeyboardEvent<HTMLButtonElement>,
    current: Audience,
  ) => {
    let next: Audience | null = null;
    if (
      event.key === "ArrowRight"
      || event.key === "ArrowDown"
      || event.key === "ArrowLeft"
      || event.key === "ArrowUp"
    ) {
      next = current === "individual" ? "business" : "individual";
    } else if (event.key === "Home") {
      next = "individual";
    } else if (event.key === "End") {
      next = "business";
    }
    if (!next) return;
    event.preventDefault();
    setAudience(next);
    (next === "individual" ? individualAudienceRef : businessAudienceRef)
      .current
      ?.focus();
  };

  return (
    <div className="site-portal pricing-page">
      <header className="portal-page-heading">
        <h1 aria-label={copy.title}>
          <span aria-hidden="true" className="portal-title-desktop">{copy.title}</span>
          <span aria-hidden="true" className="portal-title-mobile">
            {copy.mobileTitleLines.map((line) => <span key={line}>{line}</span>)}
          </span>
        </h1>
      </header>
      <div className="pricing-audience" role="tablist" aria-label={copy.audienceLabel}>
        <button
          ref={individualAudienceRef}
          type="button"
          role="tab"
          id="pricing-audience-individual"
          aria-controls="pricing-plans"
          aria-selected={audience === "individual"}
          tabIndex={audience === "individual" ? 0 : -1}
          onClick={() => setAudience("individual")}
          onKeyDown={(event) => selectAudienceFromKeyboard(event, "individual")}
        >
          <Sparkles aria-hidden="true" />
          {copy.individual}
        </button>
        <button
          ref={businessAudienceRef}
          type="button"
          role="tab"
          id="pricing-audience-business"
          aria-controls="pricing-plans"
          aria-selected={audience === "business"}
          tabIndex={audience === "business" ? 0 : -1}
          onClick={() => setAudience("business")}
          onKeyDown={(event) => selectAudienceFromKeyboard(event, "business")}
        >
          <Users aria-hidden="true" />
          {copy.business}
        </button>
      </div>

      <div
        id="pricing-plans"
        className="pricing-grid"
        data-audience={audience}
        role="tabpanel"
        aria-labelledby={`pricing-audience-${audience}`}
      >
        {displayedPlans.map((plan) => (
          <article
            key={plan.id}
            data-plan={plan.id}
            data-subscription={plan.subscriptionKey}
            className={`pricing-card${
              plan.subscriptionKey === currentSubscriptionKey ? " is-current" : ""
            }`}
            aria-current={
              plan.subscriptionKey === currentSubscriptionKey ? "true" : undefined
            }
          >
            {plan.subscriptionKey === currentSubscriptionKey ? (
              <span className="pricing-badge">{copy.currentPlan}</span>
            ) : null}
            <header>
              <h2>{plan.name}</h2>
              <p>
                <strong><span>¥</span>{plan.price}</strong>
                <span>{audience === "business" ? copy.perUserMonth : copy.month}</span>
              </p>
            </header>
            <button
              type="button"
              className={
                plan.subscriptionKey === currentSubscriptionKey
                  ? "is-current-action"
                  : ""
              }
              disabled={
                plan.subscriptionKey === currentSubscriptionKey
                || !sensitiveCloudActionsEnabled
              }
              onClick={() => {
                if (plan.subscriptionKey !== currentSubscriptionKey) choosePlan(plan);
              }}
            >
              {plan.subscriptionKey === currentSubscriptionKey
                ? copy.currentSubscription
                : plan.id === "free"
                  ? copy.start
                  : `${copy.upgrade} ${plan.name}`}
            </button>
            <ul>
              {FEATURE_KEYS.map((feature) => {
                const Icon = FEATURE_ICONS[feature];
                const included = featureIncluded(feature, plan);
                const label = featureLabel(feature, plan);
                return (
                  <li
                    key={feature}
                    aria-label={`${label} — ${
                      included ? copy.includedStatus : copy.unavailableStatus
                    }`}
                    className={`pricing-feature ${
                      included ? "is-included" : "is-unavailable"
                    }`}
                    data-available={included}
                    data-feature={feature}
                  >
                    <span className="pricing-feature-icon">
                      <Icon aria-hidden="true" />
                    </span>
                    <span>{label}</span>
                  </li>
                );
              })}
            </ul>
          </article>
        ))}
      </div>

      {selectedPlan ? (
        <div className="payment-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSelectedPlan(null);
        }}>
          <section
            ref={paymentDialogRef}
            className="payment-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="payment-title"
            tabIndex={-1}
          >
            <header>
              <div>
                <ShieldCheck aria-hidden="true" />
                <h2 id="payment-title">{copy.paymentTitle}</h2>
              </div>
              <button
                ref={paymentCloseRef}
                type="button"
                aria-label={copy.close}
                onClick={() => setSelectedPlan(null)}
              >
                <X aria-hidden="true" />
              </button>
            </header>
            <div className="payment-plan-summary">
              <strong>{selectedPlan.name}</strong>
              <span>
                ¥{selectedPlan.price}{" "}
                {selectedPlan.billingScope === "business" ? copy.perUserMonth : copy.month}
              </span>
            </div>
            <div className={`payment-methods${cardMethodAvailable ? " has-card" : ""}`}>
              <button
                type="button"
                aria-label={copy.wechat}
                aria-pressed={paymentMethod === "wechat"}
                disabled={
                  availabilityUnavailable
                  || (availability ? !availability.methods.wechat : false)
                }
                onClick={() => setPaymentMethod("wechat")}
              >
                <span className="payment-method-logo is-wechat">
                  <PaymentBrandMark brand="wechat-pay" />
                </span>
                {copy.wechat}
              </button>
              <button
                type="button"
                aria-label={copy.alipay}
                aria-pressed={paymentMethod === "alipay"}
                disabled={
                  availabilityUnavailable
                  || (availability ? !availability.methods.alipay : false)
                }
                onClick={() => setPaymentMethod("alipay")}
              >
                <span className="payment-method-logo is-alipay">
                  <PaymentBrandMark brand="alipay" />
                </span>
                {copy.alipay}
              </button>
              {cardMethodAvailable ? (
                <button
                  type="button"
                  aria-label={copy.card}
                  aria-pressed={paymentMethod === "card"}
                  onClick={() => setPaymentMethod("card")}
                >
                  <span className="payment-method-logo is-card">
                    <CreditCard aria-hidden="true" />
                  </span>
                  {copy.card}
                </button>
              ) : null}
            </div>
            {wechatQr ? (
              <div className="payment-qr" role="status">
                <strong>{copy.qrTitle}</strong>
                <img src={wechatQr} alt={copy.qrAlt} />
              </div>
            ) : (
              <button
                type="button"
                className="payment-continue"
                disabled={
                  !selectedMethodAvailable
                  || paymentState === "checking"
                  || paymentState === "creating"
                }
                onClick={() => void startPayment()}
              >
                {copy.continue}
              </button>
            )}
            {paymentMessage ? (
              <p className="payment-state" role="alert">{paymentMessage}</p>
            ) : wechatQr ? (
              <p className="payment-state">{copy.callbackNote}</p>
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}
