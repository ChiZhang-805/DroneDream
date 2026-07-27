import {
  BrainCircuit,
  CreditCard,
  FileOutput,
  Gauge,
  KeyRound,
  ShieldCheck,
  Sparkles,
  Stamp,
  Users,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { PaymentBrandMark } from "../components/PaymentBrandMark";
import {
  CloudModelAccessError,
  createBillingCheckout,
  getBillingAvailability,
  type BillingAvailability,
  type PaymentMethod,
} from "../features/settings/cloudModelAccess";

type SiteLocale = "en" | "zh-CN";
type PaidPlanId = "plus" | "pro";
type Audience = "individual" | "business";
type FeatureKey =
  | "workflow"
  | "harness"
  | "allowance"
  | "byok"
  | "reports"
  | "watermarkFree";

interface PricingPageProps {
  locale: SiteLocale;
  authenticated: boolean;
  onRequireAccount: () => void;
}

interface Plan {
  id: "free" | PaidPlanId;
  name: string;
  price: number;
  includedCredits: number;
  featured?: boolean;
}

const PLANS: readonly Plan[] = [
  { id: "free", name: "Free", price: 0, includedCredits: 300_000 },
  { id: "plus", name: "Plus", price: 39, includedCredits: 3_000_000, featured: true },
  { id: "pro", name: "Pro", price: 129, includedCredits: 15_000_000 },
];

const FEATURE_KEYS: readonly FeatureKey[] = [
  "workflow",
  "harness",
  "allowance",
  "byok",
  "reports",
  "watermarkFree",
];

const FEATURE_ICONS: Record<FeatureKey, LucideIcon> = {
  workflow: Workflow,
  harness: BrainCircuit,
  allowance: Gauge,
  byok: KeyRound,
  reports: FileOutput,
  watermarkFree: Stamp,
};

const pricingContent = {
  en: {
    title: "The same complete product. More included AI.",
    mobileTitle: "Choose your allowance.",
    audienceLabel: "Workspace type",
    individual: "Individual",
    business: "Business",
    month: "/ month",
    current: "Free plan",
    start: "Start free",
    upgrade: "Choose",
    recommended: "Recommended",
    includedStatus: "Included",
    unavailableStatus: "Not included",
    features: {
      workflow: "Complete DroneDream tuning workflow",
      harness: "Full AURORA optimization Harness",
      byok: "BYOK fallback after the included allowance",
      reports: "Experiment and comparison report export",
      watermarkFree: "Watermark-free PDF report export",
    },
    allowanceFeature: (credits: string) => `${credits} managed AI credits each month`,
    close: "Close payment dialog",
    paymentTitle: "Payment",
    wechat: "WeChat Pay",
    alipay: "Alipay",
    card: "Credit or debit card",
    continue: "Continue to payment",
    paymentFailed: "The payment order could not be created.",
    qrTitle: "Scan with WeChat to pay",
    qrAlt: "WeChat Pay QR code",
    callbackNote:
      "The plan activates only after DroneDream verifies the payment provider callback.",
  },
  "zh-CN": {
    title: "完整能力完全相同，只增加赠送 AI 额度。",
    mobileTitle: "选择赠送额度。",
    audienceLabel: "工作空间类型",
    individual: "个人",
    business: "商业",
    month: "/ 月",
    current: "免费套餐",
    start: "免费开始",
    upgrade: "选择",
    recommended: "推荐",
    includedStatus: "已包含",
    unavailableStatus: "未包含",
    features: {
      workflow: "完整的 DroneDream 调优工作流",
      harness: "完整的 AURORA 优化 Harness",
      byok: "赠送额度用尽后切换到自己的 API Key",
      reports: "导出实验与对比报告",
      watermarkFree: "导出无水印 PDF 报告",
    },
    allowanceFeature: (credits: string) => `每月 ${credits} 托管模型 AI 额度`,
    close: "关闭支付弹窗",
    paymentTitle: "支付",
    wechat: "微信支付",
    alipay: "支付宝",
    card: "信用卡或借记卡",
    continue: "继续付款",
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
}: PricingPageProps) {
  const copy = pricingContent[locale];
  const [audience, setAudience] = useState<Audience>("individual");
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("wechat");
  const [availability, setAvailability] = useState<BillingAvailability | null>(null);
  const [paymentState, setPaymentState] =
    useState<"idle" | "checking" | "creating" | "qr" | "error">("idle");
  const [paymentMessage, setPaymentMessage] = useState<string | null>(null);
  const [wechatQr, setWechatQr] = useState<string | null>(null);

  useEffect(() => {
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
        setPaymentMessage(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const plans: readonly Plan[] = availability?.plans.length === 3
    ? availability.plans.map((plan) => ({
        id: plan.id,
        name: plan.name,
        price: plan.monthly_price_cny_fen / 100,
        includedCredits: plan.included_ai_credits,
        featured: plan.id === "plus",
      }))
    : PLANS;

  const choosePlan = (plan: Plan) => {
    if (!authenticated) {
      onRequireAccount();
      return;
    }
    if (plan.id === "free") return;
    setSelectedPlan(plan);
  };

  const startPayment = async () => {
    if (!selectedPlan || selectedPlan.id === "free") return;
    setPaymentState("creating");
    setPaymentMessage(null);
    setWechatQr(null);
    try {
      const order = await createBillingCheckout(selectedPlan.id, paymentMethod);
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
  const cardMethodAvailable = Boolean(availability?.methods.card);

  const featureLabel = (feature: FeatureKey, plan: Plan): string => {
    if (feature === "allowance") {
      return copy.allowanceFeature(formatCredits(locale, plan.includedCredits));
    }
    return copy.features[feature];
  };

  const featureIncluded = (feature: FeatureKey, plan: Plan): boolean =>
    feature !== "watermarkFree" || plan.id !== "free";

  return (
    <div className="site-portal pricing-page">
      <header className="portal-page-heading">
        <h1 aria-label={copy.title}>
          <span aria-hidden="true" className="portal-title-desktop">{copy.title}</span>
          <span aria-hidden="true" className="portal-title-mobile">{copy.mobileTitle}</span>
        </h1>
      </header>

      <div className="pricing-audience" role="tablist" aria-label={copy.audienceLabel}>
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

      <div className="pricing-grid" data-audience={audience}>
        {plans.map((plan) => (
          <article
            key={plan.id}
            data-plan={plan.id}
            className={`pricing-card${plan.featured ? " is-featured" : ""}`}
          >
            {plan.featured ? <span className="pricing-badge">{copy.recommended}</span> : null}
            <header>
              <h2>{plan.name}</h2>
              <p>
                <strong><span>¥</span>{plan.price}</strong>
                <span>{copy.month}</span>
              </p>
            </header>
            <button
              type="button"
              className={plan.featured ? "is-primary" : ""}
              onClick={() => choosePlan(plan)}
            >
              {plan.id === "free" ? copy.start : `${copy.upgrade} ${plan.name}`}
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
            <div className="payment-plan-summary">
              <strong>{selectedPlan.name}</strong>
              <span>¥{selectedPlan.price} {copy.month}</span>
            </div>
            <div className={`payment-methods${cardMethodAvailable ? " has-card" : ""}`}>
              <button
                type="button"
                aria-label={copy.wechat}
                aria-pressed={paymentMethod === "wechat"}
                disabled={availability ? !availability.methods.wechat : false}
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
                disabled={availability ? !availability.methods.alipay : false}
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
