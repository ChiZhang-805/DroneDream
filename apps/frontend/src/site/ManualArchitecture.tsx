import { Fragment, useState, type CSSProperties, type ReactNode } from "react";
import { BrainCircuit, Check, Copy, Map, Plane, type LucideIcon } from "lucide-react";

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

const modelRequestExample = `{
  "natural_language":
    "Take off from the Science High School pickup point, collect the sealed sample at Chemicum, avoid roofs and trees, then return with at least 30% battery.",
  "grounded_entities": [
    { "name": "Science High School", "role": "start_and_return" },
    { "name": "Chemicum", "role": "pickup_destination" }
  ],
  "constraints": {
    "connected_routes_only": true,
    "minimum_battery_percent": 30,
    "respect_vehicle_clearance": true
  },
  "task_graph": [
    "resolve", "takeoff", "navigate", "pickup", "return", "land"
  ]
}`;

const routeToolExample = `# 1. Resolve names, then search only connected map edges.
def plan_global_corridor(start_name, goal_name, map_graph):
    start = map_resolve_entity(start_name)
    goal = map_resolve_entity(goal_name)
    route = astar(
        graph=map_graph,
        start=start.pickup_node,
        goal=goal.pickup_node,
        edge_cost=lambda edge: edge.length_m,
        allow_edge=lambda edge: edge.status == "verified",
    )
    return route_plan_global_corridor(route)`;

const trajectoryToolExample = `# 2. Turn the route into a vehicle-qualified 3D corridor.
def plan_vehicle_trajectory(route, aircraft):
    return trajectory_plan_segment(
        centerline=route.centerline_m,
        body_radius_m=aircraft.body_radius_m,
        max_speed_mps=aircraft.maximum_speed_mps,
        reserve_battery_percent=aircraft.reserve_battery_percent,
        require_obstacle_clearance=True,
    )`;

const validationToolExample = `# 3. Deterministic validation retains execution authority.
def validate_before_confirmation(plan, context):
    receipt = mission_validate_plan(
        plan=plan,
        expected_context_sha256=context.context_sha256,
        require_connected_segments=True,
        may_relax_constraints=False,
    )
    if receipt.outcome != "accepted":
        raise PlanBlocked(receipt.issue_codes)
    return receipt`;

const systemPromptExample = `SYSTEM — dronedream.autonomy.system.v1
You translate a mission request into a bounded plan.
Use only the selected, qualified map and aircraft.
Call only tools listed in eligible_tool_ids.
Never invent an entrance, route, capability, or receipt.
Return dronedream.autonomy.planner-response.v1 JSON.
You have no actuator authority and may not relax constraints.`;

const structuredOutputExample = `{
  "schema_version": "dronedream.autonomy.planner-response.v1",
  "status": "draft",
  "asset_bindings": {
    "aircraft_id": "aircraft-my-drone",
    "map_id": "kumpula-campus",
    "context_sha256": "…"
  },
  "tool_requests": [
    "map.resolve_entity",
    "route.plan_global_corridor",
    "trajectory.plan_segment",
    "mission.validate_plan"
  ],
  "safety_policy": {
    "actuator_authority": false,
    "may_relax_constraints": false,
    "execution_requires_deterministic_validation": true
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
    model: {
      title: "The model is not the system",
      paragraphs: [
        "The model interprets intent and proposes a plan, but DroneDream is the complete workflow around it. Qualified map and aircraft contracts ground the request; approved tools calculate routes and trajectories; strict schemas constrain every exchange; visual evidence resolves what structured data cannot; and the Harness validates, records, and stops the process before any execution is offered to a person.",
      ],
      firstTransition: "Understand the request",
      firstTransitionBody: "A natural-language goal is separated into grounded places, ordered actions, success evidence, and non-negotiable limits. The model reads the selected map and aircraft contracts before it converts the sentence into a task graph, so names point to verified access nodes and every requested motion remains within the selected vehicle's capability.",
      requestLabel: "Structured interpretation",
      secondTransition: "Call bounded tools",
      secondTransitionBody: "The model chooses from a small registry instead of drawing a route itself. Entity resolution binds human names to map nodes; global planning searches verified, connected edges; trajectory planning expands that centerline by the aircraft envelope; and deterministic validation rejects disconnected, stale, or unsafe results.",
      toolExamples: [
        ["Resolve and route", "The planner resolves each place to its verified pickup node, then runs A* over the connected topology. Unverified edges and invented shortcuts never enter the search."],
        ["Shape the flight volume", "The accepted route becomes a 3D trajectory whose radius, speed, clearance, and battery reserve come from the selected aircraft contract."],
        ["Validate before confirmation", "The final tool checks asset hashes, connectivity, policy, and receipts. A model rationale cannot turn a rejected plan into an accepted one."],
      ],
      thirdTransition: "Keep input and output structured",
      thirdTransitionBody: "DroneDream supplies a versioned system prompt, a content-hashed context, qualified asset contracts, and the exact eligible tool list. The response must match one planner schema with bound asset IDs, a task graph, tool requests, assumptions, blockers, repair state, and a fixed safety policy; malformed or stale output is data to reject, not code to execute.",
      promptLabel: "System prompt · excerpt",
      outputLabel: "Structured output · planner response",
      fourthTransition: "Use visual evidence where it matters",
      fourthTransitionBody: "Images are evidence for interpretation, not a substitute for geometry. The model may inspect the mission surface, the map-aligned scene, and the live route view to recognize a doorway, verify where a route actually runs, or explain a blocked segment; each observation is then tied back to a named entity, map edge, frame, or receipt before it can affect the plan.",
      visionCards: [
        ["Mission context", "The request, selected X500, and selected campus map establish the task boundary."],
        ["Grounded scene", "Roads, entrances, pickup points, and obstacles are aligned to the same map frame."],
        ["Runtime evidence", "The planned route, current aircraft state, and destination remain visible for review."],
      ],
      fifthTransition: "Run the Harness",
      fifthTransitionBody: "The Harness is the bounded control loop around every model call. It freezes the request and asset hashes, builds the context, asks for one typed proposal, executes approved read-only planning tools, validates the returned graph, and stores receipts. Repair is limited and cannot weaken policy. Only a plan that survives deterministic checks reaches human confirmation; execution remains a separate authorized step.",
      harnessSteps: [
        ["01", "Bind", "Request + asset hashes"],
        ["02", "Inspect", "Qualification receipts"],
        ["03", "Plan", "One structured model call"],
        ["04", "Tool", "Approved calculations"],
        ["05", "Validate", "Policy + connectivity"],
        ["06", "Record", "Trace + tool receipts"],
        ["07", "Confirm", "Human reviews the plan"],
      ],
      copyCode: "Copy code example",
      copiedCode: "Code example copied",
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
    model: {
      title: "The model is not the system",
      paragraphs: [
        "模型负责理解意图并提出计划，但 DroneDream 是围绕模型运行的完整流程。经过验证的地图和无人机契约负责为任务提供事实依据，受限工具计算路线与轨迹，严格的数据结构约束每次交换，视觉证据补充结构化数据无法直接表达的场景，而 Harness 会在任何执行交给用户确认前完成验证、记录与停止控制。",
      ],
      firstTransition: "理解自然语言任务",
      firstTransitionBody: "自然语言目标会被拆解为有依据的地点、按顺序执行的动作、成功证据和不可放宽的限制。模型先读取当前选定的地图与无人机契约，再把句子转换成任务图，因此地点名称会落到经过验证的访问节点，所有动作也必须处于该机型的能力范围内。",
      requestLabel: "结构化理解结果",
      secondTransition: "调用受限工具",
      secondTransitionBody: "模型不会自己手画路线，而是从一个有限的工具注册表中选择工具。地点解析把人类名称绑定到地图节点，全局规划只搜索已验证且彼此连通的边，轨迹规划按无人机包络扩展中心线，确定性验证会拒绝断开、过期或不安全的结果。",
      toolExamples: [
        ["解析地点并规划路线", "规划器先把每个地点解析到经过验证的取件节点，再在连通拓扑上运行 A*。未验证的边和凭空生成的捷径不会进入搜索。"],
        ["生成三维飞行空间", "通过验证的路线会被转换成三维轨迹，半径、速度、净空和电池余量都来自当前无人机契约。"],
        ["确认前执行验证", "最后一个工具检查资产摘要、连通性、策略和回执。模型写出的理由不能把被拒绝的计划变成可接受计划。"],
      ],
      thirdTransition: "保持结构化输入输出",
      thirdTransitionBody: "DroneDream 会提供带版本的系统提示词、内容摘要固定的上下文、经过验证的资产契约和精确的可用工具列表。模型输出必须匹配唯一的规划器结构，其中包含绑定的资产标识、任务图、工具请求、假设、阻塞项、修复状态和固定安全策略；格式错误或上下文过期的输出只会被拒绝，不会被当成代码执行。",
      promptLabel: "系统提示词 · 节选",
      outputLabel: "结构化输出 · 规划器响应",
      fourthTransition: "在关键位置使用视觉证据",
      fourthTransitionBody: "图片是用于理解的证据，不能代替几何数据。模型可以检查任务界面、与地图对齐的场景和实时路线画面，用来识别入口、核对道路实际位置或解释某段为何被阻塞；每项观察随后都必须重新绑定到有名称的地点、地图边、坐标系或回执，才能影响计划。",
      visionCards: [
        ["任务上下文", "任务描述、选定的 X500 和校园地图共同限定此次任务。"],
        ["场景对齐", "道路、入口、取件点和障碍物被对齐到同一地图坐标。"],
        ["运行证据", "规划路线、无人机当前状态和目标地点持续可供复核。"],
      ],
      fifthTransition: "运行 Harness",
      fifthTransitionBody: "Harness 是围绕每次模型调用运行的受限控制循环。它会固定任务与资产摘要、构建上下文、请求一次结构化提案、执行允许的只读规划工具、验证返回的任务图并保存回执。修复次数受到限制，也不能放宽安全策略。只有通过确定性检查的计划才会进入人工确认，执行始终属于另一个需要授权的步骤。",
      harnessSteps: [
        ["01", "绑定", "任务与资产摘要"],
        ["02", "检查", "资格验证回执"],
        ["03", "规划", "一次结构化模型调用"],
        ["04", "工具", "受限的确定性计算"],
        ["05", "验证", "策略与连通性检查"],
        ["06", "记录", "调用轨迹与工具回执"],
        ["07", "确认", "用户审阅最终计划"],
      ],
      copyCode: "复制代码示例",
      copiedCode: "已复制代码示例",
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

function highlightedCode(value: string, language: "json" | "python" | "text"): ReactNode {
  const lines = value.split("\n");
  if (language === "text") {
    return lines.map((line, lineIndex) => {
      const indent = line.match(/^\s*/u)?.[0].length ?? 0;
      const style = { paddingInlineStart: `${indent}ch` } as CSSProperties;
      return <span className="code-line" style={style} key={lineIndex}>{line.trimStart()}</span>;
    });
  }
  const pattern = language === "python"
    ? /(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b(?:def|return|raise|if|else|for|in|and|or|not|lambda|True|False|None)\b|\b\d+(?:\.\d+)?\b)/gu
    : /("(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?\b)/gu;
  return lines.map((line, lineIndex) => {
    const indent = line.match(/^\s*/u)?.[0].length ?? 0;
    const content = line.trimStart();
    const parts: ReactNode[] = [];
    let lastIndex = 0;
    for (const match of content.matchAll(pattern)) {
      const index = match.index ?? 0;
      if (index > lastIndex) parts.push(content.slice(lastIndex, index));
      const token = match[0];
      const className = token.startsWith("#")
        ? "token-comment"
        : /^['"]/u.test(token)
          ? "token-string"
          : /^(?:def|return|raise|if|else|for|in|and|or|not|lambda)$/u.test(token)
            ? "token-keyword"
            : /^(?:True|False|None|true|false|null)$/u.test(token)
              ? "token-literal"
              : "token-number";
      parts.push(<span className={className} key={`${lineIndex}-${index}`}>{token}</span>);
      lastIndex = index + token.length;
    }
    if (lastIndex < content.length) parts.push(content.slice(lastIndex));
    const style = { paddingInlineStart: `${indent}ch` } as CSSProperties;
    return <span className="code-line" style={style} key={lineIndex}>{parts}</span>;
  });
}

function CopyableCode({ value, label, copyLabel, copiedLabel, language = "json" }: {
  value: string;
  label: string;
  copyLabel: string;
  copiedLabel: string;
  language?: "json" | "python" | "text";
}) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    await copyArchitectureJson(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <div className={`architecture-json-example language-${language}`}>
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
      <pre><code>{highlightedCode(value, language)}</code></pre>
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
          <CopyableCode value={architecturePlaceExample} label={copy.jsonLabel} copyLabel={copy.copyJson} copiedLabel={copy.copiedJson} />
        </section>
      </div>
    </section>
  );
}

function DroneProductView({ facts }: { facts: readonly (readonly [string, string])[] }) {
  const sourcePoints = [
    [388, 274],
    [424, 193],
    [579, 113],
    [169, 138],
    [403, 343],
  ] as const;
  const targetY = [60, 160, 260, 360, 460] as const;
  return (
    <div className="architecture-drone-product">
      <div className="architecture-drone-visual">
        <img
          src="/docs/downloads/manual-assets/architecture-drone-x500.webp"
          alt="Realistic X500 V2 quadrotor product view"
          loading="lazy"
        />
      </div>
      <svg className="architecture-drone-connectors" viewBox="0 0 1000 520" preserveAspectRatio="none" aria-hidden="true">
        <path className="architecture-drone-baseline" d="M713 38 V482" />
        {sourcePoints.map(([x, y], index) => (
          <Fragment key={`${x}-${y}`}>
            <path d={`M${x} ${y} L650 ${targetY[index]} L713 ${targetY[index]}`} />
            <circle className="architecture-drone-source" cx={x} cy={y} r="7" />
            <circle className="architecture-drone-target" cx="713" cy={targetY[index]} r="7" />
          </Fragment>
        ))}
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
        <img src="/docs/downloads/manual-assets/architecture-airspace-corridor.webp" alt={title} loading="lazy" />
      </div>
      <figcaption>{metrics.map(([term, value]) => <div key={term}><strong>{term}</strong><span>{value}</span></div>)}</figcaption>
    </figure>
  );
}

function ModelRequestCard({ label, copyLabel, copiedLabel }: { label: string; copyLabel: string; copiedLabel: string }) {
  return (
    <div className="architecture-model-request">
      <blockquote><span>Take off from the Science High School pickup point, collect the sealed sample at Chemicum, avoid roofs and trees, then return with at least 30% battery.</span></blockquote>
      <CopyableCode value={modelRequestExample} label={label} copyLabel={copyLabel} copiedLabel={copiedLabel} />
    </div>
  );
}

function ModelToolExamples({ examples, copyLabel, copiedLabel }: {
  examples: readonly (readonly [string, string])[];
  copyLabel: string;
  copiedLabel: string;
}) {
  const snippets = [routeToolExample, trajectoryToolExample, validationToolExample] as const;
  return (
    <div className="architecture-tool-examples">
      {examples.map(([title, body], index) => (
        <article key={title}>
          <h4><span>{String(index + 1).padStart(2, "0")}</span>{title}</h4>
          <p>{body}</p>
          <CopyableCode
            value={snippets[index]}
            label={`Python · ${title}`}
            copyLabel={copyLabel}
            copiedLabel={copiedLabel}
            language="python"
          />
        </article>
      ))}
    </div>
  );
}

function ModelVisionEvidence({ cards }: { cards: readonly (readonly [string, string])[] }) {
  const images = [
    "/docs/downloads/manual-assets/software-mission-chat.webp",
    "/docs/downloads/manual-assets/architecture-map-processing.webp",
    "/docs/downloads/manual-assets/runtime-route-live.webp",
  ] as const;
  return (
    <div className="architecture-vision-evidence">
      {cards.map(([title, body], index) => (
        <figure className={`architecture-vision-card is-${index + 1}`} key={title}>
          <div><img src={images[index]} alt={title} loading="lazy" /><span>{String(index + 1).padStart(2, "0")}</span></div>
          <figcaption><strong>{title}</strong><p>{body}</p></figcaption>
        </figure>
      ))}
    </div>
  );
}

function HarnessFlow({ alt }: { alt: string }) {
  return (
    <figure className="architecture-harness-diagram">
      <img src="/docs/downloads/manual-assets/architecture-harness-flow.png" alt={alt} loading="lazy" />
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
          <CopyableCode value={architectureVehicleExample} label={copy.jsonLabel} copyLabel={copy.copyJson} copiedLabel={copy.copiedJson} />
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-drone-transition-three">
          <ArchitectureSectionHeading number="03" id="architecture-drone-transition-three" title={copy.thirdTransition} />
          <p>{copy.thirdTransitionBody}</p><AirspaceDiagram title={copy.airspaceTitle} metrics={copy.metrics} />
        </section>
      </div>
    </section>
  );
}

function ArchitectureModel({ locale }: { locale: SiteLocale }) {
  const copy = architectureCopy[locale].model;
  return (
    <section className="manual-architecture-page is-model" aria-labelledby="architecture-model-title">
      <ArchitectureIntro id="architecture-model-title" title={copy.title} paragraphs={copy.paragraphs} icon={BrainCircuit} />
      <div className="architecture-map-sequence">
        <section className="architecture-map-transition" aria-labelledby="architecture-model-transition-one">
          <ArchitectureSectionHeading number="01" id="architecture-model-transition-one" title={copy.firstTransition} />
          <p>{copy.firstTransitionBody}</p>
          <ModelRequestCard label={copy.requestLabel} copyLabel={copy.copyCode} copiedLabel={copy.copiedCode} />
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-model-transition-two">
          <ArchitectureSectionHeading number="02" id="architecture-model-transition-two" title={copy.secondTransition} />
          <p>{copy.secondTransitionBody}</p>
          <ModelToolExamples examples={copy.toolExamples} copyLabel={copy.copyCode} copiedLabel={copy.copiedCode} />
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-model-transition-three">
          <ArchitectureSectionHeading number="03" id="architecture-model-transition-three" title={copy.thirdTransition} />
          <p>{copy.thirdTransitionBody}</p>
          <div className="architecture-structured-io">
            <CopyableCode value={systemPromptExample} label={copy.promptLabel} copyLabel={copy.copyCode} copiedLabel={copy.copiedCode} language="text" />
            <CopyableCode value={structuredOutputExample} label={copy.outputLabel} copyLabel={copy.copyCode} copiedLabel={copy.copiedCode} />
          </div>
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-model-transition-four">
          <ArchitectureSectionHeading number="04" id="architecture-model-transition-four" title={copy.fourthTransition} />
          <p>{copy.fourthTransitionBody}</p>
          <ModelVisionEvidence cards={copy.visionCards} />
        </section>
        <section className="architecture-map-transition" aria-labelledby="architecture-model-transition-five">
          <ArchitectureSectionHeading number="05" id="architecture-model-transition-five" title={copy.fifthTransition} />
          <p>{copy.fifthTransitionBody}</p>
          <HarnessFlow alt={`${copy.fifthTransition} flowchart`} />
        </section>
      </div>
    </section>
  );
}

export default function ManualArchitecture({ locale, section }: ManualArchitectureProps) {
  if (section === "drone") return <ArchitectureDrone locale={locale} />;
  if (section === "model") return <ArchitectureModel locale={locale} />;
  return <ArchitectureMap locale={locale} />;
}
