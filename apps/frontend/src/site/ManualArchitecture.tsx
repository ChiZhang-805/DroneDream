import {
  ArrowRight,
  BrainCircuit,
  Database,
  Map,
  Network,
  Route,
  ShieldCheck,
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
      eyebrow: "01 · WORLD MODEL",
      title: "Map is not a map",
      lead: "A person sees a campus image. DroneDream reads named places, pickup points, and the corridors that connect them.",
      human: "Human view",
      humanBody: "The orthophoto preserves buildings, trees, roads, courtyards, and visual context.",
      agent: "Agent view",
      agentBody: "The same footprint becomes a connected graph with named buildings, pickup points, and bidirectional routes.",
      formula: "Map = geometry + semantics + topology",
    },
    places: {
      eyebrow: "02 · SEMANTIC PLACES",
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
      eyebrow: "03 · AGENT AND RUNTIME",
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
      eyebrow: "01 · 世界模型",
      title: "Map is not a map",
      lead: "人看到的是一张校园图片；DroneDream 读取的是地点名称、取件点，以及把它们连接起来的道路。",
      human: "人眼中的地图",
      humanBody: "俯视图保留建筑、树木、道路、庭院和完整的视觉环境。",
      agent: "大模型使用的地图",
      agentBody: "同一范围被转换为连通图：有名称的建筑、蓝色取件点和双向道路。",
      formula: "地图 = 几何信息 + 语义信息 + 连通关系",
    },
    places: {
      eyebrow: "02 · 语义地点",
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
      eyebrow: "03 · 智能体与运行时",
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

function ArchitectureMap({ locale }: { locale: SiteLocale }) {
  const copy = architectureCopy[locale].map;
  return (
    <section className="manual-architecture-page is-map" aria-labelledby="architecture-map-title">
      <header className="manual-architecture-intro">
        <p><Map aria-hidden="true" />{copy.eyebrow}</p>
        <h2 id="architecture-map-title">{copy.title}</h2>
        <span>{copy.lead}</span>
      </header>
      <div className="architecture-map-comparison">
        <figure>
          <div className="architecture-map-frame">
            <img
              src="/docs/downloads/manual-assets/architecture-map-human.webp"
              alt={copy.human}
            />
          </div>
          <figcaption>
            <span>01</span>
            <div><strong>{copy.human}</strong><p>{copy.humanBody}</p></div>
          </figcaption>
        </figure>
        <div className="architecture-map-arrow" aria-hidden="true"><ArrowRight /></div>
        <figure>
          <div className="architecture-map-frame">
            <img
              src="/docs/downloads/manual-assets/architecture-map-structured.webp"
              alt={copy.agent}
            />
          </div>
          <figcaption>
            <span>02</span>
            <div><strong>{copy.agent}</strong><p>{copy.agentBody}</p></div>
          </figcaption>
        </figure>
      </div>
      <div className="architecture-formula"><Network aria-hidden="true" />{copy.formula}</div>
    </section>
  );
}

function ArchitecturePlaces({ locale }: { locale: SiteLocale }) {
  const copy = architectureCopy[locale].places;
  return (
    <section className="manual-architecture-page is-places" aria-labelledby="architecture-places-title">
      <header className="manual-architecture-intro">
        <p><Database aria-hidden="true" />{copy.eyebrow}</p>
        <h2 id="architecture-places-title">{copy.title}</h2>
        <span>{copy.lead}</span>
      </header>
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
      <header className="manual-architecture-intro">
        <p><Route aria-hidden="true" />{copy.eyebrow}</p>
        <h2 id="architecture-execution-title">{copy.title}</h2>
        <span>{copy.lead}</span>
      </header>
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
