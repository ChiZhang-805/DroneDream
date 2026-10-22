import {
  BrainCircuit,
  Database,
  Map,
  Route,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import type { ArchitectureSectionId } from "./manualArchitectureData";

type SiteLocale = "en" | "zh-CN";

interface ManualArchitectureProps {
  locale: SiteLocale;
  section: ArchitectureSectionId;
}

const architectureCopy = {
  en: {
    map: {
      title: "Map is not a map",
      paragraphs: [
        "To a person, this is an aerial map whose buildings, trees, roads, courtyards, and entrances make sense as one visual scene. DroneDream structures that scene into named places, pickup points, and connected bidirectional routes, preserving where every element belongs while turning the image into information an agent can query and use.",
      ],
      human: "Human view",
      humanBody: "The orthophoto preserves buildings, trees, roads, courtyards, and visual context.",
      processing: "Semantic processing",
      processingBody: "Recognized roads, named places, and pickup points are aligned with the same geographic footprint.",
      agent: "Agent view",
      agentBody: "The same footprint becomes a connected graph with named buildings, pickup points, and bidirectional routes.",
      firstTransition: "From visual context to recognized structure",
      firstTransitionBody: "DroneDream identifies the roads that connect the campus, recognizes buildings and their entrances, places pickup points at those entrances, and aligns every extracted element with the same geographic footprint.",
      secondTransition: "From recognized structure to an agent-readable graph",
      secondTransitionBody: "The aligned observations are converted into an agent-readable network: named places become nodes, pickup points become access nodes, and bidirectional roads become connected edges that the planner can follow.",
    },
    places: {
      title: "A place becomes a node",
      lead: "Each visible destination is stored as a small, explicit record that tools can query and routes can reference.",
      cardTitle: "Chemicum",
      fields: [
        ["Type", "Key building"],
        ["Role", "Chemistry teaching and research"],
        ["Position", "ENU coordinates in the campus frame"],
        ["Pickup", "Linked blue access point"],
        ["Connections", "Garden footway · campus road"],
      ],
      note: "Names give the model meaning. Coordinates give the runtime a place. Edges make the place reachable.",
    },
    execution: {
      title: "From intent to flight",
      lead: "The model translates a goal into a checked mission. Deterministic flight software executes it and remains in control of the aircraft.",
      steps: [
        ["Intent", "Deliver a sample from Chemicum to Physicum."],
        ["Plan", "Resolve places, call route and constraint tools, then propose waypoints and speed."],
        ["Execute", "Validate the mission and hand it to PX4; the live controller flies and reports telemetry."],
      ],
      boundary: "The model plans and advises. It does not replace the real-time flight controller.",
    },
  },
  "zh-CN": {
    map: {
      title: "Map is not a map",
      paragraphs: [
        "从人的视角看，这是一张连续的校园俯视地图，建筑、树木、道路、庭院和入口共同构成完整的视觉环境；对 DroneDream 来说，它会把同一幅图结构化为有名称的地点、取件点和彼此连通的双向道路，在保留每项信息真实位置的同时，将地图转换为智能体能够查询和使用的数据。",
      ],
      human: "人眼视图",
      humanBody: "俯视图保留建筑、树木、道路、庭院和完整的视觉环境。",
      processing: "语义处理",
      processingBody: "识别出的道路、地点名称和取件点被对齐到同一地理范围。",
      agent: "智能体视图",
      agentBody: "同一范围被转换为连通图：有名称的建筑、蓝色取件点和双向道路。",
      firstTransition: "从视觉环境到可识别结构",
      firstTransitionBody: "DroneDream 会识别连接校园的道路、建筑及其入口，把取件点放到对应入口处，并将提取出的每一个元素准确对齐到同一地理范围。",
      secondTransition: "从可识别结构到智能体可读图",
      secondTransitionBody: "对齐后的观察结果会被转换成智能体可读的网络：有名称的地点成为节点，取件点成为访问节点，双向道路成为规划器可以沿着行进的连通边。",
    },
    places: {
      title: "地点如何成为节点",
      lead: "每个可见目的地都会保存成清晰的小型记录，工具可以查询，路线可以直接引用。",
      cardTitle: "Chemicum",
      fields: [
        ["类型", "关键建筑"],
        ["功能", "化学教学与研究"],
        ["位置", "校园坐标系中的 ENU 坐标"],
        ["取件点", "关联的蓝色入口节点"],
        ["连接", "花园步道 · 校园道路"],
      ],
      note: "名称提供含义，坐标提供位置，道路连接让地点真正可达。",
    },
    execution: {
      title: "从意图到飞行",
      lead: "大模型把自然语言目标转换为经过检查的任务；确定性的飞控软件负责执行，并始终控制无人机。",
      steps: [
        ["目标", "把样品从 Chemicum 送到 Physicum。"],
        ["规划", "解析地点，调用路线与约束工具，再提出航点和速度。"],
        ["执行", "校验任务并交给 PX4；实时控制器完成飞行并返回遥测。"],
      ],
      boundary: "大模型负责规划和建议，不替代实时飞行控制器。",
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

function ArchitectureMap({ locale }: { locale: SiteLocale }) {
  const copy = architectureCopy[locale].map;
  const processingImage = "/docs/downloads/manual-assets/architecture-map-processing.webp";
  return (
    <section className="manual-architecture-page is-map" aria-labelledby="architecture-map-title">
      <ArchitectureIntro id="architecture-map-title" title={copy.title} paragraphs={copy.paragraphs} icon={Map} />
      <div className="architecture-map-sequence">
        <section className="architecture-map-transition" aria-labelledby="architecture-map-transition-one">
          <header><span>01</span><h3 id="architecture-map-transition-one">{copy.firstTransition}</h3></header>
          <p>{copy.firstTransitionBody}</p>
          <div className="architecture-map-pair">
            <figure>
              <div className="architecture-map-frame">
                <img src="/docs/downloads/manual-assets/architecture-map-human.webp" alt={copy.human} loading="lazy" />
              </div>
              <figcaption><strong>{copy.human}</strong><p>{copy.humanBody}</p></figcaption>
            </figure>
            <figure>
              <div className="architecture-map-frame">
                <img src={processingImage} alt={copy.processing} loading="lazy" />
              </div>
              <figcaption><strong>{copy.processing}</strong><p>{copy.processingBody}</p></figcaption>
            </figure>
          </div>
        </section>

        <section className="architecture-map-transition" aria-labelledby="architecture-map-transition-two">
          <header><span>02</span><h3 id="architecture-map-transition-two">{copy.secondTransition}</h3></header>
          <p>{copy.secondTransitionBody}</p>
          <div className="architecture-map-pair">
            <figure>
              <div className="architecture-map-frame">
                <img src={processingImage} alt={copy.processing} loading="lazy" />
              </div>
              <figcaption><strong>{copy.processing}</strong><p>{copy.processingBody}</p></figcaption>
            </figure>
            <figure>
              <div className="architecture-map-frame">
                <img src="/docs/downloads/manual-assets/architecture-map-structured.webp" alt={copy.agent} loading="lazy" />
              </div>
              <figcaption><strong>{copy.agent}</strong><p>{copy.agentBody}</p></figcaption>
            </figure>
          </div>
        </section>
      </div>
    </section>
  );
}

function ArchitecturePlaces({ locale }: { locale: SiteLocale }) {
  const copy = architectureCopy[locale].places;
  return (
    <section className="manual-architecture-page is-places" aria-labelledby="architecture-places-title">
      <ArchitectureIntro id="architecture-places-title" title={copy.title} paragraphs={[copy.lead]} icon={Database} />
      <div className="architecture-place-layout">
        <div className="architecture-node-card">
          <div><i aria-hidden="true" /><small>PLACE / 33270</small></div>
          <h3>{copy.cardTitle}</h3>
          <dl>
            {copy.fields.map(([term, description]) => (
              <div key={term}><dt>{term}</dt><dd>{description}</dd></div>
            ))}
          </dl>
        </div>
        <div className="architecture-mini-graph" aria-hidden="true">
          <svg viewBox="0 0 540 420" role="img">
            <path d="M72 210 C145 132 200 134 270 210 S395 292 468 210" />
            <path d="M270 210 C270 138 270 102 270 58" />
            <circle cx="72" cy="210" r="16" /><circle cx="270" cy="210" r="22" />
            <circle cx="468" cy="210" r="16" /><circle cx="270" cy="58" r="16" />
            <text x="72" y="250">Exactum</text><text x="270" y="255">Chemicum</text>
            <text x="468" y="250">HOAS</text><text x="270" y="30">Physicum</text>
          </svg>
          <p>{copy.note}</p>
        </div>
      </div>
    </section>
  );
}

function ArchitectureExecution({ locale }: { locale: SiteLocale }) {
  const copy = architectureCopy[locale].execution;
  const icons = [BrainCircuit, Route, ShieldCheck];
  return (
    <section className="manual-architecture-page is-execution" aria-labelledby="architecture-execution-title">
      <ArchitectureIntro id="architecture-execution-title" title={copy.title} paragraphs={[copy.lead]} icon={Route} />
      <ol className="architecture-execution-flow">
        {copy.steps.map(([title, body], index) => {
          const Icon = icons[index];
          return (
            <li key={title}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <Icon aria-hidden="true" />
              <h3>{title}</h3>
              <p>{body}</p>
            </li>
          );
        })}
      </ol>
      <aside className="architecture-boundary"><ShieldCheck aria-hidden="true" />{copy.boundary}</aside>
    </section>
  );
}

export default function ManualArchitecture({ locale, section }: ManualArchitectureProps) {
  if (section === "places") return <ArchitecturePlaces locale={locale} />;
  if (section === "execution") return <ArchitectureExecution locale={locale} />;
  return <ArchitectureMap locale={locale} />;
}
