import {
  BookOpen,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Download,
  FileDown,
  FileText,
  Gauge,
  History,
  MessageSquareText,
  Route,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { useState } from "react";

type SiteLocale = "en" | "zh-CN";

interface ManualPageProps {
  locale: SiteLocale;
}

const manualContent = {
  en: {
    eyebrow: "DRONEDREAM MANUAL",
    title: "Build explainable tuning experiments.",
    mobileTitle: "Explain every experiment.",
    intro:
      "This manual follows the complete DroneDream workflow, from installing the Windows application to reviewing an evidence-backed result. Each chapter explains the controls, engineering decisions, and reproducibility checks, while matching Markdown and PDF editions preserve the same reference structure for offline reading.",
    search: "Search this manual",
    contents: "On this page",
    downloads: "Offline copies",
    downloadMarkdown: "Markdown",
    downloadPdf: "PDF",
    chapters: [
      ["start", "Start here"],
      ["install", "Install and prepare"],
      ["assistant", "Create with Tuning Chat"],
      ["wizard", "Five-step experiment"],
      ["track", "Edit a flight track"],
      ["results", "Review results"],
      ["safety", "Data and safety"],
    ],
    startTitle: "Start here",
    startBody:
      "DroneDream is a local-first workspace for configuring, simulating, and comparing PX4 controller parameters. Language models clarify intent and prepare reviewable drafts; deterministic validation, constraints, acceptance rules, and human review keep every experiment reproducible. Every accepted proposal remains traceable to the settings, trials, and evidence that produced it with clear provenance.",
    before: "Before you begin",
    beforeItems: [
      "Use Windows 10 or Windows 11 on an x64 computer.",
      "Keep at least 52 GiB free on a writable NTFS drive for the isolated runtime.",
      "Create a DroneDream account, then configure a model only when you want Tuning Chat or an LLM-guided strategy.",
      "Treat every generated parameter set as simulation evidence, never as automatic approval for hardware flight.",
    ],
    installTitle: "Install and prepare the local runtime",
    installBody:
      "Install the desktop application first. DroneDream then prepares a dedicated WSL2 runtime for PX4, Gazebo, workers, and experiment artifacts without reusing a personal Ubuntu distribution. The tuning workspace opens only after the environment check reaches Checked and the runtime is ready for use.",
    installSteps: [
      ["Download", "Download the current 1.0.0 Windows installer from the official website."],
      ["Install", "Choose an eligible local drive and keep the recommended application directory."],
      ["Prepare runtime", "Follow the first-launch progress screen while the isolated distribution is imported and verified."],
      ["Open workspace", "Continue only after the status light is green and the environment state reads Checked."],
    ],
    assistantTitle: "Create an experiment with Tuning Chat",
    assistantBody:
      "Tuning Chat is the fastest way to turn an ordinary description into a structured experiment draft. Describe the aircraft, route, target behavior, disturbances, and priorities in plain language or by voice. DroneDream extracts known values, lists missing decisions, and never starts a job without explicit review.",
    assistantExampleTitle: "Example request",
    assistantExample:
      "Tune an x500 quadrotor on a 5 m circular track at 3 m altitude. Prioritize tracking accuracy, include moderate sensor noise, and keep the experiment within 180 trials.",
    assistantResult:
      "Expected result: a named draft with the flight setup, objective, scenario, and budget filled where the request is explicit. Missing PX4 parameter ranges and final acceptance thresholds remain visible and must be confirmed before the draft can enter final review.",
    wizardTitle: "Complete the five-step experiment",
    wizardBody:
      "The manual workflow is available for users who want direct control of every field. Each step validates its own inputs and preserves the current position, so returning to a draft opens the same experiment at the last completed stage.",
    wizardSteps: [
      ["1", "Flight Setup", "Choose experience level, vehicle, PX4 profile, Gazebo world, objective weights, and the flight track."],
      ["2", "Parameters", "Select only the PX4 controller parameters that should change, then confirm baseline, minimum, and maximum values."],
      ["3", "Scenarios", "Define search and holdout cases, wind, sensor noise, seeds, payload, battery, and environmental effects."],
      ["4", "Constraints & Budget", "Select the simulator and optimization strategy, then set trial limits, target metrics, and pass thresholds."],
      ["5", "Review", "Audit the complete configuration, inspect selected parameter ranges, and create the experiment only when every boundary is correct."],
    ],
    trackTitle: "Edit a custom flight track",
    trackBody:
      "The track editor keeps the plot and coordinate table aligned at equal height. Switch among XY, XZ, YZ, and 3D views, edit exact coordinates in the table, and use JSON import or export when a path is easier to generate externally.",
    trackCallout:
      "In 3D view, the ground grid preserves equal real-world units on both axes. Extending a route adds square cells instead of stretching the existing grid into rectangles, keeping scale truthful as the route grows in any direction.",
    resultsTitle: "Review history and evidence",
    resultsBody:
      "Dashboard and Run History summarize each experiment without hiding failures. Filter by status, track, objective, strategy, or date; compare compatible runs; and open a result to inspect metrics, scenarios, logs, artifacts, and the complete configuration that produced it across future revisions and reviews.",
    evidence: [
      ["Configuration", "Vehicle, firmware, route, ranges, constraints, optimizer, and budget."],
      ["Execution", "Scenario identity, seeds, runtime manifest, process logs, and simulation artifacts."],
      ["Decision", "Feasibility, tracking error, overshoot, settling time, robustness, and Pareto trade-offs."],
    ],
    safetyTitle: "Account, data, and safety boundaries",
    safetyBody:
      "Accounts are isolated by Supabase identity and row-level policies. Public community topics are intentionally shared, while experiment drafts, account settings, and future cloud workspaces remain scoped to their owner. API keys stay in the current application session and are never written into experiment drafts or local histories.",
    safetyNote:
      "DroneDream assists engineering judgment; it does not replace it. Validate every selected controller parameter set in an independent SITL process, review its safety envelope, and preserve the evidence before considering any test on real hardware.",
  },
  "zh-CN": {
    eyebrow: "DRONEDREAM 使用说明",
    title: "创建可解释、可复查的调优实验。",
    mobileTitle: "创建可解释实验。",
    intro:
      "这份说明书覆盖 DroneDream 的完整使用流程，从安装 Windows 客户端，到创建实验、编辑轨迹和审查仿真结果。每一章不仅说明按钮怎么操作，也会解释对应设置的工程含义以及保证实验可复现的检查边界。",
    search: "搜索说明书",
    contents: "本页目录",
    downloads: "离线文档",
    downloadMarkdown: "Markdown",
    downloadPdf: "PDF",
    chapters: [
      ["start", "开始之前"],
      ["install", "安装与环境准备"],
      ["assistant", "通过调优对话创建"],
      ["wizard", "五环节实验配置"],
      ["track", "编辑飞行轨迹"],
      ["results", "查看结果与证据"],
      ["safety", "数据与安全边界"],
    ],
      startTitle: "开始之前",
      startBody:
        "DroneDream 是一个本地优先的 PX4 控制参数调优工作台，用来统一完成参数配置、候选搜索、Gazebo 仿真、结果比较和证据留存。大语言模型可以帮助理解意图并生成可审查草稿，但最终的约束校验、仿真执行和验收规则始终由确定性的工程流程控制，并为每次决策保留可复核的工程依据。",
    before: "开始前请确认",
    beforeItems: [
      "使用 Windows 10 或 Windows 11 的 x64 计算机。",
      "在可写入的 NTFS 磁盘上预留至少 52 GiB 空间，用于隔离运行环境。",
      "先创建 DroneDream 账户；只有需要调优对话或大模型策略时才配置模型。",
      "所有参数组合都只是仿真证据，不能被视为真实飞行的自动安全批准。",
    ],
    installTitle: "安装与环境准备",
    installBody:
      "先安装桌面客户端，随后由 DroneDream 准备专用的 WSL2 环境，用来容纳 PX4、Gazebo、工作进程和实验产物，不会复用或修改个人 Ubuntu。只有环境检查完成且状态显示 Checked，工作台入口才会真正开放。",
    installSteps: [
      ["下载安装包", "从官方网站下载当前的 1.0.0 Windows 安装程序，并核对版本。"],
      ["安装客户端", "选择符合条件的本地磁盘，并保留推荐的应用安装目录与空间设置。"],
      ["准备环境", "在首次启动页面等待隔离系统完成导入、启动和完整校验流程后再继续。"],
      ["进入工作台", "确认右上角变为绿色 Checked 后，再打开调优工作台继续配置后续实验。"],
    ],
    assistantTitle: "通过调优对话创建实验",
    assistantBody:
      "调优对话适合希望快速表达需求的用户。你可以用文字或语音描述飞行器、赛道、目标、扰动和优先级；DroneDream 会提取明确的信息，列出尚未说明的决策，并生成可以继续修改的实验草稿，而不会绕过审查直接启动任务。",
    assistantExampleTitle: "输入示例",
    assistantExample:
      "在 3 米高度让 x500 四旋翼沿半径 5 米的圆形赛道飞行，优先提高轨迹跟踪精度，加入中等强度的传感器噪声，并把总试验次数控制在 180 次以内。",
      assistantResult:
        "预期结果：系统会填写明确提到的飞行设置、优化目标、场景和预算；没有给出的 PX4 参数范围与最终验收阈值会继续保留为待确认项目，并在进入最终审查前由用户逐项确认，确保系统只在边界明确、结果可以追溯时推进到运行阶段，并保留完整证据与运行记录。",
      wizardTitle: "完成五个实验配置环节",
      wizardBody:
        "希望逐项控制所有设置的用户可以使用手动创建流程。每个环节分别校验自己的字段并记录当前位置，因此关闭后重新打开草稿时，会回到这个实验上一次停留的环节，并恢复填写状态与审查上下文。",
    wizardSteps: [
      ["1", "飞行设置", "选择经验等级、飞行器、PX4 配置、Gazebo 世界、目标权重和飞行轨迹。"],
      ["2", "控制参数", "只选择本次需要变化的 PX4 参数，并确认基线值、搜索下限和搜索上限。"],
      ["3", "仿真场景", "设置搜索与留出场景、风场、噪声、随机种子、载荷、电池及环境影响。"],
      ["4", "约束与预算", "选择仿真后端和优化策略，然后设置试验数量、目标指标和最低通过率。"],
      ["5", "最终审查", "复查完整配置和全部参数范围，确认所有边界正确后再创建并提交实验。"],
    ],
      trackTitle: "编辑自定义飞行轨迹",
      trackBody:
        "轨迹编辑器让坐标图和坐标表保持等高对齐。你可以切换 XY、XZ、YZ 和 3D 视图，在表格中输入精确坐标，也可以通过 JSON 导入或导出在其他工具中生成的路径，并即时核对每个航点的空间关系。",
    trackCallout:
      "3D 视图的地面网格在两个方向上使用相同的真实长度单位。轨迹延长时会向外增加正方形网格，而不是把现有方格拉伸成长方形。",
    resultsTitle: "查看历史记录和实验依据",
    resultsBody:
      "Dashboard 与 Run History 会如实展示每个实验和失败状态。用户可以按状态、轨迹、目标、策略和日期筛选任务，比较兼容实验，并进入详情查看指标、场景、日志、产物以及产生该结果的完整配置。",
    evidence: [
      ["配置依据", "记录飞行器、固件、轨迹、参数范围、约束、算法、完整预算和版本信息。"],
      ["执行依据", "保存场景标识、随机种子、运行清单、进程日志、完整仿真产物和校验摘要。"],
      ["决策依据", "比较可行性、跟踪误差、超调量、稳定时间、鲁棒性和 Pareto 权衡结果。"],
    ],
    safetyTitle: "账户、数据与安全边界",
    safetyBody:
      "账户通过 Supabase 身份和行级安全策略实现隔离。社区话题按设计公开共享，而实验草稿、账户设置和未来的云工作区仍然只属于创建者。模型 API Key 仅保存在当前应用会话中，不会写进实验草稿。",
    safetyNote:
      "DroneDream 用来辅助工程判断，而不是替代判断。任何候选控制参数都必须先经过独立的 SITL 安全验证，之后才可以考虑真实硬件。",
  },
} as const;

export function ManualPage({ locale }: ManualPageProps) {
  const copy = manualContent[locale];
  const screenshotRoot = locale === "en" ? "/docs/en" : "/docs/zh-CN";
  const downloadRoot = locale === "en"
    ? "/docs/downloads/DroneDream-Manual-en"
    : "/docs/downloads/DroneDream-Manual-zh-CN";
  const [query, setQuery] = useState("");
  const visibleChapters = copy.chapters.filter(([, label]) =>
    label.toLocaleLowerCase(locale).includes(query.trim().toLocaleLowerCase(locale)),
  );

  return (
    <div className="site-portal site-manual-page">
      <aside className="manual-sidebar" aria-label={copy.contents}>
        <div className="manual-sidebar-title">
          <BookOpen aria-hidden="true" />
          <strong>{copy.contents}</strong>
        </div>
        <label className="manual-search">
          <span className="site-sr-only">{copy.search}</span>
          <input
            type="search"
            placeholder={copy.search}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="manual-downloads" aria-label={copy.downloads}>
          <strong>{copy.downloads}</strong>
          <div>
            <a href={`${downloadRoot}.md`} download>
              <FileText aria-hidden="true" />
              {copy.downloadMarkdown}
            </a>
            <a href={`${downloadRoot}.pdf`} download>
              <FileDown aria-hidden="true" />
              {copy.downloadPdf}
            </a>
          </div>
        </div>
        <nav>
          {visibleChapters.map(([id, label]) => {
            const index = copy.chapters.findIndex(([chapterId]) => chapterId === id);
            return (
            <a key={id} href={`#${id}`}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              {label}
              <ChevronRight aria-hidden="true" />
            </a>
            );
          })}
        </nav>
      </aside>

      <article className="manual-article">
        <header className="manual-hero">
          <p className="site-eyebrow">{copy.eyebrow}</p>
          <h1 aria-label={copy.title}>
            <span aria-hidden="true" className="portal-title-desktop">{copy.title}</span>
            <span aria-hidden="true" className="portal-title-mobile">{copy.mobileTitle}</span>
          </h1>
          <p>{copy.intro}</p>
        </header>

        <section id="start">
          <div className="manual-section-heading">
            <Gauge aria-hidden="true" />
            <h2>{copy.startTitle}</h2>
          </div>
          <p>{copy.startBody}</p>
          <aside className="manual-callout manual-callout-info">
            <CircleAlert aria-hidden="true" />
            <div>
              <h3>{copy.before}</h3>
              <ul>{copy.beforeItems.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          </aside>
        </section>

        <section id="install">
          <div className="manual-section-heading">
            <Download aria-hidden="true" />
            <h2>{copy.installTitle}</h2>
          </div>
          <p>{copy.installBody}</p>
          <ol className="manual-document-list manual-install-list">
            {copy.installSteps.map(([title, body], index) => (
              <li key={title}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><h3>{title}</h3><p>{body}</p></div>
              </li>
            ))}
          </ol>
        </section>

        <section id="assistant">
          <div className="manual-section-heading">
            <MessageSquareText aria-hidden="true" />
            <h2>{copy.assistantTitle}</h2>
          </div>
          <p>{copy.assistantBody}</p>
          <figure className="manual-product-shot">
            <img src={`${screenshotRoot}/tuning-chat.png`} alt={copy.assistantTitle} />
          </figure>
          <div className="manual-example">
            <strong>{copy.assistantExampleTitle}</strong>
            <blockquote>{copy.assistantExample}</blockquote>
            <p>{copy.assistantResult}</p>
          </div>
        </section>

        <section id="wizard">
          <div className="manual-section-heading">
            <SlidersHorizontal aria-hidden="true" />
            <h2>{copy.wizardTitle}</h2>
          </div>
          <p>{copy.wizardBody}</p>
          <figure className="manual-product-shot">
            <img src={`${screenshotRoot}/flight-setup.png`} alt={copy.wizardTitle} />
          </figure>
          <ol className="manual-wizard-list">
            {copy.wizardSteps.map(([number, title, body]) => (
              <li key={number}>
                <span>{number}</span>
                <div><h3>{title}</h3><p>{body}</p></div>
              </li>
            ))}
          </ol>
        </section>

        <section id="track">
          <div className="manual-section-heading">
            <Route aria-hidden="true" />
            <h2>{copy.trackTitle}</h2>
          </div>
          <p>{copy.trackBody}</p>
          <aside className="manual-callout manual-callout-success">
            <CheckCircle2 aria-hidden="true" />
            <p>{copy.trackCallout}</p>
          </aside>
        </section>

        <section id="results">
          <div className="manual-section-heading">
            <History aria-hidden="true" />
            <h2>{copy.resultsTitle}</h2>
          </div>
          <p>{copy.resultsBody}</p>
          <figure className="manual-product-shot">
            <img src={`${screenshotRoot}/dashboard.png`} alt={copy.resultsTitle} />
          </figure>
          <ul className="manual-document-list manual-evidence-list">
            {copy.evidence.map(([title, body]) => (
              <li key={title}>
                <CheckCircle2 aria-hidden="true" />
                <div><h3>{title}</h3><p>{body}</p></div>
              </li>
            ))}
          </ul>
        </section>

        <section id="safety">
          <div className="manual-section-heading">
            <ShieldCheck aria-hidden="true" />
            <h2>{copy.safetyTitle}</h2>
          </div>
          <p>{copy.safetyBody}</p>
          <aside className="manual-callout manual-callout-warning">
            <ShieldCheck aria-hidden="true" />
            <p>{copy.safetyNote}</p>
          </aside>
        </section>
      </article>
    </div>
  );
}
