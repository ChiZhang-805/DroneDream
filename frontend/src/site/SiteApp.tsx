import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { BrandLockup } from "../components/BrandLockup";
import { DroneLaunchScene } from "../components/DroneLaunchScene";
import { AuthCaptcha } from "../features/auth/AuthCaptcha";
import { useAuthOrLocal } from "../features/auth/AuthContext";
import { getManagedModelUsage } from "../features/settings/cloudModelAccess";
import {
  getOrganizationAccess,
  type OrganizationAccess,
} from "../features/organization/organizationConsole";
import {
  captchaProtectionConfigured,
  turnstileSiteKey,
} from "../features/auth/supabaseClient";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";
import { useI18n } from "../i18n/I18nProvider";
import { CommunityPage } from "./CommunityPage";
import { ManualPage } from "./ManualPage";
import { OAuthConsentPage } from "./OAuthConsentPage";
import { OrganizationPage } from "./OrganizationPage";
import { PricingPage } from "./PricingPage";
import { ProductPage } from "./ProductPage";
import {
  fallbackEditionAvailability,
  isEditionAvailabilityDocument,
  type EditionAvailabilityDocument,
} from "./editionAvailability";
import {
  compareReleaseVersions,
  fallbackRelease,
  formatBinarySize,
  isWebsiteRelease,
  type WebsiteRelease,
} from "./release";

const GITHUB_URL = "https://github.com/ChiZhang-805/DroneDream";
const CODE_SIGNING_POLICY_URL = `${GITHUB_URL}/blob/main/CODE_SIGNING_POLICY.md`;
const PRIVACY_POLICY_URL = `${GITHUB_URL}/blob/main/PRIVACY.md`;
const COMMUNITY_GUIDELINES_URL = `${GITHUB_URL}/blob/main/COMMUNITY_GUIDELINES.md`;

const WEBSITE_DRONE_THEME = Object.freeze({
  primary: 0x68e8ff,
  secondary: 0x9b72ff,
  tertiary: 0xf166d8,
  darkSurface: 0x070913,
  fog: 0x070913,
  gridMinor: 0x34244f,
});

const content = {
  en: {
    skip: "Skip to content",
    metaTitle: "DroneDream",
    metaDescription: "Configure, optimize, simulate, and compare PX4 control parameters in one local Windows workflow.",
    navLabel: "Primary navigation",
    nav: [
      ["Product", "/product/"],
      ["Pricing", "/pricing/"],
      ["Manual", "/manual/"],
      ["Community", "/community/"],
    ],
    language: "中文",
    languageLabel: "Switch to Simplified Chinese",
    menu: "Open navigation",
    closeMenu: "Close navigation",
    downloadShort: "Download",
    console: "Console",
    organization: "Manage organization",
    accountPlan: "Plan",
    signIn: "Sign in",
    register: "Register",
    account: "Account",
    authTitle: "Sign in",
    registerTitle: "Create account",
    email: "Email address",
    password: "Password",
    passwordPlaceholder: "At least 8 characters",
    confirmPassword: "Confirm password",
    confirmPasswordPlaceholder: "Enter the password again",
    code: "Verification code",
    codePlaceholder: "Six-digit code",
    sendCode: "Send code",
    resendCode: "Resend code",
    signInAction: "Sign in",
    createAccount: "Create account",
    passwordTooShort: "Password must contain at least 8 characters.",
    passwordMismatch: "The two passwords do not match.",
    codeRequired: "Send and enter the verification code before creating the account.",
    completeCaptcha: "Complete the security check before continuing.",
    registerNow: "New to DroneDream? Register now",
    backToSignIn: "Already registered? Sign in",
    openConsole: "Open console",
    signOut: "Sign out",
    closeAuth: "Close account dialog",
    eyebrow: "LOCAL-FIRST PX4 / GAZEBO TUNING",
    heroLead: "Tune with evidence.",
    heroAccent: "Fly with confidence.",
    downloadWindows: "Download for Windows",
    explore: "See how it works",
    releasePrefix: "Version",
    system: "Windows 10 / 11 · x64",
    clickDrone: "Click the drone to begin a starflight",
    scroll: "Scroll to explore",
    productEyebrow: "ONE CONTINUOUS WORKFLOW",
    productTitle: "From question to defensible result.",
    productBody:
      "Keep parameters, simulations, decisions, and reports in one reproducible study.",
    demoPhases: [
      {
        label: "01 · Define",
        title: "Define the target flight",
        body: [
          "Pick vehicle, PX4 stack, Gazebo world, and route.",
          "Set safety limits, budget, and success metrics.",
          "Tie every run to one repeatable flight question.",
          "Record assumptions before spending a trial.",
          "Make targets measurable for later review.",
          "Start with clean rules and comparable outcomes.",
        ],
        status: "Experiment configured",
      },
      {
        label: "02 · Search",
        title: "Choose the next trial",
        body: [
          "Read history, failed trials, and new feedback.",
          "Keep bounds, coupling, and feasibility active.",
          "Let Bayesian, trust-region, evolution compete.",
          "Spend budget where the model still learns.",
          "Propose candidates with clear information value.",
          "Turn gain guesses into evidence-led search.",
        ],
        status: "Candidate 24 / 60",
      },
      {
        label: "03 · Verify",
        title: "Compare the evidence",
        body: [
          "Check feasibility, error, overshoot, and settle time.",
          "Compare repeats, robustness, and Pareto fronts.",
          "Reject winners that break hidden constraints.",
          "Keep logs, metrics, seeds, and snapshots linked.",
          "Preserve evidence for accepted control settings.",
          "Make every result auditable by the flight team.",
        ],
        status: "Acceptance passed",
      },
    ],
    metricLabels: ["Tracking error", "Overshoot", "Settling time"],
    parameterTitle: "Live candidate",
    parameters: ["MC_ROLL_P", "MC_PITCHRATE_I", "MPC_XY_VEL_P_ACC"],
    workflowEyebrow: "BUILT AROUND THE EXPERIMENT",
    workflowTitle: "Let software handle the repetition.",
    workflow: [
      ["Define", "Set vehicle, route, limits, and success."],
      ["Select", "Tune chosen PX4 parameters in safe ranges."],
      ["Simulate", "Run isolated PX4 / Gazebo trials."],
      ["Decide", "Rank feasible candidates and retain evidence."],
    ],
    workflowVisualLabel: "An automated closed loop from flight task to evidence-backed decision",
    capabilitiesEyebrow: "BUILT FOR ITERATION",
    capabilitiesTitle: "A local flight lab, not a parameter form.",
    capabilities: [
      ["Selective tuning", ["Choose one PX4 parameter or a curated control group.", "Set guarded search bounds and coupled dependencies.", "Explore the needed control surface; leave unrelated dimensions safely untouched."], "sliders"],
      ["Seven optimizers", ["Match each optimizer to the geometry of the experiment.", "Combine constraints, fidelity, trust regions, and evolution.", "Verify every gain under the same independent suite before ranking the final winner."], "orbit"],
      ["Isolated runtime", ["Run PX4, Gazebo, workers, and artifacts in dedicated WSL2.", "Keep each trial isolated from personal Linux files and processes.", "Diagnose and clean failed simulations before the next isolated trial begins safely."], "shield"],
      ["Traceable reports", ["Link each candidate to its scenario, seed, and parameter snapshot.", "Preserve logs, metrics, artifacts, and the runtime manifest.", "Reproduce every decision from evidence together with its complete experiment history."], "report"],
    ],
    capabilityOpen: "Open details for",
    capabilityBack: "Return to overview",
    capabilityPrevious: "Previous detail",
    capabilityNext: "Next detail",
    capabilityDetails: [
      [
        ["MPC_XY_P", "Turns horizontal position error into a velocity target; tune it with the velocity loop to avoid abrupt corrections."],
        ["MPC_XY_VEL_P_ACC", "Turns horizontal velocity error into acceleration demand and strongly shapes tracking response and overshoot."],
        ["MPC_Z_P", "Converts altitude error into climb-rate demand; coordinate it with vertical speed and acceleration limits."],
        ["MC_ROLLRATE_P", "Sets proportional roll-rate correction and directly affects response speed, damping, and oscillation risk."],
        ["MC_PITCHRATE_I", "Removes persistent pitch-rate bias while guarded bounds prevent integral windup during long maneuvers."],
      ],
      [
        ["Failure-aware constrained MOBO", "Models objectives, feasibility, and failed simulations together so unsafe regions consume less budget overall."],
        ["Multi-fidelity constrained MOBO", "Splits budget between quick screening and full validation under hard constraints before expensive trials."],
        ["TuRBO trust-region BO", "Searches coupled parameters in adaptive local regions that expand after verified gains and contract after setbacks."],
        ["SAAS constrained BO", "Finds influential axes in high-dimensional spaces before spending full trials on weak or irrelevant dimensions."],
        ["Surrogate-assisted CMA-ES", "Combines a response surrogate with covariance adaptation for continuous search across expensive trials."],
        ["BIPOP CMA-ES", "Alternates restart populations to escape local optima and deceptive regions while preserving global exploration."],
        ["Accuracy-first portfolio", "Allocates trials across six engines and ranks only independently verified gains under shared validation rules."],
      ],
      [
        ["Dedicated WSL2", "Runs the DroneDream distribution independently and never reuses or modifies a personal Ubuntu environment."],
        ["Trial isolation", "Assigns each PX4 / Gazebo run its own ports, process group, temporary files, and termination boundary safely."],
        ["Pinned inputs", "Records firmware, model, world, route, parameters, seeds, and environment effects before repeatable execution."],
        ["Recovery and cleanup", "Exports failure diagnostics, preserves artifacts, and safely removes abandoned processes before the next clean launch."],
      ],
      [
        ["Configuration snapshot", "Stores the vehicle, firmware, ranges, optimizer, constraints, and trial budget for every tested candidate."],
        ["Scenario identity", "Links each result to its world, route, disturbances, seeds, and acceptance criteria for direct comparison."],
        ["Logs and metrics", "Keeps telemetry, process logs, tracking metrics, failures, and artifacts together in one auditable result."],
        ["Pareto evidence", "Shows feasible trade-offs across error, overshoot, settling, robustness, and cost without hiding constraints."],
        ["Reproducibility manifest", "Hashes critical inputs and identifies the runtime so another machine can audit the same decision later."],
      ],
    ],
    manualEyebrow: "GET STARTED",
    manualTitle: "Tune in 3 steps.",
    manualSteps: [
      ["Install the app", "Run the Windows installer in the recommended folder."],
      ["Prepare the runtime", "Install isolated PX4 / Gazebo without changing Ubuntu."],
      ["Create an experiment", "Complete five validated steps, then start tuning."],
    ],
    openManual: "Full manual",
    manualDialogTitle: "DroneDream quick-start manual",
    manualDialogIntro:
      "This guide covers the complete customer path from a verified EXE to a first local tuning experiment.",
    manualClose: "Close manual",
    manualChapters: [
      ["1 · Check the computer", ["Use Windows 10 or Windows 11 on an x64 computer.", "Enable WSL2 and reserve at least 52 GiB for the complete Runtime.", "Use a fixed, writable NTFS drive when placing Runtime outside the system disk."]],
      ["2 · Install the desktop application", ["Download the versioned EXE from this page and verify its SHA-256 if required.", "Run the installer, choose one interface language, and keep the recommended application folder.", "The current release is not yet Authenticode-signed, so SmartScreen may require More info → Run anyway."]],
      ["3 · Prepare DroneDreamRuntime", ["Open DroneDream and start Runtime installation from the launch screen.", "Keep the app open while it downloads, verifies, imports, starts, and checks PX4 / Gazebo.", "The dedicated distribution does not replace or modify an existing personal Ubuntu distribution."]],
      ["4 · Create the first experiment", ["Choose a mode, vehicle, PX4 version, Gazebo model, and world.", "Complete the five wizard stages in order; future stages stay locked until the current stage validates.", "Select parameters and ranges, define the scenario and route, set constraints and budget, then review and create after confirming every runtime boundary with confidence while preserving the complete configuration."]],
      ["5 · Read and preserve the result", ["Compare feasible candidates using individual metrics and Pareto trade-offs, not only a combined score.", "Keep logs, artifacts, seeds, parameter snapshots, and the reproducibility manifest with the report.", "Do not use experimental parameters on real hardware without an independent safety review."]],
    ],
    integrityTitle: "Download integrity",
    integrityText: "The SHA-256 shown on this page must exactly match the value calculated from the downloaded EXE.",
    github: "View source on GitHub",
    downloadEyebrow: "WINDOWS RELEASE",
    downloadTitle: "Run DroneDream on your PC.",
    downloadBody:
      "Install the app first, then place its isolated Runtime on any eligible NTFS drive.",
    downloadAgain: "Download DroneDream",
    version: "Version",
    size: "Installer size",
    platform: "Platform",
    platformValue: "Windows x64",
    released: "Released",
    footerLine: "Local-first PX4/Gazebo control-parameter tuning. Version 1.0.0 is published while code signing is being prepared.",
    codeSigningPolicy: "Code signing policy",
    privacyPolicy: "Privacy policy",
    communityGuidelines: "Community guidelines",
  },
  "zh-CN": {
    skip: "跳到主要内容",
    metaTitle: "DroneDream",
    metaDescription: "在 Windows 本地完成 PX4 控制参数选择、自动优化、可复现仿真与结果对比。",
    navLabel: "主导航",
    nav: [
      ["产品", "/product/"],
      ["价格", "/pricing/"],
      ["说明书", "/manual/"],
      ["社区", "/community/"],
    ],
    language: "English",
    languageLabel: "切换到英文",
    menu: "打开导航",
    closeMenu: "关闭导航",
    downloadShort: "下载",
    console: "控制台",
    organization: "企业管理",
    accountPlan: "套餐",
    signIn: "登录",
    register: "注册",
    account: "账号",
    authTitle: "登录",
    registerTitle: "创建账号",
    email: "邮箱地址",
    password: "密码",
    passwordPlaceholder: "至少 8 个字符",
    confirmPassword: "确认密码",
    confirmPasswordPlaceholder: "再次输入密码",
    code: "邮箱验证码",
    codePlaceholder: "六位验证码",
    sendCode: "发送验证码",
    resendCode: "重新发送",
    signInAction: "登录",
    createAccount: "创建账号",
    passwordTooShort: "密码至少需要 8 个字符。",
    passwordMismatch: "两次输入的密码不一致。",
    codeRequired: "请先发送并填写邮箱验证码，再创建账号。",
    completeCaptcha: "请先完成安全验证，再继续。",
    registerNow: "还没有账号？立即注册",
    backToSignIn: "已经注册？返回登录",
    openConsole: "进入控制台",
    signOut: "退出登录",
    closeAuth: "关闭账号窗口",
    eyebrow: "本地优先的 PX4 / GAZEBO 调优平台",
    heroLead: "让调优有章法",
    heroAccent: "让飞行更加从容",
    downloadWindows: "下载 Windows 版",
    explore: "了解工作方式",
    releasePrefix: "版本",
    system: "Windows 10 / 11 · x64",
    clickDrone: "点击无人机，开启一次星际巡航",
    scroll: "向下探索",
    productEyebrow: "一条完整的调优链路",
    productTitle: "从控制问题，到可信结果。",
    productBody:
      "参数、仿真、决策和报告都保存在同一个可复现实验中。",
    demoPhases: [
      {
        label: "01 · 定义",
        title: "定义目标飞行任务",
        body: [
          "选择机型、PX4 控制栈、Gazebo 世界与飞行航迹。",
          "同步设定安全边界、试验预算与验收指标。",
          "让每次运行都对应同一个可复现的飞行问题。",
          "在优化器消耗试验前先记录关键假设与约束。",
          "把目标写成可度量的指标，方便后续证据复核。",
          "用清晰规则开始搜索，让后续结果天然可以横向比较。",
        ],
        status: "实验配置完成",
      },
      {
        label: "02 · 搜索",
        title: "选择下一组候选",
        body: [
          "读取历史试验、失败样本与最新仿真反馈。",
          "持续保留参数边界、耦合关系和可行性约束。",
          "让贝叶斯、信赖域、进化和组合搜索共同竞争。",
          "把预算投入模型仍能学习最多信息的区域。",
          "给出下一组候选值，并说明它的探索价值。",
          "从手动猜增益，转向有纪律、可复核的实验搜索。",
        ],
        status: "候选方案 24 / 60",
      },
      {
        label: "03 · 验证",
        title: "用证据比较结果",
        body: [
          "检查可行性、跟踪误差、超调和稳定过程。",
          "比较重复试验、鲁棒场景与 Pareto 权衡。",
          "拒绝只靠破坏隐藏约束取得高分的候选。",
          "把日志、指标、种子和参数快照一起保留。",
          "为每个通过验收的控制设置留下完整证据。",
          "让每一次调优结果都能被团队清楚复核和继续追踪。",
        ],
        status: "通过验收条件",
      },
    ],
    metricLabels: ["跟踪误差", "超调量", "稳定时间"],
    parameterTitle: "当前候选参数",
    parameters: ["MC_ROLL_P", "MC_PITCHRATE_I", "MPC_XY_VEL_P_ACC"],
    workflowEyebrow: "围绕真实实验设计",
    workflowTitle: "把重复工作交给软件。",
    workflow: [
      ["定义任务", "设置机型、航迹、安全边界与验收条件。"],
      ["选择参数", "仅在受控范围内调节选定的 PX4 参数。"],
      ["自动仿真", "隔离运行 PX4 / Gazebo 并保留试验证据。"],
      ["比较决策", "筛选可行候选方案并保存对应决策证据。"],
    ],
    workflowVisualLabel: "从飞行任务到证据决策的自动闭环工作流",
    capabilitiesEyebrow: "为持续迭代而设计",
    capabilitiesTitle: "本地飞行实验室不只是参数表单",
    capabilities: [
      ["按需选择参数", ["单独选择一个 PX4 参数，或直接使用整理好的控制参数组。", "为搜索范围设置安全边界，并同步声明必要的耦合依赖。", "只探索实验真正需要的控制空间，不把预算浪费在无关维度上，并始终保持预算与搜索焦点集中。"], "sliders"],
      ["七种实验算法", ["依据实验结构与搜索空间形态匹配合适的优化算法。", "融合约束、多保真、信赖域与进化搜索共同探索候选。", "复验每一项真实收益，再通过统一的独立验证流程确定最终优胜方案、可靠结论与复核依据。"], "orbit"],
      ["隔离运行环境", ["在专用 WSL2 中运行 PX4、Gazebo、任务进程与试验产物。", "让每次试验都与个人 Linux 文件及现有进程保持严格隔离。", "失败仿真也能安全续传、诊断和清理，并确保下一轮试验在干净环境中稳定启动与完整运行。"], "shield"],
      ["可追溯报告", ["把每个候选方案关联到对应场景、随机种子与参数快照。", "统一保留日志、评测指标、试验产物与完整运行环境清单。", "用完整证据复现每次调优决策，同时保留实验上下文、演进过程、最终判断与完整依据。"], "report"],
    ],
    capabilityOpen: "查看详情",
    capabilityBack: "返回概览",
    capabilityPrevious: "上一项",
    capabilityNext: "下一项",
    capabilityDetails: [
      [
        ["MPC_XY_P", "将水平位置误差转换为速度目标；需要与速度环协同调节，避免修正过猛并保持响应稳定。"],
        ["MPC_XY_VEL_P_ACC", "将水平速度误差转换为加速度需求，直接影响航迹响应速度、超调与稳定性边界。"],
        ["MPC_Z_P", "将高度误差转换为升降速度需求，需要同时考虑垂向速度、加速度限制与稳定裕度。"],
        ["MC_ROLLRATE_P", "决定滚转角速度的比例修正强度，直接影响响应速度、阻尼、振荡风险与控制裕度。"],
        ["MC_PITCHRATE_I", "持续消除俯仰角速度偏差，同时使用安全边界防止长时间机动中的积分饱和风险。"],
      ],
      [
        ["失败感知约束多目标贝叶斯优化", "联合建模目标、可行性与仿真失败，让高风险区域少消耗宝贵试验预算与算力资源。"],
        ["多保真约束多目标贝叶斯优化", "在快速筛选与完整验证之间合理分配预算，同时始终保留严格硬约束与统一验证标准。"],
        ["TuRBO 信赖域贝叶斯优化", "在自适应局部区域搜索耦合参数，验证增益后扩大范围，遇到失败则及时收缩范围。"],
        ["SAAS 约束贝叶斯优化", "先识别高维空间中最关键的参数轴，再把完整仿真预算投入有效维度并减少无效试验。"],
        ["代理模型辅助 CMA-ES", "结合响应代理模型与协方差自适应，提高连续参数搜索精度、试验效率与预算利用率。"],
        ["BIPOP CMA-ES", "交替使用不同重启种群规模，跳出局部最优并保持对复杂搜索地形的持续全局探索。"],
        ["精度优先优化器组合", "在六种互补引擎间分配预算，只让通过统一复验的真实增益进入最终正式决策排名。"],
      ],
      [
        ["专用 WSL2", "独立运行 DroneDream 发行版，不复用也不修改用户已有的个人 Ubuntu 环境。"],
        ["试验隔离", "为每次 PX4 / Gazebo 运行分配独立端口、进程组、临时文件与安全终止边界。"],
        ["固定输入", "启动前记录固件、模型、世界、航迹、参数、种子与高级环境效果，确保可以复现。"],
        ["恢复与清理", "失败时导出诊断并保留有效产物，随后安全清理遗留进程，为下一轮试验干净启动。"],
      ],
      [
        ["配置快照", "保存机型、固件、参数范围、优化算法、约束条件与试验预算，覆盖每个候选方案全貌。"],
        ["场景身份", "把结果关联到世界、航迹、扰动、验证种子与验收条件，便于直接比较与深入复核。"],
        ["日志与指标", "统一保留遥测、进程日志、跟踪指标、时间、失败原因与产物，形成可审计结果。"],
        ["Pareto 证据", "展示误差、超调、稳定时间、鲁棒性与资源成本之间的可行权衡、约束状态及边界变化。"],
        ["复现清单", "对关键输入生成哈希并标记运行环境，让其他电脑也能复现、审计同一决策与完整证据。"],
      ],
    ],
    manualEyebrow: "开始使用",
    manualTitle: "三步开始调优。",
    manualSteps: [
      ["安装桌面程序", "运行 Windows 安装包，并保留推荐目录。"],
      ["准备运行环境", "安装隔离的 PX4 / Gazebo，不修改已有 Ubuntu。"],
      ["创建调优实验", "依次完成五步验证，然后开始调优。"],
    ],
    openManual: "完整说明",
    manualDialogTitle: "DroneDream 快速使用说明书",
    manualDialogIntro: "这份说明覆盖从校验安装包到创建第一次本地调优实验的完整用户流程。",
    manualClose: "关闭说明书",
    manualChapters: [
      ["1 · 检查电脑条件", ["使用 x64 架构的 Windows 10 或 Windows 11 电脑。", "启用 WSL2，并为完整运行环境预留至少 52 GiB 空间。", "如果运行环境不放在系统盘，请选择固定、可写的 NTFS 磁盘。"]],
      ["2 · 安装桌面程序", ["从本页下载带版本号的 EXE；如有需要，先核对 SHA-256。", "运行安装器，选择一种界面语言，并保留推荐的应用程序目录。", "当前正式版本尚未完成 Authenticode 签名；SmartScreen 出现时需要选择“更多信息”并确认运行。"]],
      ["3 · 准备专用运行环境", ["打开 DroneDream，在启动界面开始安装 DroneDreamRuntime。", "下载、校验、导入、启动以及 PX4 / Gazebo 检查期间请保持程序开启。", "这个专用发行版不会替换或修改电脑中已有的个人 Ubuntu。"]],
      ["4 · 创建第一次实验", ["选择使用模式、机型、PX4 版本、Gazebo 模型与世界。", "依次完成五个向导步骤；当前步骤通过验证前，后续步骤始终锁定。", "选择参数及范围，设置场景、航迹、约束和预算，同时确认所有候选值、验证规则和运行边界都符合当前任务要求后再创建实验、启动调优并留存完整配置以及全部必要的关键复核证据与材料。"]],
      ["5 · 阅读并保存结果", ["使用单项指标和 Pareto 权衡比较可行候选方案，不要只看一个综合分数。", "将日志、产物、随机种子、参数快照和复现清单与报告一起保留。", "未经独立安全审查和受控试飞，不要把实验参数直接应用到真实飞行器。"]],
    ],
    integrityTitle: "下载完整性",
    integrityText: "本页显示的 SHA-256 必须与下载后从 EXE 计算得到的值完全一致。",
    github: "在 GitHub 查看源码",
    downloadEyebrow: "WINDOWS 正式版",
    downloadTitle: "在本机运行 DroneDream。",
    downloadBody:
      "先安装桌面程序，再将隔离运行环境放到符合条件的 NTFS 磁盘。",
    downloadAgain: "下载 DroneDream",
    version: "版本",
    size: "安装包大小",
    platform: "平台",
    platformValue: "Windows x64",
    released: "发布日期",
    footerLine: "本地优先的 PX4/Gazebo 控制参数调优平台；1.0.0 正式版已经发布，代码签名正在按公开流程准备。",
    codeSigningPolicy: "代码签名政策",
    privacyPolicy: "隐私政策",
    communityGuidelines: "社区规范",
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

function ArrowRightIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12h14m-5-5 5 5-5 5" />
    </svg>
  );
}

function ScrollIcon() {
  return (
    <svg className="site-scroll-icon" viewBox="0 0 24 34" aria-hidden="true">
      <path d="M12 2v27m-5-6 5 6 5-6" />
    </svg>
  );
}

function DocumentIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6.5 3.5h7.8l3.2 3.2v13.8h-11V3.5Z M14 3.8V7h3.2M9 11h6M9 14h6M9 17h4" />
    </svg>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2.7a9.4 9.4 0 0 0-3 18.3c.5.1.7-.2.7-.5v-1.8c-2.8.6-3.4-1.2-3.4-1.2-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 0 1.6 1.1 1.6 1.1.9 1.6 2.4 1.1 2.9.9.1-.7.4-1.1.7-1.4-2.3-.3-4.6-1.1-4.6-4.7 0-1 .4-1.9 1-2.5-.1-.3-.4-1.3.1-2.6 0 0 .8-.3 2.6 1a9 9 0 0 1 4.8 0c1.8-1.3 2.6-1 2.6-1 .5 1.3.2 2.3.1 2.6.6.6 1 1.5 1 2.5 0 3.6-2.4 4.4-4.6 4.7.4.3.7 1 .7 1.9v2.8c0 .3.2.6.7.5A9.4 9.4 0 0 0 12 2.7Z" />
    </svg>
  );
}

function AccountIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="3.4" />
      <path d="M5.5 20c.5-4.1 2.7-6.2 6.5-6.2s6 2.1 6.5 6.2" />
    </svg>
  );
}

type WorkflowStep = readonly [string, string];
type CapabilityDetail = readonly [string, string];

function WorkflowStepIcon({ index }: { index: number }) {
  return (
    <svg viewBox="0 0 96 96" aria-hidden="true" focusable="false">
      <circle className="site-workflow-node-aura" cx="48" cy="48" r="43" />
      <circle className="site-workflow-node-ring" cx="48" cy="48" r="34" />
      {index === 0 ? (
        <>
          <path className="site-workflow-icon-line" d="M29 59V35h38v24H29Zm7-16c5 0 6 10 12 10s8-10 15-7" />
          <circle className="site-workflow-icon-dot" cx="36" cy="43" r="2.8" />
          <circle className="site-workflow-icon-dot" cx="63" cy="46" r="2.8" />
        </>
      ) : null}
      {index === 1 ? (
        <>
          <path className="site-workflow-icon-line" d="M29 36h38M29 48h38M29 60h38" />
          <circle className="site-workflow-control" cx="41" cy="36" r="4.2" />
          <circle className="site-workflow-control" cx="58" cy="48" r="4.2" />
          <circle className="site-workflow-control" cx="46" cy="60" r="4.2" />
        </>
      ) : null}
      {index === 2 ? (
        <>
          <rect className="site-workflow-chamber" x="29" y="31" width="38" height="34" rx="7" />
          <path className="site-workflow-icon-line" d="M36 40h24M36 48h18M36 56h27" />
          <circle className="site-workflow-icon-dot" cx="62" cy="40" r="2.6" />
          <circle className="site-workflow-icon-dot" cx="56" cy="48" r="2.6" />
          <circle className="site-workflow-icon-dot" cx="64" cy="56" r="2.6" />
        </>
      ) : null}
      {index === 3 ? (
        <>
          <path className="site-workflow-icon-line" d="M29 63V50h8v13M42 63V40h8v23M55 63V32h8v31" />
          <path className="site-workflow-check" d="m52 45 7 7 13-17" />
        </>
      ) : null}
    </svg>
  );
}

function WorkflowLoopVisual({
  label,
  reducedMotion,
  steps,
}: {
  label: string;
  reducedMotion: boolean;
  steps: readonly WorkflowStep[];
}) {
  // Match the desktop visual's 1200 x 400 coordinate space. The rail passes
  // through each icon centre and stays above every title and description.
  const route = "M150 68 C250 68 350 150 450 150 S650 68 750 68 S950 150 1050 150";
  return (
    <figure
      className={`site-workflow-visual${reducedMotion ? " is-reduced-motion" : ""}`}
      aria-labelledby="site-workflow-caption"
      data-reveal
    >
      <figcaption id="site-workflow-caption" className="site-sr-only">{label}</figcaption>
      <svg className="site-workflow-route" viewBox="0 0 1200 400" preserveAspectRatio="none" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="site-workflow-rail" x1="0" x2="1">
            <stop offset="0" stopColor="#68e8ff" />
            <stop offset=".52" stopColor="#9b72ff" />
            <stop offset="1" stopColor="#f166d8" />
          </linearGradient>
          <radialGradient id="site-workflow-node-glow">
            <stop stopColor="#9b72ff" stopOpacity=".34" />
            <stop offset="1" stopColor="#9b72ff" stopOpacity="0" />
          </radialGradient>
          <filter id="site-workflow-soft-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        <path className="site-workflow-return" d="M1050 150 C930 330 360 330 150 68" />
        <path id="site-workflow-route" className="site-workflow-rail-glow" d={route} />
        <path className="site-workflow-rail" d={route} />

        <circle className="site-workflow-packet" r="5" filter="url(#site-workflow-soft-glow)">
          {!reducedMotion ? (
            <animateMotion dur="8s" repeatCount="indefinite" path={route} />
          ) : null}
        </circle>
        <circle className="site-workflow-packet site-workflow-packet-secondary" r="4">
          {!reducedMotion ? (
            <animateMotion dur="8s" begin="-4s" repeatCount="indefinite" path={route} />
          ) : null}
        </circle>
      </svg>
      <ol className="site-workflow-steps">
        {steps.map(([title, description], index) => (
          <li key={`site-workflow-step-${index}`} data-reveal>
            <span className="site-workflow-step-icon"><WorkflowStepIcon index={index} /></span>
            <h3>{title}</h3>
            <p data-copy-block data-copy-id={`workflow-${index}`}>{description}</p>
          </li>
        ))}
      </ol>
    </figure>
  );
}

function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d={direction === "left" ? "m15 5-7 7 7 7" : "m9 5 7 7-7 7"} />
    </svg>
  );
}

function FlipBackIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8 7H4v-4M4.5 7.2A9 9 0 1 1 3 14" />
    </svg>
  );
}

function CapabilityCard({
  index,
  title,
  summary,
  icon,
  details,
  openLabel,
  backLabel,
  previousLabel,
  nextLabel,
}: {
  index: number;
  title: string;
  summary: readonly string[];
  icon: IconName;
  details: readonly CapabilityDetail[];
  openLabel: string;
  backLabel: string;
  previousLabel: string;
  nextLabel: string;
}) {
  const [flipped, setFlipped] = useState(false);
  const [detailIndex, setDetailIndex] = useState(0);
  const frontRef = useRef<HTMLButtonElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);
  const pendingFocusRef = useRef<"front" | "back" | null>(null);
  const detail = details[detailIndex] ?? details[0];
  const detailId = `site-capability-${index}-details`;

  useLayoutEffect(() => {
    const target = pendingFocusRef.current;
    if (!target) return;
    pendingFocusRef.current = null;
    (target === "back" ? backRef.current : frontRef.current)?.focus({ preventScroll: true });
  }, [flipped]);

  const showDetails = () => {
    pendingFocusRef.current = "back";
    setFlipped(true);
  };
  const showOverview = () => {
    pendingFocusRef.current = "front";
    setFlipped(false);
  };
  const move = (delta: number) => {
    setDetailIndex((current) => (current + delta + details.length) % details.length);
  };

  return (
    <article
      className={`site-capability-card card-${index + 1}${flipped ? " is-flipped" : ""}`}
      data-reveal
    >
      <div className="site-capability-card-inner">
        <button
          ref={frontRef}
          type="button"
          className="site-capability-face site-capability-front"
          aria-expanded={flipped}
          aria-controls={detailId}
          aria-label={`${openLabel} ${title}`}
          aria-hidden={flipped}
          tabIndex={flipped ? -1 : 0}
          onClick={showDetails}
        >
          <span className="site-capability-front-heading">
            <span className="site-feature-icon"><FeatureIcon name={icon} /></span>
            <span role="heading" aria-level={3}>{title}</span>
          </span>
          <span className="site-capability-summary" data-copy-block data-copy-id={`capability-summary-${index}`}>
            {summary.map((line) => <span key={line}>{line}</span>)}
          </span>
        </button>

        <section
          id={detailId}
          className="site-capability-face site-capability-back"
          aria-hidden={!flipped}
          aria-label={title}
        >
          <header>
            <span className="site-feature-icon"><FeatureIcon name={icon} /></span>
            <button
              ref={backRef}
              type="button"
              className="site-capability-flip-back"
              aria-label={`${backLabel}: ${title}`}
              tabIndex={flipped ? 0 : -1}
              onClick={showOverview}
            >
              <FlipBackIcon />
            </button>
          </header>
          <div className="site-capability-entry" aria-live="polite" aria-atomic="true">
            <h3>{detail?.[0]}</h3>
            <p data-copy-block data-copy-id={`capability-detail-${index}-${detailIndex}`}>{detail?.[1]}</p>
          </div>
          <nav aria-label={title}>
            <button
              type="button"
              aria-label={previousLabel}
              tabIndex={flipped ? 0 : -1}
              onClick={() => move(-1)}
            >
              <ChevronIcon direction="left" />
            </button>
            <span>{detailIndex + 1} / {details.length}</span>
            <button
              type="button"
              aria-label={nextLabel}
              tabIndex={flipped ? 0 : -1}
              onClick={() => move(1)}
            >
              <ChevronIcon direction="right" />
            </button>
          </nav>
        </section>
      </div>
    </article>
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
  const auth = useAuthOrLocal();
  const copy = content[locale];
  const [release, setRelease] = useState<WebsiteRelease>(fallbackRelease);
  const [editionAvailability, setEditionAvailability] =
    useState<EditionAvailabilityDocument>(fallbackEditionAvailability);
  const [activePhase, setActivePhase] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<"sign-in" | "register">("sign-in");
  const [authEmail, setAuthEmail] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [authCodeSent, setAuthCodeSent] = useState(false);
  const [authPassword, setAuthPassword] = useState("");
  const [authPasswordConfirmation, setAuthPasswordConfirmation] = useState("");
  const [authCaptchaToken, setAuthCaptchaToken] = useState<string | null>(null);
  const [authCaptchaCycle, setAuthCaptchaCycle] = useState(0);
  const [authPending, setAuthPending] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [organizationAccess, setOrganizationAccess] =
    useState<OrganizationAccess | null>(null);
  const [accountPlan, setAccountPlan] = useState<{
    name: string;
    billingScope: "individual" | "business";
  } | null>(null);
  const reducedMotion = usePrefersReducedMotion();
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const droneFlightRef = useRef<(() => void) | null>(null);
  const authDialogRef = useRef<HTMLElement>(null);
  const authCloseRef = useRef<HTMLButtonElement>(null);
  const oauthPromptedRef = useRef(false);
  const path = window.location.pathname.replace(/\/+$/u, "") || "/";
  const sitePage = path === "/manual"
    ? "manual"
    : path === "/product"
      ? "product"
      : path === "/pricing"
        ? "pricing"
      : path === "/organization"
        ? "organization"
      : path === "/community"
        ? "community"
        : path === "/oauth/consent"
          ? "oauth-consent"
        : "home";

  useEffect(() => {
    let active = true;
    if (!auth.account) {
      setOrganizationAccess(null);
      setAccountPlan(null);
      return () => { active = false; };
    }
    void Promise.allSettled([
      getOrganizationAccess(),
      getManagedModelUsage(),
    ]).then(([organizationResult, usageResult]) => {
      if (!active) return;
      setOrganizationAccess(
        organizationResult.status === "fulfilled" ? organizationResult.value : null,
      );
      setAccountPlan(
        usageResult.status === "fulfilled"
          ? {
              name: usageResult.value.plan.name,
              billingScope: usageResult.value.account?.billing_scope ?? "individual",
            }
          : null,
      );
    });
    return () => { active = false; };
  }, [auth.account]);

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
    const controller = new AbortController();
    fetch("/downloads/editions.json", { signal: controller.signal, cache: "no-cache" })
      .then((response) => {
        if (!response.ok) throw new Error(`edition metadata: ${response.status}`);
        return response.json() as Promise<unknown>;
      })
      .then((candidate) => {
        if (isEditionAvailabilityDocument(candidate)) setEditionAvailability(candidate);
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
    const encodedTargetId = window.location.hash.replace(/^#/u, "");
    let targetId = encodedTargetId;
    try {
      targetId = decodeURIComponent(encodedTargetId);
    } catch {
      // A malformed external hash must never prevent the public site from rendering.
    }
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
      ".site-hero, .site-product-demo, .site-workflow-visual",
    ));
    if (!("IntersectionObserver" in window)) {
      nodes.forEach((node) => node.classList.add("is-motion-visible"));
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        entry.target.classList.toggle("is-motion-visible", entry.isIntersecting);
        if (!(entry.target instanceof HTMLElement) || !entry.target.classList.contains("site-workflow-visual")) return;
        const svg = entry.target.querySelector<SVGSVGElement>("svg");
        if (!svg || typeof svg.pauseAnimations !== "function") return;
        if (entry.isIntersecting) svg.unpauseAnimations();
        else svg.pauseAnimations();
      }),
      { rootMargin: "160px 0px", threshold: 0.01 },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!authOpen) return;
    const previousOverflow = document.body.style.overflow;
    const inertTargets = Array.from(document.querySelectorAll<HTMLElement>(
      ".site-header, #main-content, .site-footer",
    ));
    const previousInertStates = inertTargets.map((target) => target.inert);
    document.body.style.overflow = "hidden";
    inertTargets.forEach((target) => {
      target.inert = true;
    });
    const focusFrame = window.requestAnimationFrame(() => {
      const firstInput = authDialogRef.current?.querySelector<HTMLInputElement>(
        "input:not(:disabled)",
      );
      (auth.account ? authCloseRef.current : firstInput)?.focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setAuthOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        authDialogRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
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
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      inertTargets.forEach((target, index) => {
        target.inert = previousInertStates[index] ?? false;
      });
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [auth.account, authOpen]);

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
  const openAccount = (mode: "sign-in" | "register" = "sign-in") => {
    setAuthMode(mode);
    setAuthCode("");
    setAuthCodeSent(false);
    setAuthPassword("");
    setAuthPasswordConfirmation("");
    setAuthCaptchaToken(null);
    setAuthCaptchaCycle((current) => current + 1);
    setAuthError(null);
    setMenuOpen(false);
    setAuthOpen(true);
  };

  useEffect(() => {
    if (sitePage !== "oauth-consent") return;
    if (auth.account && authOpen) {
      setAuthOpen(false);
    } else if (
      auth.configured
      && !auth.loading
      && !auth.account
      && !authOpen
      && !oauthPromptedRef.current
    ) {
      oauthPromptedRef.current = true;
      openAccount("sign-in");
    }
  }, [auth.account, auth.configured, auth.loading, authOpen, sitePage]);

  const openConsole = () => {
    if (auth.account) {
      window.location.assign("/console/");
      return;
    }
    openAccount("sign-in");
  };

  const submitAuth = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (authPending) return;
    setAuthPending(true);
    setAuthError(null);
    try {
      if (authMode === "sign-in") {
        if (captchaProtectionConfigured && !authCaptchaToken) {
          throw new Error(copy.completeCaptcha);
        }
        if (authCaptchaToken) {
          await auth.signInWithPassword(
            authEmail,
            authPassword,
            authCaptchaToken,
          );
        } else {
          await auth.signInWithPassword(authEmail, authPassword);
        }
      } else {
        if (authPassword.length < 8) {
          throw new Error(copy.passwordTooShort);
        }
        if (authPassword !== authPasswordConfirmation) {
          throw new Error(copy.passwordMismatch);
        }
        if (!authCodeSent || !authCode.trim()) {
          throw new Error(copy.codeRequired);
        }
        await auth.verifyRegistrationCode(
          authEmail,
          authCode,
          authPassword,
        );
      }
    } catch (reason) {
      setAuthError(
        reason instanceof Error ? reason.message : "Account request failed.",
      );
    } finally {
      setAuthPending(false);
      if (authMode === "sign-in" && captchaProtectionConfigured) {
        setAuthCaptchaToken(null);
        setAuthCaptchaCycle((current) => current + 1);
      }
    }
  };

  const sendRegistrationCode = async () => {
    if (authPending) return;
    setAuthError(null);
    if (authPassword.length < 8) {
      setAuthError(copy.passwordTooShort);
      return;
    }
    if (authPassword !== authPasswordConfirmation) {
      setAuthError(copy.passwordMismatch);
      return;
    }
    if (captchaProtectionConfigured && !authCaptchaToken) {
      setAuthError(copy.completeCaptcha);
      return;
    }
    setAuthPending(true);
    try {
      if (authCaptchaToken) {
        await auth.sendRegistrationCode(authEmail, authCaptchaToken);
      } else {
        await auth.sendRegistrationCode(authEmail);
      }
      setAuthCodeSent(true);
    } catch (reason) {
      setAuthError(
        reason instanceof Error ? reason.message : "Account request failed.",
      );
    } finally {
      setAuthPending(false);
      if (captchaProtectionConfigured) {
        setAuthCaptchaToken(null);
        setAuthCaptchaCycle((current) => current + 1);
      }
    }
  };

  return (
    <div className="dd-site" data-locale={locale} data-page={sitePage}>
      <a className="site-skip-link" href="#main-content">{copy.skip}</a>
      <header className={`site-header${scrolled ? " is-scrolled" : ""}`}>
        <a className="site-brand" href="/" onClick={closeMenu} aria-label="DroneDream">
          <BrandLockup variant="primary" />
        </a>
        <nav
          id="site-navigation"
          className={`site-nav${menuOpen ? " is-open" : ""}`}
          aria-label={copy.navLabel}
        >
          {copy.nav.map(([label, target]) => (
            <a key={target} href={target} onClick={closeMenu}>{label}</a>
          ))}
          {organizationAccess?.authorized ? (
            <a href="/organization/" onClick={closeMenu}>{copy.organization}</a>
          ) : null}
          <button type="button" onClick={openConsole}>{copy.console}</button>
        </nav>
        <div className="site-header-actions">
          <button
            type="button"
            className="site-account-button"
            onClick={() => openAccount("sign-in")}
          >
            <AccountIcon />
            <span>{auth.account ? copy.account : copy.signIn}</span>
          </button>
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
            <DownloadIcon />
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
        {sitePage === "manual" ? (
          <ManualPage locale={locale} />
        ) : sitePage === "product" ? (
          <ProductPage availability={editionAvailability} locale={locale} />
        ) : sitePage === "pricing" ? (
          <PricingPage
            locale={locale}
            authenticated={Boolean(auth.account)}
            onRequireAccount={() => openAccount("register")}
          />
        ) : sitePage === "organization" ? (
          <OrganizationPage locale={locale} />
        ) : sitePage === "community" ? (
          <CommunityPage
            locale={locale}
            account={auth.account}
            onRequireAccount={() => openAccount("sign-in")}
          />
        ) : sitePage === "oauth-consent" ? (
          <OAuthConsentPage
            locale={locale}
            account={auth.account}
            authConfigured={auth.configured}
            authLoading={auth.loading}
            onRequireSignIn={() => openAccount("sign-in")}
          />
        ) : (
          <>
        <section className="site-hero" id="home" aria-labelledby="hero-title">
          <div className="site-hero-scene" aria-hidden="true">
            <DroneLaunchScene
              active
              starflightControllerRef={droneFlightRef}
              themeOverride={WEBSITE_DRONE_THEME}
              visualOffsetX={1.58}
            />
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
                <a className="site-button site-button-ghost" href="#product">
                  <ArrowRightIcon />
                  {copy.explore}
                </a>
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
            <ScrollIcon />
          </a>
        </section>

        <section className="site-section site-product" id="product">
          <div className="site-shell">
            <div className="site-section-heading" data-reveal>
              <p className="site-eyebrow">{copy.productEyebrow}</p>
              <h2>{copy.productTitle}</h2>
              <p data-copy-block data-copy-id="product-body">{copy.productBody}</p>
            </div>
            <div className="site-product-demo" data-reveal>
              <div className="site-demo-copy">
                <div className="site-phase-tabs" role="tablist" aria-label={copy.productEyebrow}>
                  {copy.demoPhases.map((phase, index) => (
                    <button
                      key={`site-phase-tab-${index}`}
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
                    key={`site-phase-panel-${index}`}
                    id={`site-phase-panel-${index}`}
                    className="site-phase-copy"
                    role="tabpanel"
                    aria-labelledby={`site-phase-tab-${index}`}
                    tabIndex={0}
                    hidden={activePhase !== index}
                  >
                    <span>{phase.label}</span>
                    <h3>{phase.title}</h3>
                    <p className="site-phase-description" data-copy-block data-copy-id={`phase-${index}`}>
                      {phase.body.map((line, lineIndex) => (
                        <span key={`site-phase-line-${index}-${lineIndex}`}>{line}</span>
                      ))}
                    </p>
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
                      {copy.metricLabels.map((label, index) => <span key={`site-metric-${index}`} style={{ "--index": index } as React.CSSProperties}>{label}</span>)}
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
                      <div key={`site-parameter-${index}`}>
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
            <WorkflowLoopVisual
              label={copy.workflowVisualLabel}
              reducedMotion={reducedMotion}
              steps={copy.workflow}
            />
          </div>
        </section>

        <section className="site-section site-capabilities" id="capabilities">
          <div className="site-shell">
            <div className="site-section-heading" data-reveal>
              <p className="site-eyebrow">{copy.capabilitiesEyebrow}</p>
              <h2>{copy.capabilitiesTitle}</h2>
            </div>
            <div className="site-capability-grid">
              {copy.capabilities.map(([title, summary, icon], index) => (
                <CapabilityCard
                  key={`site-capability-${index}`}
                  index={index}
                  title={title}
                  summary={summary}
                  icon={icon as IconName}
                  details={copy.capabilityDetails[index]}
                  openLabel={copy.capabilityOpen}
                  backLabel={copy.capabilityBack}
                  previousLabel={copy.capabilityPrevious}
                  nextLabel={copy.capabilityNext}
                />
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
                <a href="/manual/"><DocumentIcon /><span>{copy.openManual}</span></a>
                <a href={GITHUB_URL} target="_blank" rel="noreferrer"><GitHubIcon /><span>{copy.github}</span></a>
              </div>
            </div>
            <ol className="site-manual-steps">
              {copy.manualSteps.map(([title, description], index) => (
                <li key={`site-manual-step-${index}`} data-reveal>
                  <span>{index + 1}</span>
                  <div><h3>{title}</h3><p data-copy-block data-copy-id={`manual-step-${index}`}>{description}</p></div>
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
                <p data-copy-block data-copy-id="download-body">{copy.downloadBody}</p>
                <a className="site-button site-button-primary" href={release.downloadUrl} download={release.fileName}>
                  <DownloadIcon />
                  {copy.downloadAgain}
                </a>
              </div>
              <div className="site-release-card">
                <dl>
                  <div><dt>{copy.version}</dt><dd>{release.version}</dd></div>
                  <div><dt>{copy.size}</dt><dd>{displaySize}</dd></div>
                  <div><dt>{copy.platform}</dt><dd>{copy.platformValue}</dd></div>
                  <div><dt>{copy.released}</dt><dd>{release.publishedAt}</dd></div>
                </dl>
              </div>
            </div>
          </div>
        </section>
          </>
        )}
      </main>

      {authOpen ? (
        <div
          className="site-auth-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAuthOpen(false);
          }}
        >
          <section
            ref={authDialogRef}
            className="site-auth-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="site-auth-title"
          >
            <header>
              <h2 id="site-auth-title">
                {auth.account
                  ? copy.account
                  : authMode === "register"
                    ? copy.registerTitle
                    : copy.authTitle}
              </h2>
              <button
                ref={authCloseRef}
                type="button"
                aria-label={copy.closeAuth}
                onClick={() => setAuthOpen(false)}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m7 7 10 10M17 7 7 17" />
                </svg>
              </button>
            </header>
            {auth.account ? (
              <div className="site-auth-account">
                <AccountIcon />
                <strong>{auth.account.displayName}</strong>
                <span>{auth.account.email}</span>
                {accountPlan ? (
                  <span className="site-auth-plan">
                    {copy.accountPlan}: {accountPlan.billingScope === "business" ? "Business " : ""}{accountPlan.name}
                  </span>
                ) : null}
                <a className="site-button site-button-primary" href="/console/">
                  {copy.openConsole}
                  <ArrowRightIcon />
                </a>
                {organizationAccess?.authorized ? (
                  <a className="site-button site-button-secondary" href="/organization/">
                    {copy.organization}
                    <ArrowRightIcon />
                  </a>
                ) : null}
                <button
                  type="button"
                  className="site-auth-text-button"
                  disabled={authPending}
                  onClick={() => {
                    setAuthPending(true);
                    setAuthError(null);
                    void auth.signOut()
                      .catch((reason: unknown) => {
                        setAuthError(
                          reason instanceof Error
                            ? reason.message
                            : "Account request failed.",
                        );
                      })
                      .finally(() => setAuthPending(false));
                  }}
                >
                  {copy.signOut}
                </button>
              </div>
            ) : (
              <>
                <form className="site-auth-form" onSubmit={(event) => void submitAuth(event)}>
                  <label>
                    <span>{copy.email}</span>
                    <input
                      type="email"
                      required
                      autoComplete="email"
                      value={authEmail}
                      disabled={
                        authPending ||
                        (authMode === "register" && authCodeSent)
                      }
                      onChange={(event) => setAuthEmail(event.target.value)}
                    />
                  </label>
                  <label>
                    <span>{copy.password}</span>
                    <input
                      type="password"
                      required
                      minLength={8}
                      autoComplete={
                        authMode === "register"
                          ? "new-password"
                          : "current-password"
                      }
                      value={authPassword}
                      placeholder={copy.passwordPlaceholder}
                      disabled={authPending}
                      onChange={(event) => setAuthPassword(event.target.value)}
                    />
                  </label>
                  {authMode === "register" ? (
                    <>
                      <label>
                        <span>{copy.confirmPassword}</span>
                        <input
                          type="password"
                          required
                          minLength={8}
                          autoComplete="new-password"
                          value={authPasswordConfirmation}
                          placeholder={copy.confirmPasswordPlaceholder}
                          disabled={authPending}
                          onChange={(event) =>
                            setAuthPasswordConfirmation(event.target.value)
                          }
                        />
                      </label>
                      <div className="site-auth-code-field">
                        <label htmlFor="site-registration-code">
                          <span>{copy.code}</span>
                        </label>
                        <div className="site-auth-code-row">
                          <input
                            id="site-registration-code"
                            type="text"
                            required
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            minLength={6}
                            maxLength={12}
                            value={authCode}
                            placeholder={copy.codePlaceholder}
                            disabled={authPending}
                            onChange={(event) =>
                              setAuthCode(event.target.value.replace(/\s/gu, ""))
                            }
                          />
                          <button
                            type="button"
                            className="site-auth-code-button"
                            disabled={authPending || !authEmail.trim()}
                            onClick={() => void sendRegistrationCode()}
                          >
                            {authCodeSent ? copy.resendCode : copy.sendCode}
                          </button>
                        </div>
                      </div>
                    </>
                  ) : null}
                  {captchaProtectionConfigured ? (
                    <AuthCaptcha
                      key={authCaptchaCycle}
                      siteKey={turnstileSiteKey}
                      onTokenChange={setAuthCaptchaToken}
                    />
                  ) : null}
                  <button type="submit" disabled={authPending || auth.loading}>
                    {authMode === "register"
                      ? copy.createAccount
                      : copy.signInAction}
                  </button>
                </form>
                <button
                  type="button"
                  className="site-auth-text-button"
                  disabled={authPending}
                  onClick={() => {
                    setAuthMode((current) =>
                      current === "sign-in" ? "register" : "sign-in",
                    );
                    setAuthCode("");
                    setAuthCodeSent(false);
                    setAuthPassword("");
                    setAuthPasswordConfirmation("");
                    setAuthCaptchaToken(null);
                    setAuthCaptchaCycle((current) => current + 1);
                    setAuthError(null);
                  }}
                >
                  {authMode === "sign-in"
                    ? copy.registerNow
                    : copy.backToSignIn}
                </button>
              </>
            )}
            {authError ? <div className="site-auth-error" role="alert">{authError}</div> : null}
          </section>
        </div>
      ) : null}

      {sitePage === "home" ? (
        <footer className="site-footer">
          <div className="site-shell">
            <div className="site-footer-brand" role="img" aria-label="DroneDream">
              <BrandLockup variant="primary" />
            </div>
            <p data-copy-block data-copy-id="footer-line">{copy.footerLine}</p>
            <nav className="site-footer-policy-links" aria-label={copy.privacyPolicy}>
              <a href={CODE_SIGNING_POLICY_URL} target="_blank" rel="noreferrer">
                <FeatureIcon name="shield" />
                {copy.codeSigningPolicy}
              </a>
              <a href={PRIVACY_POLICY_URL} target="_blank" rel="noreferrer">
                <DocumentIcon />
                {copy.privacyPolicy}
              </a>
              <a href={COMMUNITY_GUIDELINES_URL} target="_blank" rel="noreferrer">
                <FeatureIcon name="report" />
                {copy.communityGuidelines}
              </a>
            </nav>
            <a href={GITHUB_URL} target="_blank" rel="noreferrer"><GitHubIcon /><span>GitHub</span></a>
          </div>
        </footer>
      ) : null}
    </div>
  );
}
