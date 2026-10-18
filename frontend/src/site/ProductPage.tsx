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
    summary: "The complete DroneDream workspace for teams that move between simulation, hardware, field work, and autonomous missions.",
    features: ["All five workspaces", "One local Runtime", "Shared aircraft and maps"],
  },
  {
    id: "sim",
    name: "SIM",
    summary: "Build repeatable PX4 and Gazebo flights, compare control changes, and rerun the same scenario locally.",
    features: ["PX4 and Gazebo", "Scenario replay", "Parameter exploration"],
  },
  {
    id: "lab",
    name: "LAB",
    summary: "Connect simulation with controlled hardware experiments and keep calibration work in one place.",
    features: ["Hardware in the loop", "Sensor integration", "Model calibration"],
  },
  {
    id: "field",
    name: "FIELD",
    summary: "Configure vehicles, follow live telemetry, and support real aircraft work from a field focused interface.",
    features: ["Vehicle setup", "Live telemetry", "Operator controls"],
  },
  {
    id: "autonomy",
    name: "AGENT",
    summary: "Describe a mission in everyday language, plan it against a map, and follow the aircraft through execution.",
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
  return (
    <section className="site-products-page" aria-labelledby="site-products-title">
      <div className="site-products-shell">
        <header className="site-products-intro">
          <p>DRONEDREAM PRODUCTS</p>
          <h1 id="site-products-title">One platform. Five ways to fly.</h1>
          <span>
            Choose the workspace that matches the work. Every product uses the same
            aircraft, maps, Runtime, and account.
          </span>
        </header>

        <div className="site-products-grid">
          {products.map((product, index) => {
            const logo = product.id === "universal"
              ? universalLockup
              : editionBrandAssets[product.id].lockup;
            return (
              <article
                className="site-products-card"
                data-product={product.id}
                style={{ "--product-order": index } as CSSProperties}
                key={product.id}
              >
                <div className="site-products-card-number">0{index + 1}</div>
                <img src={logo} alt={`DroneDream ${product.name}`} />
                <p>{product.summary}</p>
                <ul>
                  {product.features.map((feature) => (
                    <li key={feature}><Check aria-hidden="true" />{feature}</li>
                  ))}
                </ul>
                <ProductAction availability={availability} product={product} release={release} />
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
