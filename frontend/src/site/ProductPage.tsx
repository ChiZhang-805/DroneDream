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

function ProductFlightline() {
  return (
    <div className="site-products-flightline" aria-hidden="true">
      <svg viewBox="0 0 1920 88" preserveAspectRatio="none" focusable="false">
        <defs>
          <linearGradient id="product-flightline-gradient" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#7f70ff" />
            <stop offset="0.35" stopColor="#55dff7" />
            <stop offset="0.67" stopColor="#ff9b5b" />
            <stop offset="1" stopColor="#ff527c" />
          </linearGradient>
          <filter id="product-flightline-glow" x="-20%" y="-80%" width="140%" height="260%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <path className="site-products-flightline-guide" d="M18 65H1898" />
        <path
          className="site-products-flightline-route"
          d="M18 65H112l12-10 11 20 15-43 17 33h96l18-8 12 8h56V51c0-17 14-31 31-31s31 14 31 31v14h111l18-12 16 12h78c18-27 42-39 72-39s54 12 72 39h93l21-9 18 9h78l42-49 43 49h102V44h30v21h31V28h36v37h29V39h33v26h41l22-10 19 10h118l17-16 18 16h81"
        />

        <g className="site-products-flightline-detail">
          <path d="M339 51h82M349 51V65M411 51V65M361 37h38M370 28h20" />
          <path d="M621 65c18-26 42-39 72-39s54 13 72 39M653 65c10-14 23-21 40-21s30 7 40 21" />
          <path d="M978 65l42-49 43 49M993 49h55M1002 38h36M1010 27h20M1020 16v-7" />
          <path d="M1165 65V44h30v21M1226 65V28h36v37M1291 65V39h33v26M1174 52h12M1238 40h12M1238 50h12M1302 50h11" />
          <path d="M1516 65h124M1538 65V45h21v20M1570 65V34h27v31M1608 65V51h20v14" />
        </g>

        <g className="site-products-flightline-node">
          <circle cx="263" cy="65" r="3.5" />
          <circle cx="522" cy="65" r="3.5" />
          <circle cx="870" cy="65" r="3.5" />
          <circle cx="1113" cy="65" r="3.5" />
          <circle cx="1447" cy="65" r="3.5" />
        </g>

        <g className="site-products-flightline-drone" transform="translate(1743 31)">
          <path d="M35 18h42l10 11H25z" />
          <path d="M35 18L21 8M77 18L91 8M31 25L18 35M81 25l13 10" />
          <path d="M8 8h27M77 8h27M6 35h25M81 35h25" />
          <circle cx="21" cy="8" r="4" />
          <circle cx="91" cy="8" r="4" />
          <circle cx="18" cy="35" r="4" />
          <circle cx="94" cy="35" r="4" />
          <path d="M50 29h14l-3 9h-8z" />
        </g>
      </svg>
    </div>
  );
}

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

        <ProductFlightline />

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
