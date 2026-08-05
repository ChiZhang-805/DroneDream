import {
  isEditionDownloadReady,
  primaryEditionIds,
  type EditionAvailabilityDocument,
  type PrimaryEditionId,
} from "./editionAvailability";
import type { WebsiteRelease } from "./release";

type Locale = "en" | "zh-CN";

type ProductCopy = {
  eyebrow: string;
  title: string;
  intro: string;
  status: string;
  comingSoon: string;
  currentTitle: string;
  currentBody: string;
  currentAction: string;
  editions: Record<PrimaryEditionId, {
    title: string;
    audience: string;
    features: [string, string, string];
  }>;
};

const copy: Record<Locale, ProductCopy> = {
  en: {
    eyebrow: "DRONEDREAM PRODUCTS",
    title: "Choose the workspace built for your flight.",
    intro: "Three focused editions separate simulation, lab integration, and field operation.",
    status: "In preparation",
    comingSoon: "Coming soon",
    currentTitle: "Current internal preview",
    currentBody: "The existing unsigned 1.0.0 preview remains available while these editions are prepared.",
    currentAction: "Download current preview",
    editions: {
      sim: {
        title: "DroneDream Sim",
        audience: "For PX4 / Gazebo simulation studies",
        features: ["Simulation tuning", "Evidence review", "Local Runtime"],
      },
      lab: {
        title: "DroneDream Lab",
        audience: "For simulation and hardware laboratories",
        features: ["Sim + vehicle workflow", "Controlled trials", "Lab handoff"],
      },
      field: {
        title: "DroneDream Field",
        audience: "For advanced field operations",
        features: ["Vehicle execution", "Safety gates", "Operator review"],
      },
    },
  },
  "zh-CN": {
    eyebrow: "DRONEDREAM 产品",
    title: "选择适合你的飞行工作空间",
    intro: "三款专用版本分别面向仿真研究、实验室联调与真机作业。",
    status: "正在准备",
    comingSoon: "即将推出",
    currentTitle: "当前内测预览版",
    currentBody: "三款专用版本准备期间，现有未签名 1.0.0 内测预览版仍可单独下载。",
    currentAction: "下载当前预览版",
    editions: {
      sim: {
        title: "DroneDream 仿真版",
        audience: "适合 PX4 / Gazebo 仿真研究",
        features: ["仿真调优", "证据审查", "本地 Runtime"],
      },
      lab: {
        title: "DroneDream 实验室版",
        audience: "适合仿真与真机联合实验",
        features: ["仿真与真机", "受控试验", "实验室交接"],
      },
      field: {
        title: "DroneDream 真机版",
        audience: "适合高级真机现场作业",
        features: ["真机执行", "安全门禁", "操作员复核"],
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

export function ProductPage({
  availability,
  currentRelease,
  locale,
}: {
  availability: EditionAvailabilityDocument;
  currentRelease: WebsiteRelease;
  locale: Locale;
}) {
  const text = copy[locale];
  const editions = primaryEditionIds.map((id) => {
    const edition = availability.editions.find((candidate) => candidate.id === id);
    if (!edition) throw new Error(`Missing required edition metadata: ${id}`);
    return { edition, text: text.editions[id] };
  });

  return (
    <section className="site-product-page" aria-labelledby="site-product-title">
      <div className="site-product-page-shell">
        <header className="site-product-page-header">
          <p className="site-eyebrow">{text.eyebrow}</p>
          <h1 id="site-product-title">{text.title}</h1>
          <p>{text.intro}</p>
        </header>

        <div className="site-product-page-grid">
          {editions.map(({ edition, text: editionText }) => {
            const ready = isEditionDownloadReady(edition);
            return (
              <article className="site-product-edition" key={edition.id} data-edition={edition.id}>
                <div className="site-product-edition-heading">
                  <h2>{editionText.title}</h2>
                  <span>{ready ? edition.version : text.status}</span>
                </div>
                <p className="site-product-edition-audience">{editionText.audience}</p>
                <div className="site-product-edition-visual" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
                <ul>
                  {editionText.features.map((feature) => <li key={feature}>{feature}</li>)}
                </ul>
                {ready && edition.downloadUrl ? (
                  <a className="site-product-edition-action" href={edition.downloadUrl} download={edition.fileName}>
                    <DownloadIcon />
                    {edition.fileName}
                  </a>
                ) : (
                  <button className="site-product-edition-action" type="button" disabled>
                    {text.comingSoon}
                  </button>
                )}
              </article>
            );
          })}
        </div>

        <aside className="site-product-current" aria-label={text.currentTitle}>
          <div>
            <strong>{text.currentTitle}</strong>
            <span>{text.currentBody}</span>
          </div>
          <a href={currentRelease.downloadUrl} download={currentRelease.fileName}>
            <DownloadIcon />
            {text.currentAction}
          </a>
        </aside>
      </div>
    </section>
  );
}
