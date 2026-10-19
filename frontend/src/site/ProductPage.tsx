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
      <svg viewBox="0 0 1920 96" preserveAspectRatio="none" focusable="false">
        <defs>
          <linearGradient id="product-flightline-gradient" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#7f70ff" />
            <stop offset="0.35" stopColor="#55dff7" />
            <stop offset="0.67" stopColor="#ff9b5b" />
            <stop offset="1" stopColor="#ff527c" />
          </linearGradient>
          <linearGradient id="product-flightline-drone-fill" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#8f70ff" stopOpacity="0.28" />
            <stop offset="0.52" stopColor="#62dff4" stopOpacity="0.24" />
            <stop offset="1" stopColor="#f25296" stopOpacity="0.3" />
          </linearGradient>
          <filter id="product-flightline-glow" x="-20%" y="-80%" width="140%" height="260%">
            <feGaussianBlur stdDeviation="2.4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <path className="site-products-flightline-guide" d="M10 82H1910" />
        <path
          className="site-products-flightline-route"
          d="M10 82H258c20 0 27-9 45-9h236c19 0 28 9 46 9h371c18 0 28-9 47-9h282c19 0 27 9 46 9h253c19 0 27-8 46-8h118c28 0 40-21 72-21h90"
        />

        <g className="site-products-flightline-landmark site-products-flightline-campus">
          <path d="M26 82h302M39 82V49h75v33M234 82V49h80v33M114 82V37h120v45M145 37V18h58v19M154 18l20-12 20 12" />
          <path d="M119 43h110M48 49l33-15 33 15M234 49l39-15 41 15M31 86h291M134 82V54h80v28M145 82V58h58v24" />
          <circle cx="174" cy="27" r="5.5" />
          <path d="M174 22v5l3 2M174 6V1h22l-7 3 7 3h-22M151 58v24M163 58v24M185 58v24M197 58v24" />
          <path className="site-products-flightline-detail" d="M48 59h13v9H48zM70 59h13v9H70zM92 59h13v9H92zM243 59h13v9h-13zM266 59h13v9h-13zM289 59h13v9h-13zM48 72h13v10H48zM70 72h13v10H70zM92 72h13v10H92zM243 72h13v10h-13zM266 72h13v10h-13zM289 72h13v10h-13z" />
          <path d="M128 47h92M128 51h92M129 86h90" />
        </g>

        <g className="site-products-flightline-landmark site-products-flightline-shanghai">
          <path d="M350 82h302M366 82V53h31v29M405 82V41h42v41M458 82V58h27v24M548 82V34h39v48M596 82V48h31v34M635 82V61h14v21" />
          <path d="M498 82l-11-19 9-14h24l9 14-11 19M508 49V35M493 35h30M508 35V18M500 18h16M508 18V5" />
          <ellipse cx="508" cy="43" rx="13" ry="8" />
          <ellipse cx="508" cy="24" rx="8" ry="6" />
          <path d="M491 63h34M494 68h28M504 49l-4 14M512 49l4 14" />
          <path className="site-products-flightline-detail" d="M373 60h17M373 68h17M373 76h17M413 49h10M430 49h10M413 59h10M430 59h10M413 69h10M430 69h10M556 43h23M556 52h23M556 61h23M556 70h23M604 56h15M604 65h15M604 74h15" />
          <path d="M405 41l21-9 21 9M548 34l20-9 19 9M596 48l16-10 15 10" />
        </g>

        <g className="site-products-flightline-landmark site-products-flightline-bridge">
          <path d="M676 82h378M689 66h352M727 66V19h30v47M973 66V19h30v47M727 29h30M973 29h30M735 19v-8h14v8M981 19v-8h14v8" />
          <path d="M684 27c82 0 99 39 181 39s99-39 181-39M689 44c77 0 102 22 176 22s99-22 176-22" />
          <path className="site-products-flightline-detail" d="M701 36v30M720 28v38M742 20v46M765 33v33M789 43v23M813 52v14M837 60v6M893 60v6M917 52v14M941 43v23M965 33v33M988 20v46M1010 28v38M1029 36v30" />
          <path d="M689 72h352M703 72l14 10M733 72l14 10M763 72l14 10M793 72l14 10M823 72l14 10M853 72l14 10M883 72l14 10M913 72l14 10M943 72l14 10M973 72l14 10M1003 72l14 10" />
        </g>

        <g className="site-products-flightline-landmark site-products-flightline-eiffel">
          <path d="M1082 82h170M1097 82c30-24 49-55 70-80 21 25 40 56 70 80M1120 82c20-30 33-56 47-80 14 24 27 50 47 80" />
          <path d="M1105 70h124M1118 55h98M1134 37h66M1150 18h34M1167 2V0" />
          <path className="site-products-flightline-detail" d="M1108 70l108-15M1119 55l81-18M1134 37l50-19M1226 70l-108-15M1215 55l-81-18M1200 37l-50-19M1116 70l29 12M1143 55l18 27M1218 70l-29 12M1191 55l-18 27" />
          <path d="M1144 82c6-12 13-18 23-18s17 6 23 18" />
        </g>

        <g className="site-products-flightline-landmark site-products-flightline-city">
          <path d="M1272 82h330M1285 82V55h40v27M1337 82V31h46v51M1395 82V46h35v36M1442 82V19h53v63M1508 82V38h42v44M1563 82V58h27v24" />
          <path d="M1285 55l20-14 20 14M1337 31l23-16 23 16M1442 19h53M1455 19V9h27v10M1508 38l21-14 21 14" />
          <path className="site-products-flightline-detail" d="M1294 63h9M1307 63h9M1294 73h9M1307 73h9M1347 42h10M1364 42h10M1347 53h10M1364 53h10M1347 64h10M1364 64h10M1347 75h10M1364 75h10M1404 56h8M1417 56h8M1404 68h8M1417 68h8M1453 30h12M1472 30h12M1453 42h12M1472 42h12M1453 54h12M1472 54h12M1453 66h12M1472 66h12M1518 49h10M1534 49h9M1518 61h10M1534 61h9M1518 73h10M1534 73h9M1571 67h11M1571 76h11" />
        </g>

        <g className="site-products-flightline-node">
          <circle cx="303" cy="82" r="3.25" />
          <circle cx="585" cy="82" r="3.25" />
          <circle cx="1003" cy="82" r="3.25" />
          <circle cx="1250" cy="82" r="3.25" />
          <circle cx="1600" cy="82" r="3.25" />
        </g>

        <g className="site-products-flightline-drone" transform="translate(1644 3)">
          <g className="site-products-flightline-rotors">
            <ellipse cx="36" cy="20" rx="34" ry="7" />
            <ellipse cx="236" cy="20" rx="34" ry="7" />
            <ellipse cx="24" cy="72" rx="34" ry="7" />
            <ellipse cx="248" cy="72" rx="34" ry="7" />
            <ellipse cx="36" cy="20" rx="24" ry="3.5" />
            <ellipse cx="236" cy="20" rx="24" ry="3.5" />
            <ellipse cx="24" cy="72" rx="24" ry="3.5" />
            <ellipse cx="248" cy="72" rx="24" ry="3.5" />
            <circle cx="36" cy="20" r="5" />
            <circle cx="236" cy="20" r="5" />
            <circle cx="24" cy="72" r="5" />
            <circle cx="248" cy="72" r="5" />
          </g>
          <path className="site-products-flightline-drone-arm" d="M103 38L36 20M169 38l67-18M99 53L24 72M173 53l75 19" />
          <path className="site-products-flightline-drone-arm" d="M36 20l-8 14M236 20l8 14M24 72l8-14M248 72l-8-14" />
          <path className="site-products-flightline-drone-body" d="M102 32l20-12h28l20 12 17 17-13 22-24 12h-28L98 71 85 49z" />
          <path className="site-products-flightline-drone-shell" d="M101 38h70l8 11-14 19h-58L93 49zM121 25l15 13 15-13M108 44h56M113 56h46" />
          <path className="site-products-flightline-drone-shell" d="M103 39l-8 8M169 39l8 8M114 34h44" />
          <path className="site-products-flightline-drone-gear" d="M111 70l-12 15M161 70l12 15M94 86h20M158 86h20" />
          <g className="site-products-flightline-camera">
            <path d="M121 68h30l-3 18h-24z" />
            <circle cx="136" cy="77" r="7" />
            <circle cx="136" cy="77" r="3" />
          </g>
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
