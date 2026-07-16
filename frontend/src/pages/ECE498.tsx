import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import type { Locale } from "../i18n/I18nProvider";

import "./ECE498.css";

type CourseStageId =
  | "hw1"
  | "hw2"
  | "hw3"
  | "hw4"
  | "hw5"
  | "final"
  | "dronedream";

type StageGlyphKind =
  | "reason"
  | "simulate"
  | "tools"
  | "benchmark"
  | "memory"
  | "study"
  | "product";

interface CourseStage {
  id: CourseStageId;
  code: string;
  kicker: string;
  title: string;
  summary: string;
  evidence: string;
  principle: string;
  glyph: StageGlyphKind;
}

interface CourseCopy {
  pageEyebrow: string;
  courseName: string;
  subtitle: string;
  summary: string;
  professorEyebrow: string;
  professorName: string;
  gratitude: string;
  memoryLabel: string;
  memoryStory: string;
  professorStoryCta: string;
  professorStoryTitle: string;
  professorStoryParagraphs: string[];
  closeProfessorStory: string;
  harnessFlow: string[];
  timelineEyebrow: string;
  timelineTitle: string;
  timelineHint: string;
  detailLabel: string;
  evidenceLabel: string;
  applicabilityLabel: string;
  fields: string[];
  courseLink: string;
  professorLink: string;
  linksLabel: string;
  disclaimer: string;
  timelineAriaLabel: string;
  stages: CourseStage[];
}

const COURSE_URL = "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html";
const PROFESSOR_URL = "https://binhu7.github.io/";

const COURSE_COPY: Record<Locale, CourseCopy> = {
  en: {
    pageEyebrow: "A STUDENT-BUILT COURSE TRIBUTE",
    courseName: "LLM Reasoning for Engineering",
    subtitle: "From plausible answers to verified engineering systems",
    summary:
      "This course asks a harder question than ‘Can an LLM answer?’: can its output survive tools, simulation, controlled comparison, and domain verification? DroneDream is my attempt to carry that discipline from coursework into a complete product.",
    professorEyebrow: "WITH DEEP GRATITUDE",
    professorName: "Professor Bin Hu",
    gratitude:
      "Professor Hu teaches with exceptional care, intellectual honesty, and a rare sense for where engineering AI is heading. Every frontier idea must earn trust through a clear question, a verifier, evidence, and an honest account of failure. That rigor transformed a frustrating drone-tuning experience into DroneDream.",
    memoryLabel: "A student's classroom memory",
    memoryStory:
      "Long before I encountered the industry phrase ‘harness engineering,’ Professor Hu was already asking us to organize models, tools, structured outputs, automated verification, memory, and feedback loops into one engineering system. Only later did I understand how forward-looking that framework was.",
    professorStoryCta: "Read the classroom story",
    professorStoryTitle: "Why Professor Hu's course stayed with me",
    professorStoryParagraphs: [
      "Professor Hu teaches with unusual seriousness and generosity. He does not chase novelty for its own sake: new ideas are connected to engineering questions, evidence, failure analysis, and the responsibility to say exactly what a result does and does not prove. That combination made the course both timely and deeply practical.",
      "One class left a lasting impression on me. Professor Hu unexpectedly shared two readings about what was then still an unfamiliar idea: harness engineering. Many of us had never heard the term, and it felt almost out of place in the AI vocabulary of that moment. He nevertheless unpacked the articles and the system-level thinking behind them — how tools, context, verification, memory, and feedback can unlock capability that the base model alone cannot reliably deliver.",
      "The idea later became central to how the AI community discusses useful model capability. Looking back, the lecture was remarkably prescient. More importantly, it changed how I build: DroneDream is not an LLM asked to guess controller gains. It is a carefully bounded harness in which models propose, PX4 and Gazebo execute, verifiers judge, failures become evidence, and people retain authority.",
      "I am sincerely grateful to Professor Hu for a course that was innovative without being careless, current without being superficial, and ambitious without relaxing engineering standards. DroneDream exists because the course encouraged me to turn a real frustration into a question that could be tested, audited, improved, and eventually shared with others.",
    ],
    closeProfessorStory: "Close classroom story",
    harnessFlow: ["MODEL", "TOOLS", "VERIFY", "LEARN"],
    timelineEyebrow: "COURSEWORK → ENGINEERING SYSTEM",
    timelineTitle: "Seven steps from reasoning to DroneDream",
    timelineHint: "Hover, focus, or select a milestone to inspect the lesson it contributed.",
    detailLabel: "What this stage changed",
    evidenceLabel: "Evidence and boundary",
    applicabilityLabel: "Beyond drones, the method travels",
    fields: [
      "Control systems",
      "Circuits & hardware",
      "Signal processing",
      "Aerospace",
      "Materials & bioengineering",
      "Financial engineering",
    ],
    courseLink: "Course website",
    professorLink: "Professor Hu's homepage",
    linksLabel: "Explore the course",
    disclaimer: "A personal student tribute and project retrospective — not an official UIUC or course webpage.",
    timelineAriaLabel: "Course project progression",
    stages: [
      {
        id: "hw1",
        code: "HW1",
        kicker: "REASON & EVALUATE",
        title: "From answering to being verifiable",
        summary:
          "Autonomous-driving VideoQA paired a structured choice, frame-by-frame rationale, and confidence with exact-answer checks and a second-model evidence audit.",
        evidence:
          "Independent samples passed 5/5, but the important result was recognizing the easy single-question setup and the boundary between visual evidence and an invented claim.",
        principle: "Question the reasoning before trusting the answer.",
        glyph: "reason",
      },
      {
        id: "hw2",
        code: "HW2",
        kicker: "SIMULATE & REFINE",
        title: "Put the answer inside an engineering loop",
        summary:
          "The model proposed flight-control gains and limits; PX4 and Gazebo judged them across trajectories and disturbances. A valid schema could no longer masquerade as a valid design.",
        evidence:
          "Only 2/5 independent proposals passed. Precise verifier feedback then drove a three-round Fail → Fail → Pass refinement trace.",
        principle: "Execution is not domain success.",
        glyph: "simulate",
      },
      {
        id: "hw3",
        code: "HW3",
        kicker: "TOOLS & FEEDBACK",
        title: "Close the tool-assisted tuning loop",
        summary:
          "Five drone tasks shared one verifier for tracking error, overshoot, and stability. The model read simulator feedback and proposed the next bounded parameter set.",
        evidence:
          "No-tool performance was 13/25; tool augmentation reached 22/25. Refinement recovered three first-round failures without making unverified decisions.",
        principle: "Let evidence, not fluency, steer the next step.",
        glyph: "tools",
      },
      {
        id: "hw4",
        code: "HW4",
        kicker: "BENCHMARK & DIAGNOSE",
        title: "Move from one task to problem families",
        summary:
          "The original worksheet was unavailable, so this bridge is reconstructed from HW5 and the final guide: task families, repeated trials, a common verifier, logs, and explicit failure categories.",
        evidence:
          "Per-trial records made tracking, reliability, safety, and infrastructure failures diagnosable instead of anecdotal — the bridge from a demo to an auditable benchmark.",
        principle: "A system is credible only when its failures are legible.",
        glyph: "benchmark",
      },
      {
        id: "hw5",
        code: "HW5",
        kicker: "MEMORY & SAFETY",
        title: "Remember experience — and distrust bad memory",
        summary:
          "Past trials became reusable engineering lessons retrieved by task family and failure mode. The same study tested how overgeneralized or adversarial memories can poison later decisions.",
        evidence:
          "Hard-task success rose from 26.7% to 63.3% with memory, while a misleading lesson drove one task from 4/5 to 1/5 — benefit and risk measured together.",
        principle: "Memory is a soft prior, never proof.",
        glyph: "memory",
      },
      {
        id: "final",
        code: "FINAL",
        kicker: "CONTROLLED STUDY",
        title: "Turn coursework into an honest engineering study",
        summary:
          "A real ECE484 tuning pain point became a specific question with prior predictions, controlled conditions, acceptance criteria, trial budgets, reproducibility artifacts, and limitations.",
        evidence:
          "Nine course-report cases compared baselines, search, GPT proposals, and refinement. The evidence is simulator-grounded; it is explicitly not a claim of physical-flight safety.",
        principle: "State what the experiment proves — and what it does not.",
        glyph: "study",
      },
      {
        id: "dronedream",
        code: "DRONEDREAM",
        kicker: "PRODUCT EXTENSION",
        title: "Make the verified loop usable",
        summary:
          "DroneDream extends the course project into a platform that joins experiment design, bounded proposals, workers, simulator adapters, acceptance rules, diagnostics, histories, and reports.",
        evidence:
          "The LLM proposes hypotheses; simulation and acceptance criteria decide whether to use them. The product preserves the course's central separation between intelligence and authority.",
        principle: "Build an engineering harness around the model.",
        glyph: "product",
      },
    ],
  },
  "zh-CN": {
    pageEyebrow: "学生制作的课程致敬页",
    courseName: "大语言模型在工程推理中的应用",
    subtitle: "从看似合理的回答，走向经得起验证的工程系统",
    summary:
      "这门课追问的不是“大模型能不能给出答案”，而是它的输出能不能经受工具、仿真、受控比较与领域验证。DroneDream 是我把这套训练从课程作业延伸为完整产品的一次长期尝试。",
    professorEyebrow: "特别致谢",
    professorName: "胡斌教授",
    gratitude:
      "胡斌教授教学极其认真负责，对学术诚实和工程证据始终有很高要求，也对工程智能的发展方向有难得的前瞻性。每一个前沿想法都必须用清楚的问题、验证器、实验证据和对失败的诚实复盘来赢得信任。正是这份严谨，让一次令人困扰的无人机调参经历逐渐成长为 DroneDream。",
    memoryLabel: "一段学生亲历的课堂记忆",
    memoryStory:
      "在 harness engineering 这个概念后来受到广泛关注之前，胡斌教授已经在课堂中要求我们把模型、工具、结构化输出、自动验证、记忆与反馈循环组织成完整工程系统。后来回头看，我才真正理解这套课程框架有多么前瞻。",
    professorStoryCta: "展开这段课堂故事",
    professorStoryTitle: "为什么胡斌教授的课程让我印象如此深刻",
    professorStoryParagraphs: [
      "胡斌教授对教学极其认真负责，也非常愿意把真正前沿的研究思想带进课堂。他不会为了追逐新概念而停留在表面，而是始终把新方法放回工程问题、实验证据、失败分析和研究责任之中。正因如此，这门课既紧跟时代，又不是一门只展示新名词的课。",
      "那学期有一节课让我至今记忆很深。老师突然给了我们两篇讨论 harness engineering 的文章。当时这个概念远没有后来这样受到重视，班上的同学也普遍没有听说过，甚至觉得这个词出现在人工智能课堂里有些突兀。胡斌教授却已经开始讲解文章中的系统思想：如何把工具、上下文、结构化输出、自动验证、记忆和反馈组织起来，让基础模型无法独立稳定完成的任务成为可能。",
      "后来，这套思想逐渐成为提升模型真实能力的重要方向。回头再看，那堂课非常有前瞻性；更重要的是，它改变了我做工程的方式。DroneDream 并不是让大模型凭感觉猜一组控制参数，而是在模型外建立边界清楚的工程支撑体系：模型负责提出假设，PX4 与 Gazebo 负责执行，验证器负责裁决，失败结果成为下一轮证据，而最终决定权始终由人掌握。",
      "我真诚感谢胡斌教授开设并认真打磨这门课程。它有创新性，却从不牺牲严谨；它关注最新进展，却不流于表面；它鼓励大胆探索，也要求我们诚实说明每个结果究竟证明了什么、还没有证明什么。正是这样的训练，让我把一次真实的无人机调参困难转化成可以实验、可以审计、可以持续改进，并最终愿意分享给更多人的 DroneDream。",
    ],
    closeProfessorStory: "关闭课堂故事",
    harnessFlow: ["模型", "工具", "验证", "学习"],
    timelineEyebrow: "课程作业 → 工程系统",
    timelineTitle: "从推理到 DroneDream 的七个阶段",
    timelineHint: "悬停、键盘聚焦或点击任一节点，可以查看它为项目留下的能力。",
    detailLabel: "这一阶段改变了什么",
    evidenceLabel: "证据与边界",
    applicabilityLabel: "这套方法并不止于无人机",
    fields: ["控制系统", "电路与硬件", "信号处理", "航空航天", "材料与生化", "金融工程"],
    courseLink: "课程官网",
    professorLink: "胡斌教授主页",
    linksLabel: "进一步了解课程",
    disclaimer: "本页为学生个人课程致敬与项目回顾，并非 UIUC 或课程官方页面。",
    timelineAriaLabel: "课程项目成长时间线",
    stages: [
      {
        id: "hw1",
        code: "作业一",
        kicker: "推理与评估",
        title: "从会回答，到能被验证",
        summary:
          "自动驾驶视频问答把结构化选择、逐帧推理与置信度交给精确答案核对和第二个模型的证据审查，不再把一段流畅解释直接当作正确。",
        evidence:
          "五次独立采样全部通过；更重要的是主动识别了单题过易，以及“根据遮挡预判风险”和“声称看见并不存在的证据”之间的边界。",
        principle: "先怀疑推理，再相信答案。",
        glyph: "reason",
      },
      {
        id: "hw2",
        code: "作业二",
        kicker: "仿真与改进",
        title: "让答案进入真实工程闭环",
        summary:
          "模型提出飞行控制增益与限制，再由 PX4 和 Gazebo 在多种轨迹与扰动中判定。结构化格式正确，从此不能再冒充工程设计正确。",
        evidence:
          "五次独立提议只有两次通过；验证器明确指出哪项指标超出多少后，系统留下了一条“失败 → 失败 → 通过”的三轮改进轨迹。",
        principle: "代码跑通，不等于领域任务成功。",
        glyph: "simulate",
      },
      {
        id: "hw3",
        code: "作业三",
        kicker: "工具与反馈",
        title: "把工具、仿真和反馈接成回路",
        summary:
          "五个无人机任务共用一套跟踪误差、超调和稳定性验证器；模型读取仿真反馈，再提出下一组受边界约束的参数。",
        evidence:
          "无工具条件为十三次通过、十二次失败；加入工具后达到二十二次通过、三次失败。多轮改进还救回了三次首轮失败。",
        principle: "让证据，而不是语言流畅度，决定下一步。",
        glyph: "tools",
      },
      {
        id: "hw4",
        code: "作业四",
        kicker: "基准与诊断",
        title: "从一道题走向问题家族",
        summary:
          "作业四原始文档暂缺，因此这一桥梁依据作业五与课程项目指南重建：问题家族、重复试验、统一验证接口、仿真日志和明确的失败分类。",
        evidence:
          "逐次记录让跟踪、可靠性、安全和基础设施故障都能够被诊断，而不再只是一次演示中的偶然现象；这一步把原型连接到可审计基准。",
        principle: "只有失败可以被读懂，系统才值得信任。",
        glyph: "benchmark",
      },
      {
        id: "hw5",
        code: "作业五",
        kicker: "记忆与安全",
        title: "让系统记住，也学会怀疑记忆",
        summary:
          "历史试验被提炼为可按问题家族与失败机理检索的工程经验；同一研究也检验了过度泛化和恶意记忆怎样污染后续决策。",
        evidence:
          "困难题通过率由百分之二十六点七提升到百分之六十三点三；一条误导经验又让某题由五次通过四次跌至仅通过一次。收益与风险被同时测量。",
        principle: "记忆只能是软先验，不能成为证明。",
        glyph: "memory",
      },
      {
        id: "final",
        code: "课程项目",
        kicker: "受控研究",
        title: "把一次作业变成诚实的工程研究",
        summary:
          "ECE484 中真实的调参困难被重构成具体问题，并配上事前预测、对照条件、验收标准、试验预算、可复现材料和局限讨论。",
        evidence:
          "课程报告用九个案例比较默认参数、搜索、模型提议和多轮改进。它提供的是仿真证据，明确不能被包装成真实飞行安全结论。",
        principle: "既说清实验证明了什么，也说清它没有证明什么。",
        glyph: "study",
      },
      {
        id: "dronedream",
        code: "DRONEDREAM",
        kicker: "产品延伸",
        title: "让经过验证的闭环真正可用",
        summary:
          "DroneDream 把课程项目延伸为一个连接实验设计、受约束提议、任务执行、仿真适配、验收规则、诊断、历史与报告的平台。",
        evidence:
          "大模型负责提出可检验的假设，仿真结果和验收条件负责决定是否采用。产品继续坚持课程所强调的“智能”与“决策权限”分离。",
        principle: "在模型周围建立完整工程支撑体系。",
        glyph: "product",
      },
    ],
  },
};

function ExternalArrow() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M5 3h8v8M13 3 4 12M11 9v4H3V5h4" />
    </svg>
  );
}

function StageGlyph({ kind }: { kind: StageGlyphKind }) {
  let drawing: ReactNode;

  switch (kind) {
    case "reason":
      drawing = (
        <>
          <path d="M6 24s6-10 18-10 18 10 18 10-6 10-18 10S6 24 6 24Z" />
          <circle cx="24" cy="24" r="4.5" />
          <path d="m33 10 3-4m-21 4-3-4" />
        </>
      );
      break;
    case "simulate":
      drawing = (
        <>
          <path d="M5 27c5-14 9 14 14 0s9-14 14 0 7 2 10-3" />
          <path d="m31 13 4 4 8-9" />
          <path d="M7 38h34" />
        </>
      );
      break;
    case "tools":
      drawing = (
        <>
          <path d="M15 13a14 14 0 0 1 22 5" />
          <path d="m38 11-1 7-7-1" />
          <path d="M33 35a14 14 0 0 1-22-5" />
          <path d="m10 37 1-7 7 1" />
          <path d="m19 26 4 4 8-11" />
        </>
      );
      break;
    case "benchmark":
      drawing = (
        <>
          <rect x="7" y="8" width="34" height="32" rx="4" />
          <path d="M7 19h34M18 19v21M30 19v21" />
          <path d="m11 14 2 2 3-4m6 14 2 2 3-4m10 8-3 3m0-3 3 3" />
        </>
      );
      break;
    case "memory":
      drawing = (
        <>
          <circle cx="24" cy="11" r="5" />
          <circle cx="11" cy="34" r="5" />
          <circle cx="37" cy="34" r="5" />
          <path d="m21 15-7 14m13-14 7 14M16 34h16" />
          <path d="M24 21v10m-3-3 3 3 3-3" />
        </>
      );
      break;
    case "study":
      drawing = (
        <>
          <path d="M12 5h18l7 7v31H12z" />
          <path d="M30 5v8h7M18 21h13M18 28h13M18 35h8" />
          <circle cx="9" cy="39" r="4" />
          <path d="m12 42 4 3" />
        </>
      );
      break;
    case "product":
      drawing = (
        <>
          <path d="M14 17h20l5 7-5 7H14l-5-7z" />
          <path d="M18 17 13 9m17 8 5-8M18 31l-5 8m17-8 5 8" />
          <circle cx="11" cy="7" r="5" />
          <circle cx="37" cy="7" r="5" />
          <circle cx="11" cy="41" r="5" />
          <circle cx="37" cy="41" r="5" />
          <path d="M21 24h6" />
        </>
      );
      break;
  }

  return (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      {drawing}
    </svg>
  );
}

function EngineeringBackdrop() {
  return (
    <svg className="ece498-engineering-backdrop" viewBox="0 0 1400 820" aria-hidden="true" preserveAspectRatio="none">
      <defs>
        <linearGradient id="ece498-flight-gradient" x1="0" x2="1">
          <stop offset="0" stopColor="#71e7ff" stopOpacity="0" />
          <stop offset="0.45" stopColor="#71e7ff" stopOpacity="0.68" />
          <stop offset="1" stopColor="#ff74d8" stopOpacity="0" />
        </linearGradient>
        <radialGradient id="ece498-orbit-glow">
          <stop offset="0" stopColor="#ca7dff" stopOpacity="0.22" />
          <stop offset="1" stopColor="#ca7dff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="1120" cy="165" r="215" fill="url(#ece498-orbit-glow)" />
      <g className="ece498-constellation">
        <path d="M44 110 182 62l114 82 148-91 121 83 154-58" />
        <path d="m929 95 105 69 145-92 153 108" />
        <circle cx="44" cy="110" r="3" />
        <circle cx="182" cy="62" r="4" />
        <circle cx="296" cy="144" r="3" />
        <circle cx="444" cy="53" r="4" />
        <circle cx="565" cy="136" r="3" />
        <circle cx="719" cy="78" r="4" />
        <circle cx="929" cy="95" r="3" />
        <circle cx="1034" cy="164" r="4" />
        <circle cx="1179" cy="72" r="3" />
        <circle cx="1332" cy="180" r="4" />
      </g>
      <g className="ece498-circuit-lines">
        <path d="M0 650h170v-62h118v73h146" />
        <path d="M1400 615h-164v-84h-132v76H982" />
        <path d="M0 720h96v-34h78" />
        <path d="M1400 710h-96v-46h-82" />
        <circle cx="170" cy="650" r="5" />
        <circle cx="288" cy="588" r="5" />
        <circle cx="1236" cy="615" r="5" />
        <circle cx="1104" cy="531" r="5" />
      </g>
      <path
        className="ece498-flight-path"
        d="M72 410c160-122 274 116 430-8s289-132 410 6 269 62 420-58"
        stroke="url(#ece498-flight-gradient)"
      />
      <g transform="translate(1140 205)">
        <g className="ece498-orbit">
          <ellipse rx="154" ry="58" />
          <ellipse rx="154" ry="58" transform="rotate(61)" />
          <ellipse rx="154" ry="58" transform="rotate(119)" />
        </g>
      </g>
    </svg>
  );
}

export function ECE498() {
  const { locale } = useI18n();
  const copy = COURSE_COPY[locale];
  const [activeStageId, setActiveStageId] = useState<CourseStageId>("dronedream");
  const [professorStoryOpen, setProfessorStoryOpen] = useState(false);
  const professorStoryButtonRef = useRef<HTMLButtonElement>(null);
  const professorStoryCloseRef = useRef<HTMLButtonElement>(null);
  const professorStoryDialogRef = useRef<HTMLElement>(null);
  const activeStage = useMemo(
    () => copy.stages.find((stage) => stage.id === activeStageId) ?? copy.stages[0],
    [activeStageId, copy.stages],
  );
  const activeIndex = copy.stages.findIndex((stage) => stage.id === activeStage.id);
  const timelineStyle = {
    "--ece498-progress": `${(activeIndex / Math.max(copy.stages.length - 1, 1)) * 100}%`,
  } as CSSProperties;

  useEffect(() => {
    if (!professorStoryOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusFrame = window.requestAnimationFrame(() => professorStoryCloseRef.current?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setProfessorStoryOpen(false);
        window.requestAnimationFrame(() => professorStoryButtonRef.current?.focus());
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(professorStoryDialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? []);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (focusable.length === 1 || (event.shiftKey && document.activeElement === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [professorStoryOpen]);

  const handleTimelineKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    const finalIndex = copy.stages.length - 1;
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = currentIndex === finalIndex ? 0 : currentIndex + 1;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = currentIndex === 0 ? finalIndex : currentIndex - 1;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = finalIndex;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    const nextStage = copy.stages[nextIndex];
    if (!nextStage) return;
    setActiveStageId(nextStage.id);
    event.currentTarget.parentElement
      ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex]
      ?.focus();
  };

  return (
    <article className="ece498-course-page" data-locale={locale}>
      <EngineeringBackdrop />

      <header className="ece498-course-hero">
        <div className="ece498-course-intro">
          <span className="ece498-eyebrow">{copy.pageEyebrow}</span>
          <h1 aria-label={`ECE 498 BH — ${copy.courseName}`}>
            <span>ECE 498 BH</span>
            {copy.courseName}
          </h1>
          <p className="ece498-course-subtitle">{copy.subtitle}</p>
          <p className="ece498-course-summary">{copy.summary}</p>
        </div>

        <aside className="ece498-professor-card" aria-labelledby="ece498-professor-name">
          <div className="ece498-professor-mark" aria-hidden="true">
            <span>BH</span>
            <i />
          </div>
          <div className="ece498-professor-copy">
            <span className="ece498-eyebrow">{copy.professorEyebrow}</span>
            <h2 id="ece498-professor-name">{copy.professorName}</h2>
            <p>{copy.gratitude}</p>
          </div>
          <blockquote className="ece498-memory-story">
            <span>{copy.memoryLabel}</span>
            <p>{copy.memoryStory}</p>
          </blockquote>
          <button
            ref={professorStoryButtonRef}
            type="button"
            className="ece498-professor-story-button"
            aria-haspopup="dialog"
            aria-expanded={professorStoryOpen}
            onClick={() => setProfessorStoryOpen(true)}
          >
            <span>{copy.professorStoryCta}</span>
            <ExternalArrow />
          </button>
        </aside>
      </header>

      {professorStoryOpen ? (
        <div
          className="ece498-story-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target !== event.currentTarget) return;
            setProfessorStoryOpen(false);
            window.requestAnimationFrame(() => professorStoryButtonRef.current?.focus());
          }}
        >
          <section
            ref={professorStoryDialogRef}
            className="ece498-story-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ece498-story-title"
          >
            <header>
              <div>
                <span className="ece498-eyebrow">{copy.professorEyebrow}</span>
                <h2 id="ece498-story-title">{copy.professorStoryTitle}</h2>
              </div>
              <button
                ref={professorStoryCloseRef}
                type="button"
                className="ece498-story-close"
                aria-label={copy.closeProfessorStory}
                title={copy.closeProfessorStory}
                onClick={() => {
                  setProfessorStoryOpen(false);
                  window.requestAnimationFrame(() => professorStoryButtonRef.current?.focus());
                }}
              >
                <span aria-hidden="true">×</span>
              </button>
            </header>
            <div className="ece498-story-body">
              {copy.professorStoryParagraphs.map((paragraph) => (
                <p key={paragraph}>{paragraph}</p>
              ))}
            </div>
            <div className="ece498-story-harness" aria-hidden="true">
              {copy.harnessFlow.map((step, index) => (
                <div key={step}>
                  <span>{step}</span>
                  {index < copy.harnessFlow.length - 1 ? <i /> : null}
                </div>
              ))}
            </div>
          </section>
        </div>
      ) : null}

      <section className="ece498-timeline-panel" aria-labelledby="ece498-timeline-title">
        <div className="ece498-timeline-heading">
          <div>
            <span className="ece498-eyebrow">{copy.timelineEyebrow}</span>
            <h2 id="ece498-timeline-title">{copy.timelineTitle}</h2>
          </div>
          <p>{copy.timelineHint}</p>
        </div>

        <div
          className="ece498-timeline-track"
          role="tablist"
          aria-label={copy.timelineAriaLabel}
          style={timelineStyle}
        >
          <div className="ece498-timeline-rail" aria-hidden="true">
            <span />
          </div>
          {copy.stages.map((stage, index) => {
            const selected = stage.id === activeStage.id;
            return (
              <button
                key={stage.id}
                id={`ece498-tab-${stage.id}`}
                className={`ece498-timeline-node${selected ? " is-active" : ""}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls="ece498-stage-detail"
                onClick={() => setActiveStageId(stage.id)}
                onMouseEnter={() => setActiveStageId(stage.id)}
                onFocus={() => setActiveStageId(stage.id)}
                onKeyDown={(event) => handleTimelineKeyDown(event, index)}
                tabIndex={selected ? 0 : -1}
              >
                <span className="ece498-node-index" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="ece498-node-glyph">
                  <StageGlyph kind={stage.glyph} />
                </span>
                <span className="ece498-node-code">{stage.code}</span>
                <span className="ece498-node-title">{stage.title}</span>
              </button>
            );
          })}
        </div>

        <div
          id="ece498-stage-detail"
          className="ece498-stage-detail"
          role="tabpanel"
          aria-live="polite"
          aria-labelledby={`ece498-tab-${activeStage.id}`}
        >
          <div className="ece498-stage-identity">
            <span className="ece498-detail-glyph">
              <StageGlyph kind={activeStage.glyph} />
            </span>
            <div>
              <span className="ece498-stage-kicker">{activeStage.kicker}</span>
              <h3>{activeStage.title}</h3>
              <strong>{activeStage.principle}</strong>
            </div>
          </div>
          <div className="ece498-stage-copy">
            <span>{copy.detailLabel}</span>
            <p>{activeStage.summary}</p>
          </div>
          <div className="ece498-stage-copy ece498-stage-evidence">
            <span>{copy.evidenceLabel}</span>
            <p>{activeStage.evidence}</p>
          </div>
        </div>
      </section>

      <footer className="ece498-course-footer">
        <div className="ece498-applications">
          <span>{copy.applicabilityLabel}</span>
          <div>
            {copy.fields.map((field) => (
              <b key={field}>{field}</b>
            ))}
          </div>
        </div>
        <nav className="ece498-course-links" aria-label={copy.linksLabel}>
          <a href={COURSE_URL} target="_blank" rel="noreferrer">
            {copy.courseLink}
            <ExternalArrow />
          </a>
          <a href={PROFESSOR_URL} target="_blank" rel="noreferrer">
            {copy.professorLink}
            <ExternalArrow />
          </a>
        </nav>
        <p className="ece498-disclaimer">{copy.disclaimer}</p>
      </footer>
    </article>
  );
}
