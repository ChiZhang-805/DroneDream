import {
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useState } from "react";

import {
  primaryEditionIds,
  type EditionAvailabilityDocument,
  type PrimaryEditionId,
} from "./editionAvailability";
import { editionBrandAssets } from "./editionBrandAssets";
import {
  buildEditionReleaseRegistry,
  getEditionRelease,
} from "./editionReleaseRegistry";

type Locale = "en" | "zh-CN";

type ProductCopy = {
  title: string;
  download: string;
  downloadUnavailable: string;
  previousShot: string;
  nextShot: string;
  editions: Record<PrimaryEditionId, {
    title: string;
    features: string[];
    screenshots: {
      alt: string;
      src: string;
    }[];
  }>;
};

const copy: Record<Locale, ProductCopy> = {
  en: {
    title: "Choose Your DroneDream Edition",
    download: "Download",
    downloadUnavailable: "Download unavailable",
    previousShot: "Previous screenshot",
    nextShot: "Next screenshot",
    editions: {
      sim: {
        title: "DroneDream · SIM",
        features: [
          "Simulation-only tests",
          "Autonomous search",
          "Parameter candidates",
          "Scenario replay",
          "Budgeted runs",
          "Telemetry metrics",
          "Failure diagnosis",
          "Holdout evidence",
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
          "Sim-to-Real checks",
          "Real-to-Sim updates",
          "Calibration workflow",
          "Mismatch diagnosis",
          "Qualification review",
          "Controlled trials",
          "Evidence handoff",
          "Receipt comparison",
          "Lab safety gates",
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
          "Real vehicle setup",
          "Field tuning runs",
          "Operator safety bounds",
          "Live telemetry review",
          "Trial snapshot rollback",
          "On-site diagnostics",
          "Parameter application",
          "Evidence upload",
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
    download: "下载",
    downloadUnavailable: "暂不可下载",
    previousShot: "上一张截图",
    nextShot: "下一张截图",
    editions: {
      sim: {
        title: "DroneDream · SIM",
        features: [
          "纯仿真测试",
          "自主参数搜索",
          "候选参数对比",
          "场景复现实验",
          "预算约束运行",
          "遥测指标复核",
          "失败原因诊断",
          "留出验证证据",
          "不控制真机",
        ],
        screenshots: [
          { src: "/docs/zh-CN/flight-setup.png", alt: "SIM 飞行设置页面" },
          { src: "/docs/zh-CN/tuning-chat.png", alt: "SIM 调优对话页面" },
          { src: "/docs/zh-CN/dashboard.png", alt: "SIM 证据看板" },
        ],
      },
      lab: {
        title: "DroneDream · LAB",
        features: [
          "仿真到真机校验",
          "真机到仿真更新",
          "校准工作流程",
          "模型差距诊断",
          "资格证据复核",
          "受控试验验证",
          "参数交接证据",
          "试验回执对比",
          "实验室安全门",
        ],
        screenshots: [
          { src: "/docs/zh-CN/dashboard.png", alt: "LAB 证据看板" },
          { src: "/docs/zh-CN/flight-setup.png", alt: "LAB 验证设置页面" },
          { src: "/docs/zh-CN/tuning-chat.png", alt: "LAB 校准复核页面" },
        ],
      },
      field: {
        title: "DroneDream · FIELD",
        features: [
          "真机接入设置",
          "现场调参运行",
          "操作员安全边界",
          "实时遥测复核",
          "试验快照回滚",
          "现场诊断记录",
          "参数应用流程",
          "证据上传归档",
          "没有仿真阶段",
        ],
        screenshots: [
          { src: "/docs/zh-CN/dashboard.png", alt: "FIELD 遥测看板" },
          { src: "/docs/zh-CN/flight-setup.png", alt: "FIELD 试验设置页面" },
          { src: "/docs/zh-CN/tuning-chat.png", alt: "FIELD 参数复核页面" },
        ],
      },
    },
  },
};

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v11m0 0 4-4m-4 4-4-4M5 20h14" />
    </svg>
  );
}

function ScreenshotCarousel({
  id,
  locale,
  screenshots,
}: {
  id: PrimaryEditionId;
  locale: Locale;
  screenshots: ProductCopy["editions"][PrimaryEditionId]["screenshots"];
}) {
  const text = copy[locale];
  const [active, setActive] = useState(0);
  const screenshot = screenshots[active];
  const show = (offset: number) => {
    setActive((current) => (current + offset + screenshots.length) % screenshots.length);
  };

  return (
    <div className="site-product-screenshots" data-screenshot-edition={id}>
      <button
        type="button"
        aria-label={`${text.previousShot} ${copy[locale].editions[id].title}`}
        onClick={() => show(-1)}
      >
        <ChevronLeft aria-hidden="true" />
      </button>
      <img src={screenshot.src} alt={screenshot.alt} />
      <button
        type="button"
        aria-label={`${text.nextShot} ${copy[locale].editions[id].title}`}
        onClick={() => show(1)}
      >
        <ChevronRight aria-hidden="true" />
      </button>
    </div>
  );
}

export function ProductPage({
  availability,
  locale,
  softwareDownloadsEnabled = false,
}: {
  availability: EditionAvailabilityDocument;
  locale: Locale;
  softwareDownloadsEnabled?: boolean;
}) {
  const text = copy[locale];
  const registry = buildEditionReleaseRegistry(availability);
  const editions = primaryEditionIds.map((id) => {
    const release = getEditionRelease(registry, id);
    return { id, release, text: text.editions[id] };
  });

  return (
    <section className="site-product-page" aria-labelledby="site-product-title">
      <div className="site-product-page-shell">
        <header className="site-product-page-header">
          <h1 id="site-product-title">{text.title}</h1>
        </header>

        <div className="site-product-page-grid">
          {editions.map(({ id, release, text: editionText }) => {
            const brandAssets = editionBrandAssets[id];
            const titleId = `site-product-${release.id}-title`;
            const downloadLabel = `${editionText.title} ${text.download}`;
            return (
              <article
                aria-labelledby={titleId}
                className="site-product-edition"
                data-download-ready={release.downloadReady ? "true" : "false"}
                data-edition={release.id}
                data-release-registry="exact-edition-exe-v1"
                key={release.id}
              >
                <div className="site-product-edition-topline">
                  <picture
                    data-brand-handoff="universal-canonical-brand-donor-v1.1.0"
                    data-brand-surface="product-card"
                    className="site-product-edition-picture"
                  >
                    <source
                      data-brand-asset="lockup"
                      height={brandAssets.lockupHeight}
                      media="(min-width: 1161px)"
                      srcSet={brandAssets.lockup}
                      width={brandAssets.lockupWidth}
                    />
                    <img
                      alt=""
                      aria-hidden="true"
                      className="site-product-edition-icon"
                      data-brand-asset="mark"
                      height="1024"
                      src={brandAssets.mark}
                      width="1024"
                    />
                  </picture>
                  {softwareDownloadsEnabled && release.downloadReady && release.downloadUrl ? (
                    <a
                      aria-label={downloadLabel}
                      className="site-product-edition-action"
                      href={release.downloadUrl}
                      download={release.artifact.fileName}
                    >
                      <DownloadIcon />
                      {text.download}
                    </a>
                  ) : (
                    <button
                      type="button"
                      aria-label={`${editionText.title} ${text.downloadUnavailable}`}
                      className="site-product-edition-action"
                      disabled
                    >
                      <DownloadIcon />
                      {text.download}
                    </button>
                  )}
                </div>
                <h2 id={titleId}>{editionText.title}</h2>
                <ul>
                  {editionText.features.map((feature) => <li key={feature}>{feature}</li>)}
                </ul>
                <ScreenshotCarousel
                  id={id}
                  locale={locale}
                  screenshots={editionText.screenshots}
                />
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
