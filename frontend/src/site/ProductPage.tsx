import { ChevronLeft, ChevronRight, Download } from "lucide-react";
import { useState } from "react";

import {
  primaryEditionIds,
  type EditionAvailabilityDocument,
  type PrimaryEditionId,
} from "./editionAvailability";
import { editionBrandAssets } from "./editionBrandAssets";

type Locale = "en" | "zh-CN";

type EditionCopy = {
  title: string;
  features: readonly string[];
  screenshots: readonly { src: string; alt: string }[];
};

const copy: Record<Locale, {
  title: string;
  subtitle: string;
  download: string;
  unavailable: string;
  previous: string;
  next: string;
  editions: Record<PrimaryEditionId, EditionCopy>;
}> = {
  en: {
    title: "Choose Your DroneDream Edition",
    subtitle: "Three focused editions cover simulation search, lab validation, and controlled field tuning.",
    download: "Download",
    unavailable: "Download unavailable",
    previous: "Previous screenshot",
    next: "Next screenshot",
    editions: {
      sim: {
        title: "DroneDream · SIM",
        features: [
          "Simulation-only test loops",
          "Autonomous parameter search",
          "Scenario replay scoring",
          "Telemetry failure metrics",
          "Holdout evidence review",
          "No real vehicle control",
        ],
        screenshots: [
          { src: "/docs/en/flight-setup.png", alt: "SIM flight setup page" },
          { src: "/docs/en/tuning-chat.png", alt: "SIM tuning chat page" },
          { src: "/docs/en/dashboard.png", alt: "SIM evidence dashboard" },
        ],
      },
      lab: {
        title: "DroneDream · LAB",
        features: [
          "Sim-to-Real calibration",
          "Real-to-Sim model updates",
          "Mismatch diagnosis workflow",
          "Qualification evidence review",
          "Controlled trial receipts",
          "Lab safety gate checks",
        ],
        screenshots: [
          { src: "/docs/en/dashboard.png", alt: "LAB evidence dashboard" },
          { src: "/docs/en/flight-setup.png", alt: "LAB validation setup page" },
          { src: "/docs/en/tuning-chat.png", alt: "LAB calibration review page" },
        ],
      },
      field: {
        title: "DroneDream · FIELD",
        features: [
          "Real vehicle setup flow",
          "Field tuning run control",
          "Operator safety boundaries",
          "Live telemetry review",
          "Trial snapshot rollback",
          "No simulation stage",
        ],
        screenshots: [
          { src: "/docs/en/dashboard.png", alt: "FIELD telemetry dashboard" },
          { src: "/docs/en/flight-setup.png", alt: "FIELD trial setup page" },
          { src: "/docs/en/tuning-chat.png", alt: "FIELD parameter review page" },
        ],
      },
    },
  },
  "zh-CN": {
    title: "选择你的 DroneDream 版本",
    subtitle: "三个版本分别覆盖仿真搜索、实验验证和受控真机现场调参。",
    download: "下载",
    unavailable: "暂不可下载",
    previous: "上一张截图",
    next: "下一张截图",
    editions: {
      sim: {
        title: "DroneDream · SIM",
        features: ["纯仿真测试闭环", "自主参数搜索对比", "场景复现实验记录", "遥测指标评分", "失败原因诊断", "不连接控制真机"],
        screenshots: [
          { src: "/docs/zh-CN/flight-setup.png", alt: "SIM 飞行设置页面" },
          { src: "/docs/zh-CN/tuning-chat.png", alt: "SIM 调优对话页面" },
          { src: "/docs/zh-CN/dashboard.png", alt: "SIM 证据看板" },
        ],
      },
      lab: {
        title: "DroneDream · LAB",
        features: ["仿真到真机校准", "真机到仿真更新", "模型差距诊断", "资格证据审核", "受控试验验证", "实验安全门控"],
        screenshots: [
          { src: "/docs/zh-CN/dashboard.png", alt: "LAB 证据看板" },
          { src: "/docs/zh-CN/flight-setup.png", alt: "LAB 验证设置页面" },
          { src: "/docs/zh-CN/tuning-chat.png", alt: "LAB 校准复核页面" },
        ],
      },
      field: {
        title: "DroneDream · FIELD",
        features: ["真机接入设置", "现场调参运行", "操作员安全边界", "实时遥测复核", "试验快照回滚", "没有仿真阶段"],
        screenshots: [
          { src: "/docs/zh-CN/dashboard.png", alt: "FIELD 遥测看板" },
          { src: "/docs/zh-CN/flight-setup.png", alt: "FIELD 试验设置页面" },
          { src: "/docs/zh-CN/tuning-chat.png", alt: "FIELD 参数复核页面" },
        ],
      },
    },
  },
};

function ScreenshotCarousel({
  edition,
  locale,
  screenshots,
}: {
  edition: PrimaryEditionId;
  locale: Locale;
  screenshots: EditionCopy["screenshots"];
}) {
  const [active, setActive] = useState(0);
  const labels = copy[locale];
  const show = (offset: number) => {
    setActive((current) => (current + offset + screenshots.length) % screenshots.length);
  };
  return (
    <div className="site-product-screenshots" data-screenshot-edition={edition}>
      <button type="button" aria-label={`${labels.previous} ${labels.editions[edition].title}`} onClick={() => show(-1)}>
        <ChevronLeft aria-hidden="true" />
      </button>
      <img src={screenshots[active].src} alt={screenshots[active].alt} />
      <button type="button" aria-label={`${labels.next} ${labels.editions[edition].title}`} onClick={() => show(1)}>
        <ChevronRight aria-hidden="true" />
      </button>
    </div>
  );
}

export function ProductPage({
  availability,
  locale,
}: {
  availability: EditionAvailabilityDocument;
  locale: Locale;
}) {
  const text = copy[locale];
  return (
    <section className="site-product-page" aria-labelledby="site-product-title">
      <div className="site-product-page-shell">
        <header className="site-product-page-header">
          <h1 id="site-product-title">{text.title}</h1>
          <p>{text.subtitle}</p>
        </header>
        <div className="site-product-page-grid">
          {primaryEditionIds.map((id) => {
            const edition = availability.editions.find((candidate) => candidate.id === id);
            if (!edition) return null;
            const editionText = text.editions[id];
            const brand = editionBrandAssets[id];
            const published = edition.status === "published" && edition.downloadUrl;
            return (
              <article
                className="site-product-edition"
                data-download-ready={published ? "true" : "false"}
                data-edition={id}
                key={id}
              >
                <div className="site-product-edition-topline">
                  <picture className="site-product-edition-picture">
                    <source media="(min-width: 1161px)" srcSet={brand.lockup} />
                    <img className="site-product-edition-icon" src={brand.mark} alt="" aria-hidden="true" />
                  </picture>
                  {published ? (
                    <a className="site-product-edition-action" href={edition.downloadUrl!} download={edition.fileName} aria-label={`${editionText.title} ${text.download}`}>
                      <Download aria-hidden="true" />
                      {text.download}
                    </a>
                  ) : (
                    <button className="site-product-edition-action" type="button" disabled aria-label={`${editionText.title} ${text.unavailable}`}>
                      <Download aria-hidden="true" />
                      {text.download}
                    </button>
                  )}
                </div>
                <h2>{editionText.title}</h2>
                <ul>{editionText.features.map((feature) => <li key={feature}>{feature}</li>)}</ul>
                <ScreenshotCarousel edition={id} locale={locale} screenshots={editionText.screenshots} />
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
