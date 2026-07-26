import { Check, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  CloudModelAccessError,
  createBillingCheckout,
  getBillingAvailability,
  type BillingAvailability,
  type PaymentMethod,
} from "../features/settings/cloudModelAccess";

type SiteLocale = "en" | "zh-CN";
type PaidPlanId = "plus" | "pro";

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
  { id: "free", name: "Free", price: 0, includedCredits: 100_000 },
  { id: "plus", name: "Plus", price: 20, includedCredits: 1_000_000, featured: true },
  { id: "pro", name: "Pro", price: 200, includedCredits: 5_000_000 },
];

const pricingContent = {
  en: {
    eyebrow: "DRONEDREAM PLANS",
    title: "The same complete product. More included AI.",
    mobileTitle: "Choose your allowance.",
    intro:
      "Free, Plus, and Pro unlock exactly the same DroneDream software and tuning Harness. Only the included managed-model allowance changes.",
    month: "/ month",
    current: "Free plan",
    start: "Start free",
    upgrade: "Choose",
    recommended: "Recommended",
    included: "included AI credits each month",
    creditsDefinition:
      "Credits are settled from provider-reported input and output tokens under a versioned policy.",
    sharedFeatures: [
      "Complete DroneDream desktop tuning workflow",
      "The same Harness, optimizers, simulation, and reports",
      "Experiment assistant, community, manual, and updates",
      "Use your own API key after the included allowance ends",
      "No platform API key is stored on your computer",
    ],
    close: "Close payment dialog",
    paymentTitle: "Choose a payment method",
    paymentIntro:
      "This purchases one month of the selected allowance. Renewal is manual until wallet auto-renewal is separately activated.",
    wechat: "WeChat Pay",
    alipay: "Alipay",
    continue: "Continue to payment",
    checking: "Checking payment availability…",
    unavailable: "Merchant payment activation is still required.",
    paymentFailed: "The payment order could not be created.",
    qrTitle: "Scan with WeChat to pay",
    qrAlt: "WeChat Pay QR code",
    callbackNote:
      "The plan activates only after DroneDream verifies the payment provider callback.",
  },
  "zh-CN": {
    eyebrow: "DRONEDREAM 套餐",
    title: "完整能力完全相同，只增加赠送 AI 额度。",
    mobileTitle: "选择赠送额度。",
    intro:
      "Free、Plus、Pro 使用完全相同的 DroneDream 软件与调优 Harness；三个级别唯一的能力差异，是每月赠送的托管模型额度。",
    month: "/ 月",
    current: "免费套餐",
    start: "免费开始",
    upgrade: "选择",
    recommended: "推荐",
    included: "每月赠送 AI 额度",
    creditsDefinition:
      "额度依据模型服务商返回的输入、输出 token，并按版本化规则精确结算。",
    sharedFeatures: [
      "完整的 DroneDream 桌面调优工作流",
      "相同的 Harness、优化器、仿真与报告能力",
      "相同的实验助手、社区、说明书与更新",
      "赠送额度耗尽后可切换到自己的 API Key",
      "DroneDream 平台密钥不会保存到用户电脑",
    ],
    close: "关闭支付弹窗",
    paymentTitle: "选择付款方式",
    paymentIntro:
      "本次购买一个月的对应额度；在钱包自动续费能力另行签约前，到期后由用户手动续费。",
    wechat: "微信支付",
    alipay: "支付宝",
    continue: "继续付款",
    checking: "正在检查支付渠道…",
    unavailable: "仍需完成商户支付能力开通。",
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
          const availableMethod = (["wechat", "alipay"] as const).find(
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
        setPaymentMessage(copy.unavailable);
      });
    return () => {
      active = false;
    };
  }, [copy.unavailable]);

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

      <div className="pricing-grid">
        {plans.map((plan) => (
          <article
            key={plan.id}
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
            <div className="pricing-allowance">
              <strong>{formatCredits(locale, plan.includedCredits)}</strong>
              <span>{copy.included}</span>
            </div>
            <button
              type="button"
              className={plan.featured ? "is-primary" : ""}
              onClick={() => choosePlan(plan)}
            >
              {plan.id === "free" ? copy.start : `${copy.upgrade} ${plan.name}`}
            </button>
            <ul>
              {copy.sharedFeatures.map((feature) => (
                <li key={feature}><Check aria-hidden="true" /><span>{feature}</span></li>
              ))}
            </ul>
          </article>
        ))}
      </div>
      <p className="pricing-credit-definition">{copy.creditsDefinition}</p>

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
              <span>¥{selectedPlan.price} {copy.month}</span>
            </div>
            <div className="payment-methods">
              <button
                type="button"
                aria-label={copy.wechat}
                aria-pressed={paymentMethod === "wechat"}
                disabled={availability ? !availability.methods.wechat : false}
                onClick={() => setPaymentMethod("wechat")}
              >
                <span className="payment-method-logo is-wechat">微</span>
                {copy.wechat}
              </button>
              <button
                type="button"
                aria-label={copy.alipay}
                aria-pressed={paymentMethod === "alipay"}
                disabled={availability ? !availability.methods.alipay : false}
                onClick={() => setPaymentMethod("alipay")}
              >
                <span className="payment-method-logo is-alipay">支</span>
                {copy.alipay}
              </button>
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
            <p className="payment-state">
              {paymentState === "checking"
                ? copy.checking
                : paymentMessage
                  ?? (!selectedMethodAvailable ? copy.unavailable : copy.callbackNote)}
            </p>
          </section>
        </div>
      ) : null}
    </div>
  );
}
