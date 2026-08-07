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
        audience: "Controlled simulation and integration evidence review",
        features: ["Simulation workflow", "Controlled review", "Lab evidence handoff"],
      },
      field: {
        title: "DroneDream · FIELD",
        audience: "Evidence review for advanced field preparation",
        features: ["Readiness evidence", "Safety gates", "Operator review"],
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
        audience: "面向受控仿真与集成证据审查",
        features: ["仿真流程", "受控复核", "实验室证据交接"],
      },
      field: {
        title: "DroneDream · FIELD",
        audience: "面向高级现场准备的证据审查",
        features: ["就绪证据", "安全门禁", "操作员复核"],
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
            return (
              <article
                aria-labelledby={titleId}
                className="site-product-edition"
                data-download-ready={release.downloadReady ? "true" : "false"}
                data-edition={release.id}
                data-release-registry="exact-edition-exe-v1"
                key={release.id}
              >
                <div className="site-product-edition-brand">
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
                  <h2 id={titleId}>{editionText.title}</h2>
                </div>
                <p className="site-product-edition-audience">{editionText.audience}</p>
                <ul>
                  {editionText.features.map((feature) => <li key={feature}>{feature}</li>)}
                </ul>
                {softwareDownloadsEnabled && release.downloadReady && release.downloadUrl ? (
                  <a
                    className="site-product-edition-action"
                    href={release.downloadUrl}
                    download={release.artifact.fileName}
                  >
                    <DownloadIcon />
                    {release.artifact.fileName}
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
