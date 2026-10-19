import type { CSSProperties } from "react";
import { Check, Download } from "lucide-react";

import universalLockup from "../../../brand/icons/universal-lockup.png";
import {
  type EditionAvailabilityId,
  type EditionAvailabilityDocument,
} from "./editionAvailability";
import { editionBrandAssets } from "./editionBrandAssets";
import type { WebsiteRelease } from "./release";

type Locale = "en" | "zh-CN";

type ProductDefinition = {
  id: "universal" | EditionAvailabilityId;
  name: string;
  summary: string;
  features: readonly string[];
};

const products: readonly ProductDefinition[] = [
  {
    id: "universal",
    name: "Universal",
    summary: "Move from repeatable simulation to hardware validation, field operations, and natural-language missions without leaving the same workspace.",
    features: [
      "All five workspaces",
      "One local Runtime",
      "Shared aircraft and maps",
      "Shared projects and run history",
      "Consistent account and settings",
      "Edition-aware updates and downloads",
      "One installer for the complete suite",
    ],
  },
  {
    id: "sim",
    name: "SIM",
    summary: "Build repeatable PX4 and Gazebo flights, compare controls, and replay scenarios locally.",
    features: ["PX4 and Gazebo", "Scenario replay", "Parameter exploration"],
  },
  {
    id: "lab",
    name: "LAB",
    summary: "Connect simulation, hardware trials, sensor integration, and calibration in one workspace.",
    features: ["Hardware in the loop", "Sensor integration", "Model calibration"],
  },
  {
    id: "field",
    name: "FIELD",
    summary: "Configure aircraft, follow live telemetry, and manage field operations in one workspace.",
    features: ["Vehicle setup", "Live telemetry", "Operator controls"],
  },
  {
    id: "autonomy",
    name: "AGENT",
    summary: "Describe missions in everyday language, map each route, and follow the aircraft live.",
    features: ["Natural language", "Map aware planning", "Live mission views"],
  },
] as const;

function ProductAction({
  availability,
  product,
  release,
}: {
  availability: EditionAvailabilityDocument;
  product: ProductDefinition;
  release?: WebsiteRelease;
}) {
  if (product.id === "universal") {
    return release ? (
      <a
        className="site-products-action"
        href={release.downloadUrl}
        download={release.fileName}
        aria-label="Download DroneDream Universal"
      >
        <Download aria-hidden="true" />
        Download Universal
      </a>
    ) : null;
  }

  const edition = availability.editions.find((candidate) => candidate.id === product.id);
  const published = edition?.status === "published" && Boolean(edition.downloadUrl);
  if (!published || !edition?.downloadUrl) {
    return (
      <button
        className="site-products-action"
        type="button"
        disabled
        aria-label={`DroneDream ${product.name} download unavailable`}
      >
        <Download aria-hidden="true" />
        Coming soon
      </button>
    );
  }

  return (
    <a
      className="site-products-action"
      href={edition.downloadUrl}
      download={edition.fileName ?? undefined}
      aria-label={`Download DroneDream ${product.name}`}
    >
      <Download aria-hidden="true" />
      Download {product.name}
    </a>
  );
}

export function ProductPage({
  availability,
  release,
}: {
  availability: EditionAvailabilityDocument;
  locale: Locale;
  release?: WebsiteRelease;
}) {
  const universal = products[0];
  const focusedProducts = products.slice(1);

  const renderProduct = (product: ProductDefinition, index: number) => {
    const isUniversal = product.id === "universal";
    const logo = isUniversal
      ? universalLockup
      : editionBrandAssets[product.id as EditionAvailabilityId].lockup;

    return (
      <article
        className={`site-products-card ${isUniversal ? "is-universal" : "is-focused"}`}
        data-product={product.id}
        style={{ "--product-order": index } as CSSProperties}
        key={product.id}
      >
        <div className="site-products-brand">
          <img src={logo} alt={`DroneDream ${product.name}`} />
          <span>{isUniversal ? "Complete suite" : "Focused workspace"}</span>
        </div>

        {!isUniversal && (
          <div className="site-products-visual" aria-hidden="true">
            <img src={editionBrandAssets[product.id as EditionAvailabilityId].mark} alt="" />
          </div>
        )}

        <div className="site-products-copy">
          <p>{product.summary}</p>
          <ul>
            {product.features.map((feature) => (
              <li key={feature}><Check aria-hidden="true" />{feature}</li>
            ))}
          </ul>
        </div>

        <ProductAction availability={availability} product={product} release={release} />
      </article>
    );
  };

  return (
    <section className="site-products-page" aria-labelledby="site-products-title">
      <div className="site-products-shell">
        <header className="site-products-intro">
          <h1 id="site-products-title">Hey! Get Your Flight Agent.</h1>
        </header>

        <div className="site-products-layout">
          {renderProduct(universal, 0)}
          <div className="site-products-focused-grid">
            {focusedProducts.map((product, index) => renderProduct(product, index + 1))}
          </div>
        </div>
      </div>
    </section>
  );
}
