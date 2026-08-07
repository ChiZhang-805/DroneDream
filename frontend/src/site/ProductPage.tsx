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
    features: [string, string, string, string, string];
  }>;
};

const copy: Record<Locale, ProductCopy> = {
  en: {
    title: "Choose Your DroneDream Edition",
    editions: {
      sim: {
        title: "DroneDream · SIM",
        features: [
          "Pure simulation",
          "Autonomous tuning",
          "Candidate parameters",
          "Holdout evidence",
          "No real vehicle",
        ],
      },
      lab: {
        title: "DroneDream · LAB",
        features: [
          "Sim-to-Real",
          "Real-to-Sim",
          "Calibration",
          "Qualification evidence",
          "Controlled trials",
        ],
      },
      field: {
        title: "DroneDream · FIELD",
        features: [
          "Real vehicle",
          "Field tuning",
          "Safety bounds",
          "Telemetry feedback",
          "Snapshot rollback",
        ],
      },
    },
  },
  "zh-CN": {
    title: "选择你的 DroneDream 版本",
    editions: {
      sim: {
        title: "DroneDream · SIM",
        features: ["纯仿真", "自主调优", "候选参数", "留出验证", "不触真机"],
      },
      lab: {
        title: "DroneDream · LAB",
        features: ["仿真到真机", "真机到仿真", "模型校准", "资格证据", "受控试验"],
      },
      field: {
        title: "DroneDream · FIELD",
        features: ["真实设备", "现场调参", "安全边界", "遥测反馈", "快照回滚"],
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
