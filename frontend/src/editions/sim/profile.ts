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
      "Tune and compare PX4 SITL runs in Gazebo with versioned simulation vehicle profiles. This edition has no physical-aircraft control path.",
    setupPreview: "Setup preview",
    setupBody:
      "DroneDream Sim uses an external Runtime Base and Engine Pack. The app installer does not embed either dependency.",
    openSetup: "Open setup preview",
    capabilityTitle: "Simulation workspace",
    dependencyTitle: "External dependencies",
    boundaryTitle: "Edition boundary",
    boundaryBody:
      "Hardware discovery, parameter read/write, arming, flight, HITL, Lab, and Field are unavailable and denied below the interface.",
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
      "使用版本化仿真机型配置，在 Gazebo 中调优并比较 PX4 SITL 运行。本版本不存在任何真机控制路径。",
    setupPreview: "安装设置预览",
    setupBody:
      "DroneDream Sim 依赖外置 Runtime Base 与 Engine Pack；应用安装包不会内嵌这两项依赖。",
    openSetup: "打开设置预览",
    capabilityTitle: "仿真工作区",
    dependencyTitle: "外置依赖",
    boundaryTitle: "版本能力边界",
    boundaryBody:
      "硬件发现、参数读写、解锁、飞行、HITL、Lab 与 Field 均不可用，并在界面以下继续强制拒绝。",
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
