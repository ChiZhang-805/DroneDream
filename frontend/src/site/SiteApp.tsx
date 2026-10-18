import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import { BrandLockup } from "../components/BrandLockup";
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
import { useI18n } from "../i18n/I18nProvider";
import { CommunityPage } from "./CommunityPage";
import { HomeExperience } from "./HomeExperience";
import { ManualPage } from "./ManualPage";
import { OAuthConsentPage } from "./OAuthConsentPage";
import { authorizationIdFromLocation } from "./oauthConsentPolicy";
import { OrganizationPage } from "./OrganizationPage";
import { PricingPage } from "./PricingPage";
import { ProductPage } from "./ProductPage";
import {
  fallbackEditionAvailability,
  isEditionAvailabilityDocument,
  type EditionAvailabilityDocument,
} from "./editionAvailability";
import {
  fallbackRelease,
  isReleaseCandidateNonDowngrade,
  isWebsiteRelease,
  type WebsiteRelease,
} from "./release";

const PolicyDialog = lazy(() => import("./PolicyDialog"));

type AuthMode =
  | "sign-in"
  | "register"
  | "recovery-choice"
  | "recovery-sign-in"
  | "recovery-password"
  | "reset-update";

const content = {
  en: {
    skip: "Skip to content",
    metaTitle: "DroneDream",
    metaDescription: "Plan, simulate, monitor, and extend autonomous UAV missions in one local Windows workspace.",
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
    downloadMenuTitle: "Choose your DroneDream edition",
    downloadMenuHint: "Windows 10 / 11 · x64 · Version 1.0.0",
    downloadDescriptions: {
      universal: "The complete workspace for cross-product orchestration",
      sim: "Repeatable PX4 and Gazebo simulation experiments",
      lab: "Simulation-to-hardware validation and calibration",
      field: "Guarded real-device operation and field tuning",
      autonomy: "Natural-language autonomous mission workflows",
    },
    console: "Console",
    organization: "Manage organization",
    accountPlan: "Plan",
    businessPlan: "Business",
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
    accountRequestFailed: "The account request could not be completed. Please try again.",
    registerNow: "Register",
    backToSignIn: "Back to sign in",
    forgotPassword: "Forgot password",
    recoveryTitle: "Recover account",
    recoveryCodeSignIn: "Sign in with an email code",
    recoveryPassword: "Reset password with an email code",
    recoverySignInTitle: "Email code sign-in",
    recoveryPasswordTitle: "Reset password",
    recoveryCodeRequired: "Send and enter the email verification code first.",
    recoveryCodeSent: "Verification code sent.",
    signInWithCode: "Sign in",
    resetAndSignIn: "Reset password and sign in",
    resetUpdateTitle: "Choose a new password",
    resetUpdateBody: "This email link verified the reset request. Choose a new password to finish.",
    updatePassword: "Update password",
    passwordUpdated: "Your password has been updated.",
    openConsole: "Open console",
    signOut: "Sign out",
    closeAuth: "Close account dialog",
    eyebrow: "NATURAL-LANGUAGE UAV ENGINEERING",
    heroLead: "Describe the mission.",
    heroAccent: "See it take flight.",
    downloadWindows: "Download for Windows",
    explore: "See how it works",
    releasePrefix: "Version",
    system: "Windows 10 / 11 · x64",
    clickDrone: "Click the drone to begin a starflight",
    scroll: "Scroll to explore",
    productEyebrow: "ONE CONTINUOUS WORKFLOW",
    productTitle: "From intent to a running mission.",
    productBody:
      "Keep the request, map, aircraft, route, simulation, and live state in one connected workspace.",
    demoPhases: [
      {
        label: "01 · Describe",
        title: "Describe the outcome",
        body: [
          "Ask for the result in ordinary language.",
          "Mention a building, item, inspection, or destination.",
          "Use the selected map and aircraft as context.",
          "Resolve familiar names into real map locations.",
          "Keep the request concise and human.",
          "Let the workspace assemble the technical details.",
        ],
        status: "Intent understood",
      },
      {
        label: "02 · Plan",
        title: "Build the complete route",
        body: [
          "Resolve start, destination, and handoff points.",
          "Route through usable space between buildings.",
          "Keep clearance while smoothing tight turns.",
          "Choose an aircraft and required payloads.",
          "Turn the request into ordered mission actions.",
          "Show the plan before the flight begins.",
        ],
        status: "Route ready",
      },
      {
        label: "03 · Fly",
        title: "Run and watch the mission",
        body: [
          "Launch PX4 and Gazebo through the local Runtime.",
          "Follow the aircraft on the 2D route view.",
          "Switch to simulation, forward, or gimbal cameras.",
          "Watch altitude, position, speed, and progress live.",
          "Complete pickup, inspection, and return actions.",
          "Finish the full mission in one continuous run.",
        ],
        status: "Mission in progress",
      },
    ],
    metricLabels: ["Route progress", "Flight speed", "Link quality"],
    parameterTitle: "Live mission",
    parameters: ["Altitude", "Ground speed", "Payload state"],
    workflowEyebrow: "BUILT AROUND THE MISSION",
    workflowTitle: "One flow from request to flight.",
    workflow: [
      ["Describe", "State the destination, item, or inspection."],
      ["Plan", "Resolve places, actions, aircraft, and route."],
      ["Simulate", "Run PX4 and Gazebo in the selected world."],
      ["Monitor", "Watch position, altitude, cameras, and progress."],
    ],
    workflowVisualLabel: "An automated flow from natural-language request to monitored flight",
    capabilitiesEyebrow: "ONE CONNECTED WORKSPACE",
    capabilitiesTitle: "The map, aircraft, simulator, and live view stay together.",
    capabilities: [
      ["Map intelligence", ["Name buildings, entrances, and handoff points.", "Plan through usable corridors with practical clearance.", "Turn familiar place names into executable destinations."], "sliders"],
      ["Aircraft & payloads", ["Select a verified airframe for the mission.", "Pair cameras, depth, LiDAR, gimbal, and payload tools.", "Keep vehicle capability visible before launch."], "orbit"],
      ["Local runtime", ["Coordinate PX4, Gazebo, ROS 2, maps, and mission services.", "Keep the flight stack behind one desktop interface.", "Open the workspace when the required services are ready."], "shield"],
      ["Live mission views", ["Switch between 2D route and camera views.", "See current position, altitude, speed, and mission phase.", "Open the larger Live workspace whenever needed."], "report"],
    ],
    capabilityOpen: "Open details for",
    capabilityBack: "Return to overview",
    capabilityPrevious: "Previous detail",
    capabilityNext: "Next detail",
    capabilityDetails: [
      [
        ["Named buildings", "Give every building an English name, optional localized aliases, and a clear role so everyday requests resolve to the right place."],
        ["Entrances", "Bind usable entrances and handoff points to the building geometry instead of stopping at an approximate center coordinate."],
        ["Flight corridors", "Route between buildings with practical clearance and smooth corners rather than cutting straight across roofs."],
        ["Mission places", "Connect pickup, inspection, delivery, and return actions to the places where those actions can actually happen."],
      ],
      [
        ["Airframes", "Keep a focused set of working aircraft configurations instead of presenting unverified variants as ready to fly."],
        ["Perception", "Choose forward cameras, depth cameras, gimbals, optical flow, or LiDAR for the scene and mission."],
        ["Payload actions", "Represent pickup, carrying, inspection, and delivery as concrete steps in the mission plan."],
        ["Import", "Bring in a new aircraft package with its model, configuration, and required assets through one guided dialog."],
      ],
      [
        ["Dedicated services", "Run PX4, Gazebo, ROS 2 bridges, planning tools, and live streams through the DroneDream Runtime."],
        ["One launch path", "Start and check the required local services before opening the main workspace."],
        ["Asset coordination", "Load the selected map, aircraft, sensors, and mission tools into the same execution context."],
        ["Continuous execution", "Let a healthy aircraft complete the full mission while it corrects ordinary route deviations in flight."],
      ],
      [
        ["2D route", "Project the planned corridor onto the map with start, waypoint, destination, and current aircraft position."],
        ["Camera views", "Move between simulation, forward-camera, and gimbal views without leaving the mission conversation."],
        ["Flight state", "Keep altitude, speed, position, payload state, and mission phase visible while the simulation runs."],
        ["Live workspace", "Open the larger Live page when the operator needs more room for cameras and telemetry."],
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
    footerLine: "Local-first UAV planning, simulation, and mission control. Version 1.0.0 is available now.",
    policies: "Policies",
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
    downloadMenuTitle: "选择适合你的 DroneDream 版本",
    downloadMenuHint: "Windows 10 / 11 · x64 · 版本 1.0.0",
    downloadDescriptions: {
      universal: "用于跨产品协同与编排的完整工作台",
      sim: "可重复运行的 PX4 与 Gazebo 仿真实验",
      lab: "仿真到硬件的双向验证与标定",
      field: "带安全边界的实机运行与现场调参",
      autonomy: "通过自然语言完成自主任务工作流",
    },
    console: "控制台",
    organization: "企业管理",
    accountPlan: "套餐",
    businessPlan: "企业",
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
    accountRequestFailed: "无法完成账号请求，请稍后重试。",
    registerNow: "注册",
    backToSignIn: "返回登录",
    forgotPassword: "忘记密码",
    recoveryTitle: "找回账号",
    recoveryCodeSignIn: "使用邮箱验证码登录",
    recoveryPassword: "使用邮箱验证码修改密码",
    recoverySignInTitle: "邮箱验证码登录",
    recoveryPasswordTitle: "修改密码",
    recoveryCodeRequired: "请先发送并填写邮箱验证码。",
    recoveryCodeSent: "验证码已发送。",
    signInWithCode: "登录",
    resetAndSignIn: "修改密码并登录",
    resetUpdateTitle: "设置新密码",
    resetUpdateBody: "邮件链接已确认本次重置请求，请设置新密码以完成操作。",
    updatePassword: "更新密码",
    passwordUpdated: "密码已更新。",
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
      ["按需选择参数", ["单独选择一个 PX4 参数，或直接使用整理好的控制参数组。", "为搜索范围设置安全边界，并同步声明必要的耦合依赖。", "只探索实验真正需要的控制空间，不浪费试验预算，并始终保持搜索重点集中。"], "sliders"],
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
    policies: "政策",
    communityGuidelines: "社区规范",
  },
} as const;

function DownloadChevronIcon() {
  return (
    <svg className="site-header-download-chevron" viewBox="0 0 16 16" aria-hidden="true">
      <path d="m3.5 6 4.5 4 4.5-4" />
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

function AccountIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="8" r="3.4" />
      <path d="M5.5 20c.5-4.1 2.7-6.2 6.5-6.2s6 2.1 6.5 6.2" />
    </svg>
  );
}

export function SiteApp() {
  const { setLocale } = useI18n();
  const locale = "en" as const;
  const auth = useAuthOrLocal();
  const copy = content.en;
  const [release, setRelease] = useState<WebsiteRelease>(fallbackRelease);
  const [editionAvailability, setEditionAvailability] =
    useState<EditionAvailabilityDocument>(fallbackEditionAvailability);
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("sign-in");
  const [authEmail, setAuthEmail] = useState("");
  const [authCode, setAuthCode] = useState("");
  const [authCodeSent, setAuthCodeSent] = useState(false);
  const [authPassword, setAuthPassword] = useState("");
  const [authPasswordConfirmation, setAuthPasswordConfirmation] = useState("");
  const [authCaptchaToken, setAuthCaptchaToken] = useState<string | null>(null);
  const [authCaptchaCycle, setAuthCaptchaCycle] = useState(0);
  const [authPending, setAuthPending] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authNotice, setAuthNotice] = useState<string | null>(null);
  const [organizationAccess, setOrganizationAccess] =
    useState<OrganizationAccess | null>(null);
  const [accountPlan, setAccountPlan] = useState<{
    name: string;
    billingScope: "individual" | "business";
  } | null>(null);
  useLayoutEffect(() => {
    setLocale("en");
    document.documentElement.lang = "en";
  }, [setLocale]);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const accountButtonRef = useRef<HTMLButtonElement>(null);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const authDialogRef = useRef<HTMLElement>(null);
  const authCloseRef = useRef<HTMLButtonElement>(null);
  const closePolicies = useCallback(() => {
    setPolicyOpen(false);
    requestAnimationFrame(() => accountButtonRef.current?.focus());
  }, []);
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
  const oauthAuthorizationId = sitePage === "oauth-consent"
    ? authorizationIdFromLocation()
    : null;
  const hasValidOAuthAuthorizationId = oauthAuthorizationId !== null;
  const [desktopOAuthFreshAuthReady, setDesktopOAuthFreshAuthReady] = useState(false);
  const desktopOAuthPreparedRef = useRef<string | null>(null);
  const oauthAuthPage = hasValidOAuthAuthorizationId && (
    !desktopOAuthFreshAuthReady || !auth.account || authPending || Boolean(authError)
  );

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
          isReleaseCandidateNonDowngrade(candidate, fallbackRelease)
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
      (
        auth.account && authMode !== "reset-update"
          ? authCloseRef.current
          : firstInput
      )?.focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (
        event.key === "Escape"
        && authMode !== "reset-update"
        && !oauthAuthPage
      ) {
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
  }, [auth.account, authMode, authOpen, oauthAuthPage]);

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

  useEffect(() => {
    if (!accountMenuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (
        event.target instanceof Node
        && !accountMenuRef.current?.contains(event.target)
      ) {
        setAccountMenuOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setAccountMenuOpen(false);
      accountButtonRef.current?.focus();
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [accountMenuOpen]);

  const closeMenu = () => {
    setMenuOpen(false);
    setAccountMenuOpen(false);
  };
  const openAccount = useCallback((mode: AuthMode = "sign-in") => {
    setAuthMode(mode);
    setAuthCode("");
    setAuthCodeSent(false);
    setAuthPassword("");
    setAuthPasswordConfirmation("");
    setAuthCaptchaToken(null);
    setAuthCaptchaCycle((current) => current + 1);
    setAuthError(null);
    setAuthNotice(null);
    setMenuOpen(false);
    setAccountMenuOpen(false);
    setAuthOpen(true);
  }, []);

  const localizedAuthError = useCallback((reason: unknown): string => {
    const message = reason instanceof Error ? reason.message : "";
    const localizedValidationMessages: string[] = [
      copy.passwordTooShort,
      copy.passwordMismatch,
      copy.codeRequired,
      copy.recoveryCodeRequired,
      copy.completeCaptcha,
    ];
    return localizedValidationMessages.includes(message)
      ? message
      : copy.accountRequestFailed;
  }, [
    copy.accountRequestFailed,
    copy.codeRequired,
    copy.completeCaptcha,
    copy.passwordMismatch,
    copy.passwordTooShort,
    copy.recoveryCodeRequired,
  ]);

  useEffect(() => {
    if (!auth.passwordRecovery) return;
    setAuthMode("reset-update");
    setAuthPassword("");
    setAuthPasswordConfirmation("");
    setAuthError(null);
    setAuthNotice(null);
    setAuthOpen(true);
  }, [auth.passwordRecovery]);

  useEffect(() => {
    if (sitePage !== "oauth-consent" || !hasValidOAuthAuthorizationId) return;
    if (auth.loading) return;
    if (desktopOAuthPreparedRef.current !== oauthAuthorizationId) {
      desktopOAuthPreparedRef.current = oauthAuthorizationId;
      setDesktopOAuthFreshAuthReady(false);
      if (auth.account) {
        setAuthPending(true);
        void auth.signOut()
          .catch((reason: unknown) => setAuthError(localizedAuthError(reason)))
          .finally(() => {
            setAuthPending(false);
            openAccount("sign-in");
          });
      } else {
        openAccount("sign-in");
      }
      return;
    }
    if (
      desktopOAuthFreshAuthReady
      &&
      auth.account
      && authOpen
      && !auth.passwordRecovery
      && !authPending
      && !authError
    ) {
      setAuthOpen(false);
    } else if (
      auth.configured
      && !auth.loading
      && !auth.account
      && !authOpen
    ) {
      openAccount("sign-in");
    }
  }, [
    auth,
    auth.account,
    auth.configured,
    auth.loading,
    auth.passwordRecovery,
    authError,
    authOpen,
    authPending,
    desktopOAuthFreshAuthReady,
    hasValidOAuthAuthorizationId,
    localizedAuthError,
    oauthAuthorizationId,
    openAccount,
    sitePage,
  ]);

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
    setAuthNotice(null);
    try {
      if (authMode === "reset-update") {
        if (authPassword.length < 8) {
          throw new Error(copy.passwordTooShort);
        }
        if (authPassword !== authPasswordConfirmation) {
          throw new Error(copy.passwordMismatch);
        }
        await auth.updatePassword(authPassword);
        setAuthPassword("");
        setAuthPasswordConfirmation("");
        setAuthMode("sign-in");
        setAuthNotice(copy.passwordUpdated);
      } else if (authMode === "sign-in") {
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
      } else if (authMode === "register") {
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
      } else if (
        authMode === "recovery-sign-in"
        || authMode === "recovery-password"
      ) {
        if (!authCodeSent || !authCode.trim()) {
          throw new Error(copy.recoveryCodeRequired);
        }
        if (authMode === "recovery-password") {
          if (authPassword.length < 8) {
            throw new Error(copy.passwordTooShort);
          }
          if (authPassword !== authPasswordConfirmation) {
            throw new Error(copy.passwordMismatch);
          }
          await auth.verifyRecoveryCode(
            authEmail,
            authCode,
            authPassword,
          );
        } else {
          await auth.verifyRecoveryCode(authEmail, authCode);
        }
      }
      if (hasValidOAuthAuthorizationId) {
        setDesktopOAuthFreshAuthReady(true);
      }
    } catch (reason) {
      setAuthError(localizedAuthError(reason));
    } finally {
      setAuthPending(false);
      if (
        authMode === "sign-in" && captchaProtectionConfigured
      ) {
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
      setAuthNotice(copy.recoveryCodeSent);
    } catch (reason) {
      setAuthError(localizedAuthError(reason));
    } finally {
      setAuthPending(false);
      if (captchaProtectionConfigured) {
        setAuthCaptchaToken(null);
        setAuthCaptchaCycle((current) => current + 1);
      }
    }
  };

  const sendRecoveryCode = async () => {
    if (authPending) return;
    setAuthError(null);
    setAuthNotice(null);
    if (captchaProtectionConfigured && !authCaptchaToken) {
      setAuthError(copy.completeCaptcha);
      return;
    }
    setAuthPending(true);
    try {
      if (authCaptchaToken) {
        await auth.sendRecoveryCode(authEmail, authCaptchaToken);
      } else {
        await auth.sendRecoveryCode(authEmail);
      }
      setAuthCodeSent(true);
      setAuthNotice(copy.recoveryCodeSent);
    } catch (reason) {
      setAuthError(localizedAuthError(reason));
    } finally {
      setAuthPending(false);
      if (captchaProtectionConfigured) {
        setAuthCaptchaToken(null);
        setAuthCaptchaCycle((current) => current + 1);
      }
    }
  };

  const recoveryCodeMode = authMode === "recovery-sign-in"
    || authMode === "recovery-password";
  const authTitle = authMode === "recovery-choice"
    ? copy.recoveryTitle
    : authMode === "recovery-sign-in"
      ? copy.recoverySignInTitle
      : authMode === "recovery-password"
        ? copy.recoveryPasswordTitle
        : authMode === "reset-update"
          ? copy.resetUpdateTitle
          : auth.account
            ? copy.account
            : authMode === "register"
              ? copy.registerTitle
              : copy.authTitle;
  const showEmailField = authMode !== "reset-update"
    && authMode !== "recovery-choice";
  const showPasswordField = authMode === "sign-in"
    || authMode === "register"
    || authMode === "recovery-password"
    || authMode === "reset-update";
  const showPasswordConfirmation = authMode === "register"
    || authMode === "recovery-password"
    || authMode === "reset-update";
  const showVerificationCode = authMode === "register" || recoveryCodeMode;
  const showCaptcha = captchaProtectionConfigured && (
    authMode === "sign-in"
    || authMode === "register"
    || recoveryCodeMode
  );
  const headerNavigation = [
    ["Home", "/"],
    ["Products", "/product/"],
    ["Pricing", "/pricing/"],
    ["Manual", "/manual/"],
    ["Community", "/community/"],
  ] as const;
  const currentNavigationTarget = sitePage === "home"
    ? "/"
    : sitePage === "product"
      ? "/product/"
      : sitePage === "pricing"
        ? "/pricing/"
        : sitePage === "manual"
          ? "/manual/"
          : sitePage === "community"
            ? "/community/"
            : null;
  const accountName = auth.account?.displayName.trim() || copy.account;

  return (
    <div className="dd-site" data-locale={locale} data-page={sitePage}>
      <a className="site-skip-link" href="#main-content">{copy.skip}</a>
      <header className={`site-header${scrolled ? " is-scrolled" : ""}`}>
        <a className="site-brand" href="/" onClick={closeMenu} aria-label="DroneDream">
          <BrandLockup />
        </a>
        <nav
          id="site-navigation"
          className={`site-nav${menuOpen ? " is-open" : ""}`}
          aria-label={copy.navLabel}
        >
          {headerNavigation.map(([label, target]) => (
            <a
              key={target}
              href={target}
              aria-current={target === currentNavigationTarget ? "page" : undefined}
              onClick={closeMenu}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="site-header-actions">
          <div
            ref={accountMenuRef}
            className={`site-account-picker${accountMenuOpen ? " is-open" : ""}`}
          >
            <button
              ref={accountButtonRef}
              type="button"
              className="site-account-button"
              aria-haspopup={auth.account ? "menu" : undefined}
              aria-expanded={auth.account ? accountMenuOpen : undefined}
              aria-controls={auth.account ? "site-account-menu" : undefined}
              onClick={() => {
                setMenuOpen(false);
                if (!auth.account) {
                  openAccount("sign-in");
                  return;
                }
                setAccountMenuOpen((open) => !open);
              }}
            >
              <span className="site-account-avatar" aria-hidden="true">
                {auth.account?.avatarUrl ? (
                  <img src={auth.account.avatarUrl} alt="" />
                ) : (
                  <AccountIcon />
                )}
              </span>
              <span>{auth.account ? accountName : copy.signIn}</span>
              {auth.account ? <DownloadChevronIcon /> : null}
            </button>
            {auth.account && accountMenuOpen ? (
              <div
                id="site-account-menu"
                className="site-account-menu"
                role="menu"
                aria-label={copy.account}
              >
                <div className="site-account-menu-profile">
                  <strong>{accountName}</strong>
                  <span>{auth.account.email}</span>
                </div>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => openAccount("sign-in")}
                >
                  {copy.account}
                </button>
                <button type="button" role="menuitem" onClick={openConsole}>
                  {copy.openConsole}
                </button>
                {organizationAccess?.authorized ? (
                  <a href="/organization/" role="menuitem" onClick={closeMenu}>
                    {copy.organization}
                  </a>
                ) : null}
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setAccountMenuOpen(false);
                    setPolicyOpen(true);
                  }}
                >
                  {copy.policies}
                </button>
                <button
                  type="button"
                  role="menuitem"
                  disabled={authPending}
                  onClick={() => {
                    setAccountMenuOpen(false);
                    setAuthPending(true);
                    void auth.signOut()
                      .catch((reason: unknown) => setAuthError(localizedAuthError(reason)))
                      .finally(() => setAuthPending(false));
                  }}
                >
                  {copy.signOut}
                </button>
              </div>
            ) : null}
          </div>
          <button
            ref={menuButtonRef}
            type="button"
            className="site-menu-button"
            aria-label={menuOpen ? copy.closeMenu : copy.menu}
            aria-expanded={menuOpen}
            aria-controls="site-navigation"
            onClick={() => {
              setMenuOpen((open) => !open);
            }}
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
          <ProductPage availability={editionAvailability} locale={locale} release={release} />
        ) : sitePage === "pricing" ? (
          <PricingPage
            locale={locale}
            authenticated={Boolean(auth.account)}
            onRequireAccount={() => openAccount("register")}
          />
        ) : sitePage === "organization" ? (
          <OrganizationPage locale={locale} accountId={auth.account?.id ?? null} />
        ) : sitePage === "community" ? (
          <CommunityPage
            locale={locale}
            account={auth.account}
            onRequireAccount={() => openAccount("sign-in")}
          />
        ) : sitePage === "oauth-consent" && (
          !hasValidOAuthAuthorizationId
          ||
          (desktopOAuthFreshAuthReady && auth.account && !authPending && !authError)
          || (!auth.configured && !auth.loading)
        ) ? (
          <OAuthConsentPage
            locale={locale}
            account={auth.account}
            authConfigured={auth.configured}
            authLoading={auth.loading}
            onRequireSignIn={() => openAccount("sign-in")}
            onRequireRegistration={() => openAccount("register")}
            onSwitchAccount={() => {
              setAuthPending(true);
              setAuthError(null);
              void auth.signOut()
                .then(() => openAccount("sign-in"))
                .catch((reason: unknown) => {
                  setAuthError(localizedAuthError(reason));
                  setAuthOpen(true);
                })
                .finally(() => setAuthPending(false));
            }}
          />
        ) : sitePage === "oauth-consent" && desktopOAuthFreshAuthReady ? (
          <div className="site-oauth-auth-stage" aria-hidden="true" />
        ) : (
          <HomeExperience release={release} />
        )}
      </main>

      {policyOpen ? (
        <Suspense
          fallback={(
            <div className="site-policy-backdrop" aria-hidden="true">
              <div className="site-policy-dialog site-policy-loading">Loading policies…</div>
            </div>
          )}
        >
          <PolicyDialog onClose={closePolicies} />
        </Suspense>
      ) : null}

      {authOpen ? (
        <div
          className={`site-auth-backdrop${oauthAuthPage ? " is-oauth-page" : ""}`}
          onMouseDown={(event) => {
            if (
              event.target === event.currentTarget
              && authMode !== "reset-update"
              && !oauthAuthPage
            ) {
              setAuthOpen(false);
            }
          }}
        >
          <section
            ref={authDialogRef}
            className={`site-auth-dialog${oauthAuthPage ? " is-oauth-page" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="site-auth-title"
          >
            <header className="site-auth-header">
              <div className="site-auth-brand" role="img" aria-label="DroneDream">
                <BrandLockup />
              </div>
              <div className="site-auth-header-actions">
                {!auth.account && authMode !== "reset-update" ? (
                  <button
                    type="button"
                    className="site-auth-mode-switch"
                    disabled={authPending}
                    onClick={() => openAccount(
                      authMode === "sign-in" ? "register" : "sign-in",
                    )}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M15.5 19.25v-1.5a3.5 3.5 0 0 0-3.5-3.5H7a3.5 3.5 0 0 0-3.5 3.5v1.5M9.5 10.25a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5ZM18.25 7v6.5M15 10.25h6.5" />
                    </svg>
                    <span>
                      {authMode === "sign-in" ? copy.registerNow : copy.backToSignIn}
                    </span>
                  </button>
                ) : null}
                {authMode !== "reset-update" && !oauthAuthPage ? (
                <button
                  ref={authCloseRef}
                  type="button"
                  className="site-auth-close"
                  aria-label={copy.closeAuth}
                  onClick={() => setAuthOpen(false)}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="m7 7 10 10M17 7 7 17" />
                  </svg>
                </button>
              ) : null}
              </div>
            </header>
            <h2 id="site-auth-title">{authTitle}</h2>
            {auth.account
              && authMode !== "reset-update"
              && (!hasValidOAuthAuthorizationId || desktopOAuthFreshAuthReady) ? (
              <div className="site-auth-account">
                <AccountIcon />
                <strong>{auth.account.displayName}</strong>
                <span>{auth.account.email}</span>
                {accountPlan ? (
                  <span className="site-auth-plan">
                    {copy.accountPlan}: {accountPlan.billingScope === "business" ? `${copy.businessPlan} ` : ""}{accountPlan.name}
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
                        setAuthError(localizedAuthError(reason));
                      })
                      .finally(() => setAuthPending(false));
                  }}
                >
                  {copy.signOut}
                </button>
              </div>
            ) : authMode === "recovery-choice" ? (
              <div className="site-auth-recovery-options">
                <button
                  type="button"
                  disabled={authPending}
                  onClick={() => openAccount("recovery-sign-in")}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3.5 6.25 12 12l8.5-5.75M4.75 4.5h14.5A1.75 1.75 0 0 1 21 6.25v11.5a1.75 1.75 0 0 1-1.75 1.75H4.75A1.75 1.75 0 0 1 3 17.75V6.25A1.75 1.75 0 0 1 4.75 4.5Z" />
                  </svg>
                  <span>{copy.recoveryCodeSignIn}</span>
                </button>
                <button
                  type="button"
                  disabled={authPending}
                  onClick={() => openAccount("recovery-password")}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M14.25 8.75a4.5 4.5 0 1 0-3.73 4.43L13 15.66V18h2.34v2.34H18V17.7l-4.82-4.82a4.5 4.5 0 0 0 1.07-4.13Z" />
                    <circle cx="9.75" cy="8.75" r="1" />
                  </svg>
                  <span>{copy.recoveryPassword}</span>
                </button>
              </div>
            ) : (
              <>
                {authMode === "reset-update" ? (
                  <p className="site-auth-guidance">{copy.resetUpdateBody}</p>
                ) : null}
                <form className="site-auth-form" onSubmit={(event) => void submitAuth(event)}>
                  {showEmailField ? (
                    <label>
                      <span>{copy.email}</span>
                      <input
                        type="email"
                        required
                        autoComplete="email"
                        value={authEmail}
                        disabled={
                          authPending
                          || (showVerificationCode && authCodeSent)
                        }
                        onChange={(event) => setAuthEmail(event.target.value)}
                      />
                    </label>
                  ) : null}
                  {showPasswordField ? (
                    <label>
                      <span>{copy.password}</span>
                      <input
                        type="password"
                        required
                        minLength={8}
                        autoComplete={
                          authMode === "sign-in"
                            ? "current-password"
                            : "new-password"
                        }
                        value={authPassword}
                        placeholder={copy.passwordPlaceholder}
                        disabled={authPending}
                        onChange={(event) => setAuthPassword(event.target.value)}
                      />
                    </label>
                  ) : null}
                  {showPasswordConfirmation ? (
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
                  ) : null}
                  {showVerificationCode ? (
                    <div className="site-auth-code-field">
                      <label htmlFor="site-verification-code">
                        <span>{copy.code}</span>
                      </label>
                      <div className="site-auth-code-row">
                        <input
                          id="site-verification-code"
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
                          onClick={() => void (
                            authMode === "register"
                              ? sendRegistrationCode()
                              : sendRecoveryCode()
                          )}
                        >
                          {authCodeSent ? copy.resendCode : copy.sendCode}
                        </button>
                      </div>
                    </div>
                  ) : null}
                  {showCaptcha ? (
                    <AuthCaptcha
                      key={authCaptchaCycle}
                      siteKey={turnstileSiteKey}
                      locale={locale}
                      onTokenChange={setAuthCaptchaToken}
                    />
                  ) : null}
                  <button type="submit" disabled={authPending || auth.loading}>
                    {authMode === "register"
                      ? copy.createAccount
                      : authMode === "reset-update"
                        ? copy.updatePassword
                        : authMode === "recovery-sign-in"
                          ? copy.signInWithCode
                          : authMode === "recovery-password"
                            ? copy.resetAndSignIn
                            : copy.signInAction}
                  </button>
                </form>
                {authMode === "sign-in" ? (
                  <div className="site-auth-link-row">
                    <button
                      type="button"
                      className="site-auth-text-button"
                      disabled={authPending}
                      onClick={() => openAccount("recovery-choice")}
                    >
                      {copy.forgotPassword}
                    </button>
                  </div>
                ) : null}
              </>
            )}
            {authNotice ? <div className="site-auth-notice" role="status">{authNotice}</div> : null}
            {authError ? <div className="site-auth-error" role="alert">{authError}</div> : null}
          </section>
        </div>
      ) : null}

    </div>
  );
}
