import {
  createDefaultDistributionSelection,
  normalizeDistributionSelection,
  type DistributionSelectionDraft,
} from "../../features/distribution/installationSelection";
import type { RegionId } from "../../features/distribution/catalog";

export type SimLocale = "en" | "zh-CN";

export const SIM_EDITION = {
  editionId: "sim",
  productName: "DroneDream \u00b7 SIM",
  displayVersion: "1.0.0",
  artifactFileName: "DroneDream-Sim-1.0.0.exe",
  releaseState: "internal-preview",
  validationState: "planned-not-validated",
  allowedCapabilities: [
    "qualification.simulation.issue",
    "simulation.execute",
    "simulation.parameter.write",
    "simulation.vehicle.arm",
    "updater.module.apply",
    "vehicle-pack.install",
  ],
  forbiddenCapabilities: [
    "external.qgroundcontrol.launch",
    "hardware.arm",
    "hardware.discover",
    "hardware.emergency-stop",
    "hardware.flight",
    "hardware.hitl.execute",
    "hardware.parameter.read",
    "hardware.parameter.write",
    "hardware.preflight.execute",
    "qualification.trusted.consume",
  ],
  visibleSurfaces: [
    "autonomous-optimization",
    "model-candidate-planning",
    "harness-evidence",
    "simulation",
    "px4-sitl",
    "gazebo",
    "sim-vehicle-packs",
    "runtime-base-external",
    "engine-pack-external",
  ],
} as const;

const ALLOWED_CAPABILITIES = new Set<string>(SIM_EDITION.allowedCapabilities);

export function simCapabilityDecision(capability: string): "allow" | "deny" {
  return ALLOWED_CAPABILITIES.has(capability) ? "allow" : "deny";
}

export function assertSimCapability(capability: string): void {
  if (simCapabilityDecision(capability) === "deny") {
    throw new Error(`${SIM_EDITION.productName} denies capability: ${capability}`);
  }
}

export function lockDistributionSelectionToSim(
  selection: DistributionSelectionDraft,
): DistributionSelectionDraft {
  return normalizeDistributionSelection({
    ...selection,
    editionId: "sim",
    controllerKey: null,
    optionalModules: [],
  });
}

export function defaultSimDistributionSelection(
  region: RegionId,
): DistributionSelectionDraft {
  return lockDistributionSelectionToSim(createDefaultDistributionSelection(region));
}

export const SIM_COPY = {
  en: {
    editionBadge: "SIM EDITION",
    navOverview: "Sim Overview",
    workspaceTitle: "Simulation workspace",
    overviewEyebrow: "Simulation-only internal preview",
    overviewTitle: "DroneDream \u00b7 SIM",
    overviewBody:
      "Run autonomous Model + Harness parameter optimization across repeatable PX4 SITL and Gazebo experiments. This edition has no physical-aircraft control path.",
    loopKicker: "Autonomous optimization",
    loopTitle: "Model reasoning, Harness evidence",
    loopBody:
      "The Model chooses bounded tools, proposes candidates, analyzes feedback, and adapts the next strategy. The Harness executes reproducible simulations, enforces budgets and constraints, classifies failures, and controls qualification and holdout.",
    startOptimization: "Start optimization job",
    loop: {
      objective: {
        title: "Objective and constraints",
        body: "Freeze metrics, parameter domains, disturbance cases, budgets, and stop rules.",
      },
      model: {
        title: "Model strategy",
        body: "Choose proposal tools and form a bounded candidate hypothesis from prior evidence.",
      },
      harness: {
        title: "Harness execution",
        body: "Validate every value, then run deterministic, budgeted simulation trials.",
      },
      telemetry: {
        title: "Telemetry and diagnosis",
        body: "Collect logs and metrics, classify failures, and return structured feedback.",
      },
      compare: {
        title: "Candidate comparison",
        body: "Compare objectives, constraints, robustness, and evidence across candidates.",
      },
      qualify: {
        title: "Qualification and holdout",
        body: "Seal independent simulation evidence before a candidate can be exported.",
      },
    },
    setupPreview: "Setup preview",
    setupBody:
      "DroneDream Sim uses an external Runtime Base and Engine Pack. The app installer does not embed either dependency.",
    openSetup: "Open setup preview",
    capabilityTitle: "Simulation workspace",
    dependencyTitle: "External dependencies",
    boundaryTitle: "Edition boundary",
    boundaryBody:
      "Hardware discovery, parameter read/write, arming, flight, HITL, Lab, and Field are unavailable and denied below the interface.",
    candidateWarning:
      "Simulation candidates are evidence-backed hypotheses, not parameters approved for physical aircraft.",
    settingsTitle: "Sim edition",
    settingsBody:
      "The edition is fixed to simulation. There is no Lab or Field mode switch in this build.",
    fixedMode: "Fixed mode",
    previewStatus: "Internal preview · not validated for promotion",
    blockedTitle: "Unavailable in DroneDream Sim",
    blockedBody:
      "That route belongs to hardware, HITL, Lab, or Field workflows and is not part of this edition.",
    items: {
      simulation: "Simulation",
      px4: "PX4 SITL",
      gazebo: "Gazebo",
      vehiclePacks: "Sim Vehicle Packs",
      runtime: "Runtime Base",
      engine: "Engine Pack",
    },
    external: "External",
  },
  "zh-CN": {
    editionBadge: "纯仿真版",
    navOverview: "Sim 概览",
    workspaceTitle: "纯仿真工作区",
    overviewEyebrow: "纯仿真内测预览",
    overviewTitle: "DroneDream \u00b7 SIM",
    overviewBody:
      "通过 Model + Harness 在可重复的 PX4 SITL 与 Gazebo 实验中自主搜索和优化参数。本版本不存在任何真机控制路径。",
    loopKicker: "自主参数调优",
    loopTitle: "Model 推理，Harness 持证",
    loopBody:
      "Model 在受限范围内选择工具、提出候选、分析反馈并调整下一步策略；Harness 负责可复现实验、预算与约束、失败分类、资格判定和独立 holdout。",
    startOptimization: "开始自主调优",
    loop: {
      objective: {
        title: "目标与约束",
        body: "冻结指标、参数域、扰动场景、预算与停止规则。",
      },
      model: {
        title: "Model 策略",
        body: "依据历史证据选择候选工具，并提出受约束的参数假设。",
      },
      harness: {
        title: "Harness 执行",
        body: "逐值验证后，运行确定性且受预算约束的仿真实验。",
      },
      telemetry: {
        title: "遥测与诊断",
        body: "采集日志和指标，分类失败，并返回结构化反馈。",
      },
      compare: {
        title: "候选比较",
        body: "比较候选的目标、约束、鲁棒性和证据完整度。",
      },
      qualify: {
        title: "资格与 Holdout",
        body: "通过独立仿真验证并封存证据后，候选才可导出。",
      },
    },
    setupPreview: "安装设置预览",
    setupBody:
      "DroneDream Sim 依赖外置 Runtime Base 与 Engine Pack；应用安装包不会内嵌这两项依赖。",
    openSetup: "打开设置预览",
    capabilityTitle: "仿真工作区",
    dependencyTitle: "外置依赖",
    boundaryTitle: "版本能力边界",
    boundaryBody:
      "硬件发现、参数读写、解锁、飞行、HITL、Lab 与 Field 均不可用，并在界面以下继续强制拒绝。",
    candidateWarning: "仿真候选只是有证据的参数假设，不代表已经获准用于真机。",
    settingsTitle: "Sim 版本",
    settingsBody: "本版本固定为纯仿真，不提供 Lab 或 Field 模式切换。",
    fixedMode: "固定模式",
    previewStatus: "内测预览 · 尚未达到发布验证条件",
    blockedTitle: "DroneDream Sim 不提供此功能",
    blockedBody: "该路径属于硬件、HITL、Lab 或 Field 工作流，不在本版本能力范围内。",
    items: {
      simulation: "Simulation 仿真",
      px4: "PX4 SITL",
      gazebo: "Gazebo",
      vehiclePacks: "Sim 仿真机型包",
      runtime: "Runtime Base",
      engine: "Engine Pack",
    },
    external: "外置",
  },
} as const;

export function simCopy(locale: SimLocale) {
  return SIM_COPY[locale];
}
