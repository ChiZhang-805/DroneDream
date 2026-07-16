import { useEffect, useMemo, useRef, useState } from "react";

import appIcon from "../../../desktop/src-tauri/icons/128x128.png";
import { DroneLaunchScene } from "../components/DroneLaunchScene";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useI18n } from "../i18n/I18nProvider";
import {
  compareReleaseVersions,
  fallbackRelease,
  formatBinarySize,
  isWebsiteRelease,
  type WebsiteRelease,
} from "./release";

const GITHUB_URL = "https://github.com/ChiZhang-805/DroneDream";

const content = {
  en: {
    skip: "Skip to content",
    metaTitle: "DroneDream — Autonomous PX4 tuning",
    metaDescription: "Configure, optimize, simulate, and compare PX4 control parameters in one local Windows workflow.",
    navLabel: "Primary navigation",
    nav: [
      ["Product", "product"],
      ["Workflow", "workflow"],
      ["Manual", "manual"],
      ["Download", "download"],
    ],
    language: "中文",
    languageLabel: "Switch to Simplified Chinese",
    menu: "Open navigation",
    closeMenu: "Close navigation",
    downloadShort: "Download",
    eyebrow: "LOCAL-FIRST PX4 / GAZEBO TUNING",
    heroLead: "Tune with evidence.",
    heroAccent: "Fly with confidence.",
    downloadWindows: "Download for Windows",
    explore: "See how it works",
    releasePrefix: "Preview",
    system: "Windows 10 / 11 · x64",
    clickDrone: "Click the drone to begin a starflight",
    scroll: "Scroll to explore",
    productEyebrow: "ONE CONTINUOUS WORKFLOW",
    productTitle: "From a tuning question to a defensible result.",
    productBody:
      "DroneDream keeps parameter choices, simulation evidence, optimizer decisions, and reports in one reproducible experiment.",
    demoPhases: [
      {
        label: "01 · Define",
        title: "Describe the flight you actually need",
        body: "Choose the airframe, PX4 parameters, Gazebo world, trajectory, constraints, and acceptance criteria.",
        status: "Experiment configured",
      },
      {
        label: "02 · Search",
        title: "Let optimizers propose the next trial",
        body: "Run Bayesian, CMA-ES, trust-region, and portfolio strategies against the evidence returned by simulation.",
        status: "Candidate 24 / 60",
      },
      {
        label: "03 · Verify",
        title: "Compare more than a single score",
        body: "Review feasibility, tracking error, overshoot, settling time, robustness, and the Pareto trade-off before exporting parameters.",
        status: "Acceptance passed",
      },
    ],
    metricLabels: ["Tracking error", "Overshoot", "Settling time"],
    parameterTitle: "Live candidate",
    parameters: ["MC_ROLL_P", "MC_PITCHRATE_I", "MPC_XY_VEL_P_ACC"],
    workflowEyebrow: "BUILT AROUND THE EXPERIMENT",
    workflowTitle: "The repetitive work becomes the software's job.",
    workflow: [
      ["Define", "Set the vehicle, world, route, limits, and success criteria."],
      ["Select", "Tune only the PX4 parameters you choose, within guarded ranges."],
      ["Simulate", "Run isolated PX4 and Gazebo trials with structured artifacts."],
      ["Decide", "Rank feasible candidates and preserve the evidence behind them."],
    ],
    capabilitiesEyebrow: "DESIGNED FOR SERIOUS ITERATION",
    capabilitiesTitle: "A local flight laboratory, not another parameter form.",
    capabilities: [
      ["Selective tuning", "Choose individual control parameters or a curated group instead of searching everything blindly.", "sliders"],
      ["Seven strategy portfolio", "Compare complementary experimental optimizers and route each experiment to an appropriate search strategy.", "orbit"],
      ["Isolated runtime", "Keep PX4, Gazebo, workers, and artifacts inside a dedicated WSL2 environment without reusing personal distributions.", "shield"],
      ["Evidence-first reports", "Trace every candidate back to its scenario, seed, logs, metrics, constraints, and reproducibility manifest.", "report"],
    ],
    manualEyebrow: "GET STARTED",
    manualTitle: "Three steps from download to your first experiment.",
    manualSteps: [
      ["Install the desktop app", "Run the Windows installer and keep the recommended application folder."],
      ["Prepare DroneDreamRuntime", "The launcher downloads and verifies the isolated PX4 / Gazebo runtime. Existing Ubuntu distributions stay untouched."],
      ["Create an experiment", "Follow the five-step wizard, validate each stage, then start the tuning run."],
    ],
    openManual: "Read the full manual",
    manualDialogTitle: "DroneDream quick-start manual",
    manualDialogIntro:
      "This guide covers the complete customer path from a verified EXE to a first local tuning experiment.",
    manualClose: "Close manual",
    manualChapters: [
      ["1 · Check the computer", ["Use Windows 10 or Windows 11 on an x64 computer.", "Enable WSL2 and reserve at least 52 GiB for the complete Runtime.", "Use a fixed, writable NTFS drive when placing Runtime outside the system disk."]],
      ["2 · Install the desktop application", ["Download the versioned EXE from this page and verify its SHA-256 if required.", "Run the installer, choose one interface language, and keep the recommended application folder.", "The current preview is unsigned, so SmartScreen may require More info → Run anyway."]],
      ["3 · Prepare DroneDreamRuntime", ["Open DroneDream and start Runtime installation from the launch screen.", "Keep the app open while it downloads, verifies, imports, starts, and checks PX4 / Gazebo.", "The dedicated distribution does not replace or modify an existing personal Ubuntu distribution."]],
      ["4 · Create the first experiment", ["Choose a mode, vehicle, PX4 version, Gazebo model, and world.", "Complete the five wizard stages in order; future stages stay locked until the current stage validates.", "Select parameters and ranges, define the scenario and route, set constraints and budget, then review and create."]],
      ["5 · Read and preserve the result", ["Compare feasible candidates using individual metrics and Pareto trade-offs, not only a combined score.", "Keep logs, artifacts, seeds, parameter snapshots, and the reproducibility manifest with the report.", "Do not apply experimental parameters to real hardware without independent safety review and controlled flight testing."]],
    ],
    integrityTitle: "Download integrity",
    integrityText: "The SHA-256 shown on this page must exactly match the value calculated from the downloaded EXE.",
    github: "View source on GitHub",
    downloadEyebrow: "WINDOWS DEVELOPMENT PREVIEW",
    downloadTitle: "Bring the tuning workspace to your own machine.",
    downloadBody:
      "The desktop installer is small. DroneDreamRuntime is downloaded separately only when required and can be placed on a non-system NTFS drive.",
    downloadAgain: "Download DroneDream",
    version: "Version",
    size: "Installer size",
    platform: "Platform",
    platformValue: "Windows x64",
    released: "Released",
    checksum: "SHA-256",
    copyChecksum: "Copy checksum",
    copied: "Copied",
    checksumFile: "Checksum file",
    previewNote:
      "Development preview · currently unsigned. Windows SmartScreen may ask you to confirm before running it.",
    requirementsTitle: "Before installing",
    requirements:
      "Windows 10/11 x64, WSL2 support, at least 52 GiB free for the complete local runtime, and a stable connection for the first download.",
    footerLine: "Local-first autonomous control-parameter tuning for PX4 and Gazebo.",
    privacy: "No account is required for local preview workflows.",
  },
  "zh-CN": {
    skip: "跳到主要内容",
    metaTitle: "DroneDream — 无人机控制参数自动调优",
    metaDescription: "在 Windows 本地完成 PX4 控制参数选择、自动优化、可复现仿真与结果对比。",
    navLabel: "主导航",
    nav: [
      ["产品", "product"],
      ["工作流", "workflow"],
      ["说明书", "manual"],
      ["下载", "download"],
    ],
    language: "English",
    languageLabel: "切换到英文",
    menu: "打开导航",
    closeMenu: "关闭导航",
    downloadShort: "下载",
    eyebrow: "本地优先的 PX4 / GAZEBO 调优平台",
    heroLead: "让调优有章法",
    heroAccent: "让飞行更加从容",
    downloadWindows: "下载 Windows 版",
    explore: "了解工作方式",
    releasePrefix: "开发预览版",
    system: "Windows 10 / 11 · x64",
    clickDrone: "点击无人机，开启一次星际巡航",
    scroll: "向下探索",
    productEyebrow: "一条完整的调优链路",
    productTitle: "从一个控制问题，到一份经得起检查的结果。",
    productBody:
      "DroneDream 将参数选择、仿真证据、算法决策和最终报告保存在同一个可复现实验中。",
    demoPhases: [
      {
        label: "01 · 定义",
        title: "描述你真正需要的飞行任务",
        body: "选择机架、PX4 参数、Gazebo 世界、飞行轨迹、约束条件和验收标准。",
        status: "实验配置完成",
      },
      {
        label: "02 · 搜索",
        title: "让优化器决定下一组候选参数",
        body: "根据仿真反馈，组合使用贝叶斯、CMA-ES、信赖域和策略组合等实验算法。",
        status: "候选方案 24 / 60",
      },
      {
        label: "03 · 验证",
        title: "比较的不只是一个总分",
        body: "同时检查可行性、跟踪误差、超调量、稳定时间、鲁棒性和 Pareto 权衡，再导出参数。",
        status: "通过验收条件",
      },
    ],
    metricLabels: ["跟踪误差", "超调量", "稳定时间"],
    parameterTitle: "当前候选参数",
    parameters: ["MC_ROLL_P", "MC_PITCHRATE_I", "MPC_XY_VEL_P_ACC"],
    workflowEyebrow: "围绕真实实验设计",
    workflowTitle: "把重复而繁琐的工作交给软件。",
    workflow: [
      ["定义任务", "设置机型、世界、航迹、边界和成功标准。"],
      ["选择参数", "只调节你选中的 PX4 参数，并使用经过保护的搜索范围。"],
      ["自动仿真", "在隔离环境中运行 PX4 与 Gazebo，并生成结构化产物。"],
      ["比较决策", "筛选可行候选方案，同时保留每个结论背后的证据。"],
    ],
    capabilitiesEyebrow: "为认真迭代而设计",
    capabilitiesTitle: "它是一间本地飞行实验室，而不只是参数表单。",
    capabilities: [
      ["按需选择参数", "可以选择单个控制参数或经过整理的参数组，无需盲目搜索全部变量。", "sliders"],
      ["七种实验算法", "比较互补的优化方法，并根据实验特征选择更合适的搜索策略。", "orbit"],
      ["隔离运行环境", "PX4、Gazebo、工作进程和产物都位于专用 WSL2 环境，不复用个人 Ubuntu。", "shield"],
      ["证据优先报告", "每个候选方案都能追溯到场景、随机种子、日志、指标、约束和复现清单。", "report"],
    ],
    manualEyebrow: "开始使用",
    manualTitle: "从下载到第一次调优，只需要三个阶段。",
    manualSteps: [
      ["安装桌面程序", "运行 Windows 安装包，并保留推荐的应用程序目录。"],
      ["准备专用运行环境", "启动器会下载并验证隔离的 PX4 / Gazebo 环境，不会修改已有 Ubuntu。"],
      ["创建调优实验", "依次完成五步向导；当前步骤验证通过后，才能进入下一步并开始调优。"],
    ],
    openManual: "阅读完整说明书",
    manualDialogTitle: "DroneDream 快速使用说明书",
    manualDialogIntro: "这份说明覆盖从校验安装包到创建第一次本地调优实验的完整用户流程。",
    manualClose: "关闭说明书",
    manualChapters: [
      ["1 · 检查电脑条件", ["使用 x64 架构的 Windows 10 或 Windows 11 电脑。", "启用 WSL2，并为完整运行环境预留至少 52 GiB 空间。", "如果运行环境不放在系统盘，请选择固定、可写的 NTFS 磁盘。"]],
      ["2 · 安装桌面程序", ["从本页下载带版本号的 EXE；如有需要，先核对 SHA-256。", "运行安装器，选择一种界面语言，并保留推荐的应用程序目录。", "当前预览版尚未签名；SmartScreen 出现时需要选择“更多信息”并确认运行。"]],
      ["3 · 准备专用运行环境", ["打开 DroneDream，在启动界面开始安装 DroneDreamRuntime。", "下载、校验、导入、启动以及 PX4 / Gazebo 检查期间请保持程序开启。", "这个专用发行版不会替换或修改电脑中已有的个人 Ubuntu。"]],
      ["4 · 创建第一次实验", ["选择使用模式、机型、PX4 版本、Gazebo 模型与世界。", "依次完成五个向导步骤；当前步骤通过验证前，后续步骤始终锁定。", "选择参数及范围，设置场景、航迹、约束和预算，最后检查并创建实验。"]],
      ["5 · 阅读并保存结果", ["使用单项指标和 Pareto 权衡比较可行候选方案，不要只看一个综合分数。", "将日志、产物、随机种子、参数快照和复现清单与报告一起保留。", "未经独立安全审查和受控试飞，不要把实验参数直接应用到真实飞行器。"]],
    ],
    integrityTitle: "下载完整性",
    integrityText: "本页显示的 SHA-256 必须与下载后从 EXE 计算得到的值完全一致。",
    github: "在 GitHub 查看源码",
    downloadEyebrow: "WINDOWS 开发预览版",
    downloadTitle: "把自动调优工作空间带到自己的电脑。",
    downloadBody:
      "桌面安装包本身很小；只有在需要时才会单独下载 DroneDreamRuntime，并且可以安装到非系统 NTFS 磁盘。",
    downloadAgain: "下载 DroneDream",
    version: "版本",
    size: "安装包大小",
    platform: "平台",
    platformValue: "Windows x64",
    released: "发布日期",
    checksum: "SHA-256",
    copyChecksum: "复制校验值",
    copied: "已复制",
    checksumFile: "校验文件",
    previewNote: "开发预览版 · 当前尚未签名，Windows SmartScreen 可能要求你确认后再运行。",
    requirementsTitle: "安装前需要准备",
    requirements:
      "Windows 10/11 x64、WSL2 支持、完整本地运行环境至少 52 GiB 可用空间，以及首次下载时稳定的网络连接。",
    footerLine: "面向 PX4 与 Gazebo 的本地优先无人机控制参数自动调优平台。",
    privacy: "本地预览工作流不要求注册账户。",
  },
} as const;

type IconName = "sliders" | "orbit" | "shield" | "report";

function FeatureIcon({ name }: { name: IconName }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    strokeWidth: 1.8,
  };
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true">
      {name === "sliders" ? (
        <>
          <path d="M6 8h20M6 16h20M6 24h20" {...common} />
          <circle cx="12" cy="8" r="2.4" {...common} />
          <circle cx="21" cy="16" r="2.4" {...common} />
          <circle cx="15" cy="24" r="2.4" {...common} />
        </>
      ) : null}
      {name === "orbit" ? (
        <>
          <circle cx="16" cy="16" r="3.3" {...common} />
          <ellipse cx="16" cy="16" rx="12" ry="6" transform="rotate(28 16 16)" {...common} />
          <ellipse cx="16" cy="16" rx="12" ry="6" transform="rotate(-28 16 16)" {...common} />
        </>
      ) : null}
      {name === "shield" ? (
        <path d="M16 4 26 8v7c0 6.4-4 10.7-10 13-6-2.3-10-6.6-10-13V8l10-4Zm-4.5 12 3 3 6-7" {...common} />
      ) : null}
      {name === "report" ? (
        <>
          <path d="M8 4h12l5 5v19H8V4Z M20 4v6h5" {...common} />
          <path d="M12 16h9M12 21h9M12 11h3" {...common} />
        </>
      ) : null}
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v11m0 0 4-4m-4 4-4-4M5 20h14" />
    </svg>
  );
}

function StarflightIcon() {
  return (
    <svg className="site-starflight-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 1.75c.74 5.84 4.41 9.51 10.25 10.25C16.41 12.74 12.74 16.41 12 22.25 11.26 16.41 7.59 12.74 1.75 12 7.59 11.26 11.26 7.59 12 1.75Z" />
    </svg>
  );
}

export function SiteApp() {
  const { locale, setLocale } = useI18n();
  const copy = content[locale];
  const [release, setRelease] = useState<WebsiteRelease>(fallbackRelease);
  const [activePhase, setActivePhase] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [checksumCopied, setChecksumCopied] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const reducedMotion = usePrefersReducedMotion();
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const droneFlightRef = useRef<(() => void) | null>(null);
  const manualTriggerRef = useRef<HTMLButtonElement>(null);
  const manualCloseRef = useRef<HTMLButtonElement>(null);
  const manualDialogRef = useRef<HTMLElement>(null);
  const checksumResetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    document.title = copy.metaTitle;
    document.querySelector<HTMLMetaElement>('meta[name="description"]')
      ?.setAttribute("content", copy.metaDescription);
    document.querySelector<HTMLMetaElement>('meta[property="og:title"]')
      ?.setAttribute("content", copy.metaTitle);
    document.querySelector<HTMLMetaElement>('meta[property="og:description"]')
      ?.setAttribute("content", copy.metaDescription);
  }, [copy.metaDescription, copy.metaTitle]);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/downloads/latest.json", { signal: controller.signal, cache: "no-cache" })
      .then((response) => {
        if (!response.ok) throw new Error(`release metadata: ${response.status}`);
        return response.json() as Promise<unknown>;
      })
      .then((candidate) => {
        if (
          isWebsiteRelease(candidate) &&
          compareReleaseVersions(candidate.version, fallbackRelease.version) >= 0
        ) {
          setRelease(candidate);
        }
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const targetId = decodeURIComponent(window.location.hash.replace(/^#/u, ""));
    if (!targetId) return;
    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById(targetId);
      if (!target) return;
      const top = target.getBoundingClientRect().top + window.scrollY - 66;
      window.scrollTo({ top: Math.max(0, top) });
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
    if (!("IntersectionObserver" in window)) {
      nodes.forEach((node) => node.classList.add("is-visible"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      }),
      { rootMargin: "0px 0px -12%", threshold: 0.12 },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>(
      ".site-hero, .site-product-demo",
    ));
    if (!("IntersectionObserver" in window)) {
      nodes.forEach((node) => node.classList.add("is-motion-visible"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        entry.target.classList.toggle("is-motion-visible", entry.isIntersecting);
      }),
      { rootMargin: "160px 0px", threshold: 0.01 },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!manualOpen) return;
    const previousOverflow = document.body.style.overflow;
    const inertTargets = Array.from(document.querySelectorAll<HTMLElement>(
      ".site-header, #main-content, .site-footer",
    ));
    document.body.style.overflow = "hidden";
    const previousInertStates = inertTargets.map((target) => target.inert);
    inertTargets.forEach((target) => { target.inert = true; });
    manualCloseRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setManualOpen(false);
        window.requestAnimationFrame(() => manualTriggerRef.current?.focus());
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(manualDialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? []);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      inertTargets.forEach((target, index) => {
        target.inert = previousInertStates[index] ?? false;
      });
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [manualOpen]);

  useEffect(() => () => {
    if (checksumResetTimerRef.current !== null) {
      window.clearTimeout(checksumResetTimerRef.current);
    }
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuOpen(false);
      menuButtonRef.current?.focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  const currentPhase = copy.demoPhases[activePhase];
  const displaySize = useMemo(() => formatBinarySize(release.sizeBytes), [release.sizeBytes]);

  const copyChecksum = async () => {
    try {
      await navigator.clipboard.writeText(release.sha256);
      setChecksumCopied(true);
      if (checksumResetTimerRef.current !== null) {
        window.clearTimeout(checksumResetTimerRef.current);
      }
      checksumResetTimerRef.current = window.setTimeout(() => {
        checksumResetTimerRef.current = null;
        setChecksumCopied(false);
      }, 1_800);
    } catch {
      setChecksumCopied(false);
    }
  };

  const selectPhaseFromKeyboard = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    const lastIndex = copy.demoPhases.length - 1;
    const nextIndex = event.key === "ArrowRight" || event.key === "ArrowDown"
      ? (currentIndex + 1) % copy.demoPhases.length
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? (currentIndex + lastIndex) % copy.demoPhases.length
        : event.key === "Home"
          ? 0
          : event.key === "End"
            ? lastIndex
            : null;
    if (nextIndex === null) return;
    event.preventDefault();
    setActivePhase(nextIndex);
    event.currentTarget.parentElement
      ?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex]
      ?.focus();
  };

  const closeMenu = () => setMenuOpen(false);
  const closeManual = () => {
    setManualOpen(false);
    window.requestAnimationFrame(() => manualTriggerRef.current?.focus());
  };

  return (
    <div className="dd-site">
      <a className="site-skip-link" href="#main-content">{copy.skip}</a>
      <header className={`site-header${scrolled ? " is-scrolled" : ""}`}>
        <a className="site-brand" href="#home" onClick={closeMenu} aria-label="DroneDream">
          <img src={appIcon} alt="" />
          <span>DroneDream</span>
        </a>
        <nav
          id="site-navigation"
          className={`site-nav${menuOpen ? " is-open" : ""}`}
          aria-label={copy.navLabel}
        >
          {copy.nav.map(([label, target]) => (
            <a key={target} href={`#${target}`} onClick={closeMenu}>{label}</a>
          ))}
        </nav>
        <div className="site-header-actions">
          <button
            type="button"
            className="site-language"
            aria-label={copy.languageLabel}
            onClick={() => setLocale(locale === "en" ? "zh-CN" : "en")}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.7 2.4 4 5.4 4 9s-1.3 6.6-4 9c-2.7-2.4-4-5.4-4-9s1.3-6.6 4-9Z" /></svg>
            {copy.language}
          </button>
          <a className="site-header-download" href={release.downloadUrl} download={release.fileName}>
            {copy.downloadShort}
          </a>
          <button
            ref={menuButtonRef}
            type="button"
            className="site-menu-button"
            aria-label={menuOpen ? copy.closeMenu : copy.menu}
            aria-expanded={menuOpen}
            aria-controls="site-navigation"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span />
            <span />
          </button>
        </div>
      </header>

      <main id="main-content">
        <section className="site-hero" id="home" aria-labelledby="hero-title">
          <div className="site-hero-scene" aria-hidden="true">
            <DroneLaunchScene active starflightControllerRef={droneFlightRef} visualOffsetX={1.35} />
          </div>
          <div className="site-hero-shade" aria-hidden="true" />
          <div className="site-shell site-hero-layout">
            <div className="site-hero-copy">
              <p className="site-eyebrow">{copy.eyebrow}</p>
              <h1 id="hero-title">
                <span className="site-hero-line">{copy.heroLead}</span>
                <span className="site-hero-line site-hero-line-accent">{copy.heroAccent}</span>
              </h1>
              <div className="site-hero-actions">
                <a className="site-button site-button-primary" href={release.downloadUrl} download={release.fileName}>
                  <DownloadIcon />
                  {copy.downloadWindows}
                </a>
                <a className="site-button site-button-ghost" href="#product">{copy.explore}</a>
              </div>
              <div className="site-release-line" aria-label={`${copy.version} ${release.version}`}>
                <span className="site-live-dot" />
                <strong>{copy.releasePrefix} {release.version}</strong>
                <span>{displaySize}</span>
                <span>{copy.system}</span>
              </div>
            </div>
            {!reducedMotion ? (
              <button
                type="button"
                className="site-drone-hint"
                onClick={() => droneFlightRef.current?.()}
              >
                <StarflightIcon />
                <span>{copy.clickDrone}</span>
              </button>
            ) : null}
          </div>
          <a className="site-scroll-cue" href="#product">
            <span>{copy.scroll}</span>
            <i aria-hidden="true" />
          </a>
        </section>

        <section className="site-section site-product" id="product">
          <div className="site-shell">
            <div className="site-section-heading" data-reveal>
              <p className="site-eyebrow">{copy.productEyebrow}</p>
              <h2>{copy.productTitle}</h2>
              <p>{copy.productBody}</p>
            </div>
            <div className="site-product-demo" data-reveal>
              <div className="site-demo-copy">
                <div className="site-phase-tabs" role="tablist" aria-label={copy.productEyebrow}>
                  {copy.demoPhases.map((phase, index) => (
                    <button
                      key={phase.label}
                      type="button"
                      role="tab"
                      id={`site-phase-tab-${index}`}
                      aria-controls={`site-phase-panel-${index}`}
                      aria-selected={activePhase === index}
                      tabIndex={activePhase === index ? 0 : -1}
                      className={activePhase === index ? "is-active" : ""}
                      onClick={() => setActivePhase(index)}
                      onKeyDown={(event) => selectPhaseFromKeyboard(event, index)}
                    >
                      <span>{phase.label}</span>
                      <i aria-hidden="true" />
                    </button>
                  ))}
                </div>
                {copy.demoPhases.map((phase, index) => (
                  <div
                    key={phase.label}
                    id={`site-phase-panel-${index}`}
                    className="site-phase-copy"
                    role="tabpanel"
                    aria-labelledby={`site-phase-tab-${index}`}
                    tabIndex={0}
                    hidden={activePhase !== index}
                  >
                    <span>{phase.label}</span>
                    <h3>{phase.title}</h3>
                    <p>{phase.body}</p>
                  </div>
                ))}
              </div>
              <div className={`site-demo-visual phase-${activePhase}`}>
                <div className="site-demo-topbar">
                  <span><i /> DroneDream / EXP-024</span>
                  <strong>{currentPhase.status}</strong>
                </div>
                <div className="site-demo-grid">
                  <div className="site-demo-chart">
                    <div className="site-chart-labels">
                      {copy.metricLabels.map((label, index) => <span key={label} style={{ "--index": index } as React.CSSProperties}>{label}</span>)}
                    </div>
                    <svg viewBox="0 0 640 280" preserveAspectRatio="none" aria-hidden="true">
                      <defs>
                        <linearGradient id="site-chart-gradient" x1="0" y1="0" x2="1" y2="0">
                          <stop offset="0" stopColor="#68e8ff" />
                          <stop offset="0.55" stopColor="#9b7cff" />
                          <stop offset="1" stopColor="#f166d8" />
                        </linearGradient>
                        <linearGradient id="site-chart-area" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0" stopColor="#9877ff" stopOpacity=".35" />
                          <stop offset="1" stopColor="#9877ff" stopOpacity="0" />
                        </linearGradient>
                      </defs>
                      <path className="site-chart-grid" d="M0 55H640M0 110H640M0 165H640M0 220H640" />
                      <path className="site-chart-area" d="M0 224C72 215 82 93 150 108s76 90 137 60 72-104 137-73 78 130 126 83 56-73 90-118V280H0Z" />
                      <path className="site-chart-line" d="M0 224C72 215 82 93 150 108s76 90 137 60 72-104 137-73 78 130 126 83 56-73 90-118" />
                      <circle className="site-chart-point point-a" cx="150" cy="108" r="5" />
                      <circle className="site-chart-point point-b" cx="424" cy="95" r="5" />
                      <circle className="site-chart-point point-c" cx="640" cy="60" r="6" />
                    </svg>
                  </div>
                  <aside className="site-parameter-stack">
                    <p>{copy.parameterTitle}</p>
                    {copy.parameters.map((parameter, index) => (
                      <div key={parameter}>
                        <span>{parameter}</span>
                        <strong>{[6.84, 0.19, 1.72][index].toFixed(2)}</strong>
                        <i><b style={{ width: `${[72, 43, 61][index]}%` }} /></i>
                      </div>
                    ))}
                  </aside>
                </div>
                <div className="site-pulse-orbit" aria-hidden="true"><i /><i /><i /></div>
              </div>
            </div>
          </div>
        </section>

        <section className="site-section site-workflow" id="workflow">
          <div className="site-shell">
            <div className="site-section-heading site-heading-light" data-reveal>
              <p className="site-eyebrow">{copy.workflowEyebrow}</p>
              <h2>{copy.workflowTitle}</h2>
            </div>
            <ol className="site-workflow-list">
              {copy.workflow.map(([title, description], index) => (
                <li key={title} data-reveal>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <div><h3>{title}</h3><p>{description}</p></div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="site-section site-capabilities">
          <div className="site-shell">
            <div className="site-section-heading" data-reveal>
              <p className="site-eyebrow">{copy.capabilitiesEyebrow}</p>
              <h2>{copy.capabilitiesTitle}</h2>
            </div>
            <div className="site-capability-grid">
              {copy.capabilities.map(([title, description, icon], index) => (
                <article key={title} className={`site-capability-card card-${index + 1}`} data-reveal>
                  <span className="site-feature-icon"><FeatureIcon name={icon as IconName} /></span>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section className="site-section site-manual" id="manual">
          <div className="site-shell site-manual-layout">
            <div className="site-manual-copy" data-reveal>
              <p className="site-eyebrow">{copy.manualEyebrow}</p>
              <h2>{copy.manualTitle}</h2>
              <div className="site-manual-links">
                <button ref={manualTriggerRef} type="button" onClick={() => setManualOpen(true)}>{copy.openManual}<span aria-hidden="true">↗</span></button>
                <a href={GITHUB_URL} target="_blank" rel="noreferrer">{copy.github}<span aria-hidden="true">↗</span></a>
              </div>
            </div>
            <ol className="site-manual-steps">
              {copy.manualSteps.map(([title, description], index) => (
                <li key={title} data-reveal>
                  <span>{index + 1}</span>
                  <div><h3>{title}</h3><p>{description}</p></div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="site-section site-download" id="download">
          <div className="site-shell">
            <div className="site-download-card" data-reveal>
              <div className="site-download-glow" aria-hidden="true" />
              <div className="site-download-copy">
                <p className="site-eyebrow">{copy.downloadEyebrow}</p>
                <h2>{copy.downloadTitle}</h2>
                <p>{copy.downloadBody}</p>
                <a className="site-button site-button-primary" href={release.downloadUrl} download={release.fileName}>
                  <DownloadIcon />
                  {copy.downloadAgain}
                </a>
                <small>{copy.previewNote}</small>
              </div>
              <div className="site-release-card">
                <dl>
                  <div><dt>{copy.version}</dt><dd>{release.version}</dd></div>
                  <div><dt>{copy.size}</dt><dd>{displaySize}</dd></div>
                  <div><dt>{copy.platform}</dt><dd>{copy.platformValue}</dd></div>
                  <div><dt>{copy.released}</dt><dd>{release.publishedAt}</dd></div>
                </dl>
                <div className="site-checksum">
                  <span>{copy.checksum}</span>
                  <code title={release.sha256}>{release.sha256}</code>
                  <div>
                    <button type="button" onClick={copyChecksum}>{checksumCopied ? copy.copied : copy.copyChecksum}</button>
                    <a href={release.checksumUrl} download>{copy.checksumFile}</a>
                  </div>
                </div>
                <details>
                  <summary>{copy.requirementsTitle}</summary>
                  <p>{copy.requirements}</p>
                </details>
              </div>
            </div>
          </div>
        </section>
      </main>

      {manualOpen ? (
        <div
          className="site-manual-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeManual();
          }}
        >
          <section ref={manualDialogRef} className="site-manual-dialog" role="dialog" aria-modal="true" aria-labelledby="site-manual-title">
            <header>
              <div>
                <p className="site-eyebrow">{copy.manualEyebrow}</p>
                <h2 id="site-manual-title">{copy.manualDialogTitle}</h2>
                <p>{copy.manualDialogIntro}</p>
              </div>
              <button ref={manualCloseRef} type="button" aria-label={copy.manualClose} onClick={closeManual}>×</button>
            </header>
            <div className="site-manual-dialog-body">
              {copy.manualChapters.map(([title, items]) => (
                <article key={title}>
                  <h3>{title}</h3>
                  <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
                </article>
              ))}
              <aside>
                <strong>{copy.integrityTitle}</strong>
                <p>{copy.integrityText}</p>
                <code>{release.sha256}</code>
              </aside>
            </div>
          </section>
        </div>
      ) : null}

      <footer className="site-footer">
        <div className="site-shell">
          <div className="site-footer-brand"><img src={appIcon} alt="" /><strong>DroneDream</strong></div>
          <p>{copy.footerLine}</p>
          <span>{copy.privacy}</span>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer">GitHub ↗</a>
        </div>
      </footer>
    </div>
  );
}
