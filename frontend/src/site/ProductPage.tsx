import type { CSSProperties } from "react";
import {
  Activity,
  Boxes,
  Camera,
  Check,
  Command,
  Cpu,
  Cuboid,
  Download,
  Gauge,
  Map,
  Navigation,
  Plane,
  Plug,
  Radio,
  Route,
  Sparkles,
} from "lucide-react";

import universalLockup from "../../../brand/icons/universal-lockup.png";
import universalMark from "../../../brand/icons/universal-mark.png";
import {
  primaryEditionIds,
  type EditionAvailabilityId,
  type EditionAvailabilityDocument,
} from "./editionAvailability";
import { editionBrandAssets } from "./editionBrandAssets";
import type { WebsiteRelease } from "./release";

type Locale = "en" | "zh-CN";

const editionCopy: Record<EditionAvailabilityId, {
  title: string;
  role: string;
  features: readonly string[];
}> = {
  sim: {
    title: "DroneDream · SIM",
    role: "Build and repeat PX4 / Gazebo flights in a local digital twin.",
    features: ["Scenario setup", "Route simulation", "Parameter exploration"],
  },
  lab: {
    title: "DroneDream · LAB",
    role: "Connect simulation and hardware work inside one controlled workspace.",
    features: ["Hardware-in-the-loop", "Model calibration", "Sensor integration"],
  },
  field: {
    title: "DroneDream · FIELD",
    role: "Prepare vehicles, monitor telemetry, and run real-world field work.",
    features: ["Vehicle setup", "Live telemetry", "Operator controls"],
  },
  autonomy: {
    title: "DroneDream · AGENT",
    role: "Turn everyday language into map-aware autonomous missions.",
    features: ["Natural-language planning", "Mission simulation", "Live mission views"],
  },
};

const capabilityCards = [
  {
    icon: Map,
    kicker: "MAP INTELLIGENCE",
    title: "Understand places before planning the route.",
    body: "Buildings, entrances, handoff points, corridors, and map semantics give the planner meaningful destinations instead of anonymous coordinates.",
    meta: ["Named places", "Entrances", "Flight corridors"],
  },
  {
    icon: Plane,
    kicker: "AIRCRAFT & PAYLOADS",
    title: "Match the aircraft to the work.",
    body: "Select a verified airframe and its cameras, depth sensors, LiDAR, gimbal, and payload configuration before the mission begins.",
    meta: ["Airframes", "Sensors", "Payloads"],
  },
  {
    icon: Cuboid,
    kicker: "DIGITAL TWIN",
    title: "See the mission happen before it leaves the screen.",
    body: "PX4 and Gazebo run the planned route against the chosen world, vehicle, obstacles, payload, and mission actions.",
    meta: ["PX4", "Gazebo", "3D worlds"],
  },
  {
    icon: Camera,
    kicker: "LIVE MONITORING",
    title: "Keep the flight and the map in the same view.",
    body: "Switch between a 2D route, simulation camera, forward camera, and gimbal feed while altitude, progress, and aircraft position update live.",
    meta: ["2D route", "Camera feeds", "Telemetry"],
  },
  {
    icon: Cpu,
    kicker: "LOCAL RUNTIME",
    title: "One desktop workspace, one dedicated flight runtime.",
    body: "The Windows app coordinates the model, map assets, PX4, Gazebo, ROS 2 services, mission execution, and live state through a local Runtime.",
    meta: ["Windows app", "ROS 2", "Local services"],
  },
  {
    icon: Plug,
    kicker: "EXTENSIBILITY",
    title: "Add the tools a new mission needs.",
    body: "Aircraft packages, maps, models, mission tools, and plug-ins extend the workspace without changing how people describe and launch work.",
    meta: ["Plug-ins", "Imported assets", "Mission tools"],
  },
] as const;

const workflow = [
  { icon: Command, number: "01", title: "Describe", body: "Ask for the outcome in ordinary language." },
  { icon: Route, number: "02", title: "Plan", body: "Resolve the place, route, aircraft, and actions." },
  { icon: Plane, number: "03", title: "Fly", body: "Run the complete mission in the selected world." },
  { icon: Radio, number: "04", title: "Monitor", body: "Follow position, altitude, cameras, and progress live." },
] as const;

function ProductEditionCard({ id, availability }: {
  id: EditionAvailabilityId;
  availability: EditionAvailabilityDocument;
}) {
  const edition = availability.editions.find((candidate) => candidate.id === id);
  if (!edition) return null;
  const text = editionCopy[id];
  const brand = editionBrandAssets[id];
  const published = edition.status === "published" && Boolean(edition.downloadUrl);

  return (
    <article className="site-product-edition" data-edition={id} data-download-ready={published ? "true" : "false"}>
      <div className="site-product-edition-topline">
        <picture className="site-product-edition-picture">
          <source media="(min-width: 1161px)" srcSet={brand.lockup} />
          <img className="site-product-edition-icon" src={brand.mark} alt="" aria-hidden="true" />
        </picture>
        {published ? (
          <a className="site-product-edition-action" href={edition.downloadUrl!} download={edition.fileName} aria-label={`${text.title} Download`}>
            <Download aria-hidden="true" />Download
          </a>
        ) : (
          <button className="site-product-edition-action" type="button" disabled aria-label={`${text.title} Download unavailable`}>
            <Download aria-hidden="true" />Download
          </button>
        )}
      </div>
      <h3>{text.title}</h3>
      <p>{text.role}</p>
      <ul>{text.features.map((feature) => <li key={feature}><Check aria-hidden="true" />{feature}</li>)}</ul>
    </article>
  );
}

export function ProductPage({ availability, locale: _locale, release }: {
  availability: EditionAvailabilityDocument;
  locale: Locale;
  release?: WebsiteRelease;
}) {
  const visibleEditionIds: EditionAvailabilityId[] = [...primaryEditionIds];
  if (availability.editions.some((edition) => edition.id === "autonomy" && edition.status === "published")) {
    visibleEditionIds.push("autonomy");
  }

  return (
    <div className="site-product-page">
      <section className="site-product-hero" aria-labelledby="site-product-title">
        <div className="site-product-hero-copy">
          <p className="site-product-kicker"><Sparkles aria-hidden="true" /> INTEGRATED UAV ENGINEERING</p>
          <h1 id="site-product-title">Describe the mission.<br /><span>See it take flight.</span></h1>
          <p className="site-product-lead">DroneDream brings natural-language planning, map-aware routing, digital twins, aircraft configuration, live monitoring, and local flight services into one desktop workspace.</p>
          <div className="site-product-hero-actions">
            {release ? <a className="site-button site-button-primary" href={release.downloadUrl} download={release.fileName}><Download aria-hidden="true" />Download DroneDream</a> : null}
            <a className="site-button site-button-secondary" href="#product-capabilities">Explore the workspace</a>
          </div>
          <div className="site-product-signal-row" aria-label="DroneDream product capabilities">
            <span><Command aria-hidden="true" />Natural language</span>
            <span><Map aria-hidden="true" />Map aware</span>
            <span><Activity aria-hidden="true" />Live mission state</span>
          </div>
        </div>

        <div className="site-product-flight-board" aria-label="Animated map-aware autonomous mission preview">
          <div className="site-product-flight-toolbar"><span><span className="site-product-live-dot" />Mission live</span><span>ALT 18.4 m</span><span>4.2 m/s</span></div>
          <div className="site-product-map-grid" aria-hidden="true">
            <span className="site-product-building is-one" /><span className="site-product-building is-two" /><span className="site-product-building is-three" /><span className="site-product-building is-four" />
            <svg viewBox="0 0 720 430" preserveAspectRatio="none"><path className="site-product-route-shadow" d="M84 346 C160 310 192 238 252 242 S354 308 410 252 S472 120 626 82" /><path className="site-product-route-line" d="M84 346 C160 310 192 238 252 242 S354 308 410 252 S472 120 626 82" /></svg>
            <span className="site-product-map-node is-start"><span>Start</span></span><span className="site-product-map-node is-waypoint"><span>Pickup</span></span><span className="site-product-map-node is-destination"><span>Return</span></span>
            <span className="site-product-map-aircraft"><Navigation aria-hidden="true" /></span>
          </div>
          <div className="site-product-view-switcher" aria-hidden="true"><span className="is-active"><Map />2D</span><span><Camera />Simulation</span><span><Camera />Forward</span></div>
        </div>
      </section>

      <section className="site-product-workflow" aria-labelledby="site-product-workflow-title">
        <div className="site-product-section-heading"><p className="site-product-kicker">CORE WORKFLOW</p><h2 id="site-product-workflow-title">One request becomes a complete flight.</h2><p>The interface stays simple while the workspace resolves the technical steps behind the mission.</p></div>
        <ol>{workflow.map(({ icon: Icon, number, title, body }) => <li key={number}><span className="site-product-workflow-number">{number}</span><Icon aria-hidden="true" /><h3>{title}</h3><p>{body}</p></li>)}</ol>
      </section>

      <section className="site-product-capabilities" id="product-capabilities" aria-labelledby="site-product-capabilities-title">
        <div className="site-product-section-heading"><p className="site-product-kicker">THE WORKSPACE</p><h2 id="site-product-capabilities-title">Every layer of the mission stays connected.</h2><p>Move from a place name to a flying vehicle without losing the map, aircraft, simulation, or live state.</p></div>
        <div className="site-product-capability-grid">
          {capabilityCards.map(({ icon: Icon, kicker, title, body, meta }, index) => <article key={title} style={{ "--capability-index": index } as CSSProperties}><div className="site-product-capability-icon"><Icon aria-hidden="true" /></div><p className="site-product-kicker">{kicker}</p><h3>{title}</h3><p>{body}</p><ul>{meta.map((item) => <li key={item}>{item}</li>)}</ul></article>)}
        </div>
      </section>

      <section className="site-product-runtime" aria-labelledby="site-product-runtime-title">
        <div><p className="site-product-kicker">RUNTIME ARCHITECTURE</p><h2 id="site-product-runtime-title">The desktop app conducts the whole local stack.</h2><p>Mission intent enters once. DroneDream coordinates the planner, assets, flight services, simulator, and live views behind one interface.</p></div>
        <div className="site-product-runtime-flow" aria-label="Desktop to local flight runtime architecture">
          <span><Command aria-hidden="true" /><strong>Desktop</strong><small>Intent & control</small></span><i aria-hidden="true" /><span><Cpu aria-hidden="true" /><strong>Runtime</strong><small>Mission services</small></span><i aria-hidden="true" /><span><Boxes aria-hidden="true" /><strong>PX4 + Gazebo</strong><small>Flight & world</small></span><i aria-hidden="true" /><span><Gauge aria-hidden="true" /><strong>Live state</strong><small>Views & telemetry</small></span>
        </div>
      </section>

      <section className="site-product-editions" aria-labelledby="site-product-editions-title">
        <div className="site-product-section-heading"><p className="site-product-kicker">FIVE EDITIONS</p><h2 id="site-product-editions-title">Start with the workspace that fits the flight.</h2><p>Universal combines the full platform. SIM, LAB, FIELD, and AGENT focus the interface around a specific kind of work.</p></div>
        <div className="site-product-family-strip" aria-label="DroneDream edition family">
          <article data-edition="universal"><img src={universalMark} alt="" aria-hidden="true" /><div><strong>Universal</strong><span>Complete integrated workspace</span></div></article>
          {(["sim", "lab", "field", "autonomy"] as const).map((id) => <article data-edition={id} key={id}><img src={editionBrandAssets[id].mark} alt="" aria-hidden="true" /><div><strong>{id === "autonomy" ? "Agent" : id.toUpperCase()}</strong><span>{editionCopy[id].role}</span></div></article>)}
        </div>
        <div className="site-product-universal-banner"><img src={universalLockup} alt="DroneDream Universal" /><p>Open simulation, hardware, field, and autonomous mission work from one installation.</p>{release ? <a href={release.downloadUrl} download={release.fileName}><Download aria-hidden="true" />Download Universal</a> : null}</div>
      </section>

      <section className="site-product-downloads" aria-labelledby="site-product-downloads-title">
        <div className="site-product-section-heading"><p className="site-product-kicker">FOCUSED WORKSPACES</p><h2 id="site-product-downloads-title">Choose the interface you want to open first.</h2></div>
        <div className="site-product-page-grid">{visibleEditionIds.map((id) => <ProductEditionCard id={id} availability={availability} key={id} />)}</div>
      </section>
    </div>
  );
}
