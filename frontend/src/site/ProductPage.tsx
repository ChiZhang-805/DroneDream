import {
  isEditionDownloadReady,
  primaryEditionIds,
  type EditionAvailabilityDocument,
  type PrimaryEditionId,
} from "./editionAvailability";

type Locale = "en" | "zh-CN";

type ProductCopy = {
  title: string;
  editions: Record<PrimaryEditionId, {
    title: string;
    audience: string;
    features: [string, string, string];
  }>;
};

const copy: Record<Locale, ProductCopy> = {
  en: {
    title: "DroneDream Editions",
    editions: {
      sim: {
        title: "DroneDream · SIM",
        audience: "PX4 / Gazebo simulation and parameter research",
        features: ["Simulation tuning", "Evidence review", "Isolated runtime"],
      },
      lab: {
        title: "DroneDream · LAB",
        audience: "Controlled simulation and vehicle lab integration",
        features: ["Sim + vehicle workflow", "Controlled trials", "Lab handoff"],
      },
      field: {
        title: "DroneDream · FIELD",
        audience: "Guarded execution for advanced field operations",
        features: ["Vehicle execution", "Safety gates", "Operator review"],
      },
    },
  },
  "zh-CN": {
    title: "DroneDream 专业版本",
    editions: {
      sim: {
        title: "DroneDream · SIM",
        audience: "面向 PX4 / Gazebo 仿真与参数研究",
        features: ["仿真调优", "证据审查", "隔离运行环境"],
      },
      lab: {
        title: "DroneDream · LAB",
        audience: "面向受控仿真与真机实验室联调",
        features: ["仿真与真机", "受控试验", "实验室交接"],
      },
      field: {
        title: "DroneDream · FIELD",
        audience: "面向高级现场任务的受控执行",
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
  locale,
}: {
  availability: EditionAvailabilityDocument;
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
          <h1 id="site-product-title">{text.title}</h1>
        </header>

        <div className="site-product-page-grid">
          {editions.map(({ edition, text: editionText }) => {
            const ready = isEditionDownloadReady(edition);
            const titleId = `site-product-${edition.id}-title`;
            return (
              <article
                aria-labelledby={titleId}
                className="site-product-edition"
                data-download-ready={ready ? "true" : "false"}
                data-edition={edition.id}
                key={edition.id}
              >
                <div className="site-product-edition-brand">
                  <div
                    aria-hidden="true"
                    className="site-product-edition-icon"
                    data-icon-donor="pending"
                  />
                  <h2 id={titleId}>{editionText.title}</h2>
                </div>
                <p className="site-product-edition-audience">{editionText.audience}</p>
                <ul>
                  {editionText.features.map((feature) => <li key={feature}>{feature}</li>)}
                </ul>
                {ready && edition.downloadUrl ? (
                  <a className="site-product-edition-action" href={edition.downloadUrl} download={edition.fileName}>
                    <DownloadIcon />
                    {edition.fileName}
                  </a>
                ) : null}
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
