import { useState } from "react";
import { Check, Copy, Map, Plane, type LucideIcon } from "lucide-react";

import type { ArchitectureSectionId } from "./manualArchitectureData";

type SiteLocale = "en" | "zh-CN";

interface ManualArchitectureProps {
  locale: SiteLocale;
  section: ArchitectureSectionId;
}

const architecturePlaceExample = `{
  "points": [
    {
      "point_id": "chemicum",
      "kind": "building",
      "position_m": { "x": 63.2, "y": 45.1, "z": 0.0 },
      "geographic_position": null,
      "label": "Chemicum",
      "building_id": null,
      "status": "verified",
      "evidence_ids": ["chemicum-building-review"],
      "external_place_ids": {}
    },
    {
      "point_id": "chemicum-pickup",
      "kind": "handoff",
      "position_m": { "x": 61.8, "y": 42.7, "z": 0.0 },
      "geographic_position": null,
      "label": "Chemicum pickup point",
      "building_id": "chemicum",
      "status": "verified",
      "evidence_ids": ["chemicum-entrance-review"],
      "external_place_ids": {}
    }
  ],
  "routes": [
    {
      "route_id": "chemicum-pickup-main-junction",
      "start_point_id": "chemicum-pickup",
      "end_point_id": "main-junction-04",
      "centerline_m": [
        { "x": 61.8, "y": 42.7, "z": 0.0 },
        { "x": 58.4, "y": 39.6, "z": 0.0 }
      ],
      "direction": "bidirectional",
      "kind": "road",
      "status": "verified",
      "evidence_ids": ["chemicum-route-review"]
    }
  ]
}`;

const architectureVehicleExample = `{
  "kind": "vehicle",
  "asset_id": "aircraft-my-drone",
  "name": "My Drone",
  "version": "x500-v2-px4-v1",
  "status": "qualified",
  "content_hash": "sha256:…",
  "qualification_receipt_id": "qualification/x500-v2-px4-v1",
  "capabilities": {
    "vehicle_class": "multirotor",
    "coordinate_frame": "ENU",
    "body_radius_m": 0.38,
    "body_height_m": 0.43,
    "dry_mass_kg": 2.0643076923,
    "maximum_takeoff_mass_kg": 2.1643076923,
    "maximum_thrust_n": 34.19432,
    "maximum_speed_mps": 4.0,
    "maximum_acceleration_mps2": 2.5,
    "maximum_pickup_payload_kg": 0.1,
    "reserve_battery_percent": 30,
    "qualified_range_m": 500,
    "sensor_contract": "gps-gnss-10hz",
    "simulation_targets": ["PX4 v1.16", "MAVSDK"],
    "localization_sources": ["GPS", "GNSS"]
  }
}`;

async function copyArchitectureJson(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

const architectureCopy = {
  en: {
    map: {
      title: "Map is not a map",
      paragraphs: [
        "To a person, this is an aerial map whose buildings, trees, roads, courtyards, and entrances make sense as one visual scene. DroneDream structures that scene into named places, pickup points, and connected bidirectional routes, preserving where every element belongs while turning the image into information an agent can query and use.",
      ],
      human: "Human view",
      humanBody: "The orthophoto preserves buildings, trees, roads, courtyards, entrances, and full visual context.",
      processing: "Semantic processing",
      processingBody: "Recognized roads, named places, and pickup points align with the same geographic footprint.",
      agent: "Agent view",
      agentBody: "The footprint becomes a graph with named buildings, pickup points, and bidirectional routes.",
      firstTransition: "From visual context to recognized structure",
      firstTransitionBody: "DroneDream identifies the roads that connect the campus, recognizes buildings and their entrances, places pickup points at those entrances, and aligns every extracted element with the same geographic footprint.",
      secondTransition: "From recognized structure to an agent-readable graph",
      secondTransitionBody: "The aligned observations become an agent-readable network: named places are nodes, pickup points are access nodes, and bidirectional roads are connected edges that the planner can follow.",
      thirdTransition: "From a place to structured data",
      thirdTransitionBody: "Every mapped destination follows the backend's MapFeaturePoint and MapRouteEdge contracts. A building and its access point carry stable IDs, ENU positions, verification state, and evidence; separate route records connect that access point to the graph, so the agent can resolve a name without inventing a doorway or shortcut.",
      jsonLabel: "JSON · MapEvidenceBundle fragment",
      copyJson: "Copy JSON example",
      copiedJson: "JSON example copied",
    },
    drone: {
      title: "Drone is not a drone",
      paragraphs: [
        "To a person, it is a flying machine. To DroneDream, the aircraft is a qualified capability contract: its body, propulsion, mass, battery, sensors, controller, and operating limits determine what missions can be planned and which parts of a map are safe to use.",
      ],
      firstTransition: "Read the aircraft",
      firstTransitionBody: "The physical X500 V2 becomes a set of measurable facts. Its footprint, propulsion, payload, energy, localization, and flight stack are attached to the same aircraft identity before a route is considered.",
      facts: [
        ["Airframe", "X500 V2 · Quad X"],
        ["Flight stack", "Pixhawk 6C · PX4 v1.16"],
        ["Safety envelope", "0.38 m planning radius"],
        ["Performance", "4.0 m/s · 34.19 N thrust"],
        ["Energy & payload", "74 Wh · 0.10 kg payload"],
      ],
      secondTransition: "Build its capability contract",
      secondTransitionBody: "The model does not plan from a product name alone. DroneDream exposes the qualified values used by the mission harness, including mass, thrust, speed, acceleration, payload, battery reserve, coordinate frame, sensors, and supported simulation targets.",
      jsonLabel: "JSON · AutonomyHarnessAsset",
      copyJson: "Copy aircraft JSON",
      copiedJson: "Aircraft JSON copied",
      thirdTransition: "Fit the aircraft to the map",
      thirdTransitionBody: "The map graph is lifted into a vehicle-specific 3D corridor. DroneDream offsets each route by the aircraft envelope, respects altitude and clearance limits, and accepts only connected segments that remain inside the qualified airspace for this vehicle.",
      airspaceTitle: "Vehicle-specific 3D corridor",
      metrics: [
        ["Route graph", "Connected map edges"],
        ["Flight volume", "Altitude + obstacle clearance"],
        ["Vehicle fit", "0.38 m safety radius"],
        ["Execution frame", "ENU waypoints for PX4"],
      ],
    },
  },
  "zh-CN": {
    map: {
      title: "Map is not a map",
      paragraphs: [
        "从人的视角看，这是一张连续的校园俯视地图，建筑、树木、道路、庭院和入口共同构成完整的视觉环境；对 DroneDream 来说，它会把同一幅图结构化为有名称的地点、取件点和彼此连通的双向道路，在保留每项信息真实位置的同时，将地图转换为智能体能够查询和使用的数据。",
      ],
      human: "人眼视图",
      humanBody: "俯视图保留建筑、树木、道路、庭院、入口和完整视觉环境。",
      processing: "语义处理",
      processingBody: "识别出的道路、地点名称和取件点对齐到同一地理范围。",
      agent: "智能体视图",
      agentBody: "同一范围成为由建筑、取件点和双向道路组成的连通图。",
      firstTransition: "从视觉环境到可识别结构",
      firstTransitionBody: "DroneDream 会识别连接校园的道路、建筑及其入口，把取件点放到对应入口处，并将提取出的每一个元素准确对齐到同一地理范围。",
      secondTransition: "从可识别结构到智能体可读图",
      secondTransitionBody: "对齐后的观察结果会被转换成智能体可读的网络：有名称的地点成为节点，取件点成为访问节点，双向道路成为规划器可以沿着行进的连通边。",
      thirdTransition: "从地点到结构化数据",
      thirdTransitionBody: "每个地图目的地都遵循后端实际使用的 MapFeaturePoint 与 MapRouteEdge 数据契约。建筑及其取件点保存稳定标识、ENU 位置、验证状态和证据；独立的路线记录再把取件点接入路网，让智能体能够按名称解析地点，而不会凭空猜测入口或捷径。",
      jsonLabel: "JSON · MapEvidenceBundle 片段",
      copyJson: "复制 JSON 示例",
      copiedJson: "已复制 JSON 示例",
    },
    drone: {
      title: "Drone is not a drone",
      paragraphs: [
        "从人的视角看，它是一架会飞的机器；对 DroneDream 来说，无人机是一份经过验证的能力契约，机体、动力、重量、电池、传感器、控制器和运行边界共同决定哪些任务可以规划，以及地图中的哪些空间可以安全使用。",
      ],
      firstTransition: "读懂无人机",
      firstTransitionBody: "实体 X500 V2 会先转换为一组可测量的事实。它的占用空间、动力、载荷、能源、定位方式和飞行栈都会绑定到同一架无人机的身份上，再进入路线规划。",
      facts: [
        ["机架", "X500 V2 · Quad X"],
        ["飞行栈", "Pixhawk 6C · PX4 v1.16"],
        ["安全包络", "0.38 米规划半径"],
        ["性能", "4.0 米/秒 · 34.19 牛推力"],
        ["能源与载荷", "74 瓦时 · 0.10 千克载荷"],
      ],
      secondTransition: "建立能力契约",
      secondTransitionBody: "模型不会只凭产品名称规划。DroneDream 会提供任务执行器实际使用的验证参数，包括重量、推力、速度、加速度、载荷、电池余量、坐标系、传感器和支持的仿真目标。",
      jsonLabel: "JSON · AutonomyHarnessAsset",
      copyJson: "复制无人机 JSON",
      copiedJson: "已复制无人机 JSON",
      thirdTransition: "让无人机适配地图",
      thirdTransitionBody: "地图路网会被抬升为面向具体机型的三维走廊。DroneDream 根据无人机包络扩展每条路线，检查高度和障碍物净空，并只接受处于该机型验证空域内且彼此连通的航段。",
      airspaceTitle: "面向机型的三维飞行走廊",
      metrics: [
        ["路线网络", "相互连通的地图边"],
        ["飞行空间", "高度与障碍物净空"],
        ["机型适配", "0.38 米安全半径"],
        ["执行坐标", "提供给 PX4 的 ENU 航点"],
      ],
    },
  },
} as const;

function ArchitectureIntro({
  id,
  title,
  paragraphs,
  icon: Icon,
}: {
  id: string;
  title: string;
  paragraphs: readonly string[];
  icon: LucideIcon;
}) {
  return (
    <header className="manual-architecture-intro">
      <h2 id={id}>
        <span className="manual-chapter-icon" aria-hidden="true"><Icon /></span>
        <span>{title}</span>
        <i aria-hidden="true" />
      </h2>
      <div className="manual-architecture-prose">
        {paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
      </div>
    </header>
  );
}

function ArchitectureSectionHeading({ number, id, title }: { number: string; id: string; title: string }) {
  return <header><span>{number}</span><h3 id={id}>{title}</h3></header>;
}

function CopyableJson({ value, label, copyLabel, copiedLabel }: {
  value: string;
  label: string;
  copyLabel: string;
  copiedLabel: string;
}) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await copyArchitectureJson(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className="architecture-json-example">
      <span>{label}</span>
      <button
        type="button"
        className={copied ? "is-copied" : undefined}
        aria-label={copied ? copiedLabel : copyLabel}
        title={copied ? copiedLabel : copyLabel}
        onClick={() => void handleCopy()}
      >
        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      </button>
      <pre><code>{value}</code></pre>
    </div>
  );
}

function ArchitectureMap({ locale }: { locale: SiteLocale }) {
  const copy = architectureCopy[locale].map;
  const processingImage = "/docs/downloads/manual-assets/architecture-map-processing.webp";
  return (
    <section className="manual-architecture-page is-map" aria-labelledby="architecture-map-title">
      <ArchitectureIntro id="architecture-map-title" title={copy.title} paragraphs={copy.paragraphs} icon={Map} />
      <div className="architecture-map-sequence">
        <section className="architecture-map-transition" aria-labelledby="architecture-map-transition-one">
          <ArchitectureSectionHeading number="01" id="architecture-map-transition-one" title={copy.firstTransition} />
          <p>{copy.firstTransitionBody}</p>
          <div className="architecture-map-pair">
            <figure>
              <div className="architecture-map-frame"><img src="/docs/downloads/manual-assets/architecture-map-human.webp" alt={copy.human} loading="lazy" /></div>
              <figcaption><strong>{copy.human}</strong><p>{copy.humanBody}</p></figcaption>
            </figure>
            <figure>
              <div className="architecture-map-frame"><img src={processingImage} alt={copy.processing} loading="lazy" /></div>
              <figcaption><strong>{copy.processing}</strong><p>{copy.processingBody}</p></figcaption>
            </figure>
          </div>
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-map-transition-two">
          <ArchitectureSectionHeading number="02" id="architecture-map-transition-two" title={copy.secondTransition} />
          <p>{copy.secondTransitionBody}</p>
          <div className="architecture-map-pair">
            <figure>
              <div className="architecture-map-frame"><img src={processingImage} alt={copy.processing} loading="lazy" /></div>
              <figcaption><strong>{copy.processing}</strong><p>{copy.processingBody}</p></figcaption>
            </figure>
            <figure>
              <div className="architecture-map-frame"><img src="/docs/downloads/manual-assets/architecture-map-structured.webp" alt={copy.agent} loading="lazy" /></div>
              <figcaption><strong>{copy.agent}</strong><p>{copy.agentBody}</p></figcaption>
            </figure>
          </div>
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-map-transition-three">
          <ArchitectureSectionHeading number="03" id="architecture-map-transition-three" title={copy.thirdTransition} />
          <p>{copy.thirdTransitionBody}</p>
          <CopyableJson value={architecturePlaceExample} label={copy.jsonLabel} copyLabel={copy.copyJson} copiedLabel={copy.copiedJson} />
        </section>
      </div>
    </section>
  );
}

function DroneIllustration() {
  return (
    <svg viewBox="0 0 680 520" role="img" aria-label="X500 V2 quadrotor product view">
      <defs>
        <linearGradient id="drone-body" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#202a43" /><stop offset="1" stopColor="#0e1426" /></linearGradient>
        <linearGradient id="drone-accent" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#6bd8f3" /><stop offset="0.48" stopColor="#8b7df2" /><stop offset="1" stopColor="#e85cc5" /></linearGradient>
        <filter id="drone-shadow" x="-30%" y="-30%" width="160%" height="180%"><feDropShadow dx="0" dy="18" stdDeviation="18" floodColor="#2f315b" floodOpacity="0.24" /></filter>
      </defs>
      <ellipse cx="328" cy="434" rx="224" ry="26" fill="#756bd2" opacity="0.12" />
      <g filter="url(#drone-shadow)">
        <g fill="none" stroke="#252c44" strokeWidth="16" strokeLinecap="round"><path d="M292 238 L136 140" /><path d="M366 238 L524 140" /><path d="M292 280 L136 374" /><path d="M366 280 L524 374" /></g>
        <g fill="none" stroke="#59647b" strokeWidth="5" strokeLinecap="round" opacity="0.78"><path d="M292 238 L136 140" /><path d="M366 238 L524 140" /><path d="M292 280 L136 374" /><path d="M366 280 L524 374" /></g>
        <g fill="#11182b" stroke="#68748e" strokeWidth="5"><circle cx="126" cy="132" r="32" /><circle cx="534" cy="132" r="32" /><circle cx="126" cy="382" r="32" /><circle cx="534" cy="382" r="32" /></g>
        <g fill="none" stroke="url(#drone-accent)" strokeWidth="7" opacity="0.82"><ellipse cx="126" cy="132" rx="92" ry="18" /><ellipse cx="534" cy="132" rx="92" ry="18" /><ellipse cx="126" cy="382" rx="92" ry="18" /><ellipse cx="534" cy="382" rx="92" ry="18" /></g>
        <path d="M255 220 L292 187 H369 L405 220 V302 L369 335 H292 L255 302 Z" fill="url(#drone-body)" stroke="#737f99" strokeWidth="4" />
        <path d="M281 229 H379 V295 H281 Z" fill="#151d32" stroke="#8792a7" strokeWidth="3" />
        <path d="M304 209 H356 L368 230 H292 Z" fill="url(#drone-accent)" opacity="0.9" />
        <circle cx="330" cy="260" r="26" fill="#070b16" stroke="#4fd4ee" strokeWidth="4" /><circle cx="330" cy="260" r="8" fill="#e76bcc" />
        <path d="M282 319 L268 399 H298 L318 329 M378 319 L392 399 H362 L342 329" fill="none" stroke="#323b54" strokeWidth="9" strokeLinecap="round" />
        <path d="M300 400 H256 M404 400 H360" fill="none" stroke="#11182b" strokeWidth="8" strokeLinecap="round" />
      </g>
      <g fill="#7d51df" stroke="#fff" strokeWidth="4"><circle cx="530" cy="132" r="8" /><circle cx="391" cy="224" r="8" /><circle cx="403" cy="316" r="8" /><circle cx="359" cy="391" r="8" /><circle cx="512" cy="382" r="8" /></g>
    </svg>
  );
}

function DroneProductView({ facts }: { facts: readonly (readonly [string, string])[] }) {
  return (
    <div className="architecture-drone-product">
      <div className="architecture-drone-visual"><DroneIllustration /></div>
      <svg className="architecture-drone-connectors" viewBox="0 0 1000 520" preserveAspectRatio="none" aria-hidden="true">
        <path d="M530 132 L682 72 L724 72" /><path d="M391 224 L650 170 L724 170" />
        <path d="M403 316 L650 268 L724 268" /><path d="M359 391 L658 366 L724 366" />
        <path d="M512 382 L682 464 L724 464" />
      </svg>
      <dl className="architecture-drone-facts">
        {facts.map(([term, value]) => <div key={term}><dt>{term}</dt><dd>{value}</dd></div>)}
      </dl>
    </div>
  );
}

function AirspaceDiagram({ title, metrics }: { title: string; metrics: readonly (readonly [string, string])[] }) {
  return (
    <figure className="architecture-airspace-diagram">
      <div className="architecture-airspace-scene">
        <svg viewBox="0 0 980 510" role="img" aria-label={title}>
          <defs>
            <linearGradient id="airspace-corridor" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#58d7ef" stopOpacity="0.52" /><stop offset="0.55" stopColor="#8b77ef" stopOpacity="0.38" /><stop offset="1" stopColor="#eb63c8" stopOpacity="0.3" /></linearGradient>
            <linearGradient id="airspace-route" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#2cb9ed" /><stop offset="1" stopColor="#c74fd2" /></linearGradient>
          </defs>
          <g fill="none" stroke="#8f97ac" strokeOpacity="0.22" strokeWidth="1.4"><path d="M80 420 L470 190 L900 420" /><path d="M80 420 L500 500 L900 420" /><path d="M158 374 L576 454" /><path d="M236 328 L652 408" /><path d="M314 282 L730 362" /><path d="M392 236 L808 316" /><path d="M164 436 L554 206" /><path d="M250 452 L640 222" /><path d="M336 468 L726 238" /><path d="M422 484 L812 254" /></g>
          <g fill="#cfd5e4" opacity="0.46"><path d="M120 363 L230 299 L332 319 L222 384 Z" /><path d="M604 371 L741 291 L864 314 L727 394 Z" /><path d="M331 422 L438 359 L525 376 L418 440 Z" /><path d="M509 275 L599 222 L676 237 L586 290 Z" /></g>
          <g fill="url(#airspace-corridor)" stroke="#8d6be6" strokeWidth="2.4"><path d="M158 342 L301 253 L449 309 L608 211 L829 301 L829 355 L608 265 L449 363 L301 307 L158 396 Z" /><path d="M158 342 L158 281 L301 192 L449 248 L608 150 L829 240 L829 301 L608 211 L449 309 L301 253 Z" opacity="0.56" /><path d="M158 281 L301 192 L449 248 L608 150 L829 240 L829 355 L608 265 L449 363 L301 307 L158 396 Z" fill="none" opacity="0.72" /></g>
          <path d="M175 336 L302 260 L448 316 L608 219 L811 301" fill="none" stroke="url(#airspace-route)" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
          <g fill="#fff" stroke="#774fd9" strokeWidth="5"><circle cx="175" cy="336" r="10" /><circle cx="302" cy="260" r="10" /><circle cx="448" cy="316" r="10" /><circle cx="608" cy="219" r="10" /><circle cx="811" cy="301" r="10" /></g>
          <g transform="translate(567 171)"><ellipse cx="40" cy="54" rx="50" ry="11" fill="#232c45" opacity="0.14" /><path d="M15 28 L-18 8 M65 28 L98 8 M15 38 L-18 58 M65 38 L98 58" stroke="#212a42" strokeWidth="7" strokeLinecap="round" /><g fill="none" stroke="#8f67e7" strokeWidth="4"><ellipse cx="-22" cy="6" rx="29" ry="7" /><ellipse cx="102" cy="6" rx="29" ry="7" /><ellipse cx="-22" cy="60" rx="29" ry="7" /><ellipse cx="102" cy="60" rx="29" ry="7" /></g><rect x="15" y="20" width="50" height="27" rx="7" fill="#172037" stroke="#55cce9" strokeWidth="3" /></g>
          <g fill="#31394d" fontFamily="Inter, sans-serif" fontSize="18" fontWeight="700"><text x="106" y="257">z min</text><text x="842" y="236">z max</text></g>
          <g stroke="#59647b" strokeWidth="2" strokeDasharray="6 7"><path d="M148 278 V401" /><path d="M839 235 V363" /></g>
        </svg>
      </div>
      <figcaption>{metrics.map(([term, value]) => <div key={term}><strong>{term}</strong><span>{value}</span></div>)}</figcaption>
    </figure>
  );
}

function ArchitectureDrone({ locale }: { locale: SiteLocale }) {
  const copy = architectureCopy[locale].drone;
  return (
    <section className="manual-architecture-page is-drone" aria-labelledby="architecture-drone-title">
      <ArchitectureIntro id="architecture-drone-title" title={copy.title} paragraphs={copy.paragraphs} icon={Plane} />
      <div className="architecture-map-sequence">
        <section className="architecture-map-transition" aria-labelledby="architecture-drone-transition-one">
          <ArchitectureSectionHeading number="01" id="architecture-drone-transition-one" title={copy.firstTransition} />
          <p>{copy.firstTransitionBody}</p><DroneProductView facts={copy.facts} />
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-drone-transition-two">
          <ArchitectureSectionHeading number="02" id="architecture-drone-transition-two" title={copy.secondTransition} />
          <p>{copy.secondTransitionBody}</p>
          <CopyableJson value={architectureVehicleExample} label={copy.jsonLabel} copyLabel={copy.copyJson} copiedLabel={copy.copiedJson} />
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-drone-transition-three">
          <ArchitectureSectionHeading number="03" id="architecture-drone-transition-three" title={copy.thirdTransition} />
          <p>{copy.thirdTransitionBody}</p><AirspaceDiagram title={copy.airspaceTitle} metrics={copy.metrics} />
        </section>
      </div>
    </section>
  );
}

export default function ManualArchitecture({ locale, section }: ManualArchitectureProps) {
  return section === "drone" ? <ArchitectureDrone locale={locale} /> : <ArchitectureMap locale={locale} />;
}
