import type { BrandEditionId } from "../../brand/edition-brand.generated";
import type { InterfaceLocale } from "../../i18n/I18nProvider";

export type AssistantTaskType =
  | "control_tuning"
  | "mission_autonomy"
  | "vehicle_modeling"
  | "simulation_experiment"
  | "cross_edition_workflow"
  | "hardware_validation"
  | "calibration"
  | "sim_to_real"
  | "real_to_sim"
  | "field_task";

export interface AssistantTaskOption {
  id: AssistantTaskType;
  label: string;
  description: string;
}

const TASKS_BY_EDITION: Readonly<Record<BrandEditionId, readonly AssistantTaskType[]>> = {
  universal: [
    "control_tuning",
    "mission_autonomy",
    "vehicle_modeling",
    "simulation_experiment",
    "cross_edition_workflow",
  ],
  sim: ["control_tuning", "mission_autonomy", "simulation_experiment"],
  lab: [
    "control_tuning",
    "mission_autonomy",
    "simulation_experiment",
    "hardware_validation",
    "calibration",
    "sim_to_real",
    "real_to_sim",
  ],
  field: ["control_tuning", "mission_autonomy", "field_task"],
  autonomy: ["mission_autonomy", "vehicle_modeling", "simulation_experiment"],
};

const EN: Record<AssistantTaskType, Omit<AssistantTaskOption, "id">> = {
  control_tuning: { label: "Control tuning", description: "Tune PX4 parameters against bounded evidence." },
  mission_autonomy: { label: "Autonomous mission", description: "Plan, simulate, monitor, and safely replan a route." },
  vehicle_modeling: { label: "Vehicle modeling", description: "Create an editable airframe and component draft." },
  simulation_experiment: { label: "Simulation study", description: "Build a repeatable PX4 and Gazebo experiment." },
  cross_edition_workflow: { label: "Cross-edition workflow", description: "Connect SIM, LAB, and FIELD with qualification gates." },
  hardware_validation: { label: "Hardware validation", description: "Prepare a bounded bench or captured-vehicle validation." },
  calibration: { label: "Calibration", description: "Diagnose mismatch and prepare a traceable calibration flow." },
  sim_to_real: { label: "Sim-to-Real", description: "Qualify a simulation result for hardware handoff." },
  real_to_sim: { label: "Real-to-Sim", description: "Use captured evidence to update the simulation model." },
  field_task: { label: "Field task", description: "Prepare a reviewed task plan with abort and rollback limits." },
};

const ZH: Record<AssistantTaskType, Omit<AssistantTaskOption, "id">> = {
  control_tuning: { label: "控制参数调优", description: "依据受约束证据调优 PX4 参数。" },
  mission_autonomy: { label: "自主飞行任务", description: "规划、仿真、监控并安全地实时重规划航线。" },
  vehicle_modeling: { label: "无人机建模", description: "创建可继续编辑的机架与组件模型草稿。" },
  simulation_experiment: { label: "仿真实验", description: "创建可复现的 PX4 与 Gazebo 实验。" },
  cross_edition_workflow: { label: "跨版本工作流", description: "通过资格门连接 SIM、LAB 与 FIELD。" },
  hardware_validation: { label: "真机验证", description: "准备受约束的台架或实测数据验证流程。" },
  calibration: { label: "标定校准", description: "诊断偏差并建立可追溯校准流程。" },
  sim_to_real: { label: "仿真到真机", description: "将仿真结果经过资格验证后移交真机。" },
  real_to_sim: { label: "真机到仿真", description: "用采集证据更新仿真模型。" },
  field_task: { label: "现场任务", description: "准备包含中止与回滚边界的现场计划。" },
};

export function assistantTaskOptions(
  edition: BrandEditionId,
  locale: InterfaceLocale,
): AssistantTaskOption[] {
  const copy = locale === "zh-CN" || locale === "zh-TW" ? ZH : EN;
  return TASKS_BY_EDITION[edition].map((id) => ({ id, ...copy[id] }));
}

export function assistantTaskIsAllowed(
  edition: BrandEditionId,
  taskType: AssistantTaskType,
): boolean {
  return TASKS_BY_EDITION[edition].includes(taskType);
}

const AUTONOMY_HANDOFF_KEY = "dronedream.tuning-chat.autonomy-handoff.v1";

export function storeAutonomyHandoff(intent: string): void {
  sessionStorage.setItem(AUTONOMY_HANDOFF_KEY, intent.trim().slice(0, 2_000));
}

export function consumeAutonomyHandoff(): string | null {
  const intent = sessionStorage.getItem(AUTONOMY_HANDOFF_KEY)?.trim() ?? "";
  sessionStorage.removeItem(AUTONOMY_HANDOFF_KEY);
  return intent || null;
}

export function loadAutonomyHandoff(): string | null {
  const intent = sessionStorage.getItem(AUTONOMY_HANDOFF_KEY)?.trim() ?? "";
  return intent || null;
}

export const assistantTaskTypesByEdition = TASKS_BY_EDITION;
