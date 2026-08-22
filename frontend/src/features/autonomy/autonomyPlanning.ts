import type { BrandEditionId } from "../../brand/edition-brand.generated";
import { apiClient } from "../../api/client";
import { orchestrateAssistantTurn } from "../experiment/assistantOrchestration";
import { activeAssistantTenantContext } from "../experiment/workspaceRegistry";
import type { ManagedModelCatalogEntry } from "../settings/cloudModelAccess";
import {
  autonomyAircraftRadiusM,
  isAutonomyAircraftAssetQualified,
  type AutonomyMapPack,
  type AutonomyMissionPlanSnapshot,
  type AutonomyWorkspaceState,
} from "./workspaceStore";
import {
  autonomyAssetBlockerMessage,
  autonomyCanonicalSha256,
  autonomyHarnessRequest,
  autonomyModelContext,
  autonomyPlannerBindingIssues,
  localAutonomyHarnessInspection,
  parseAutonomyPlannerArtifact,
  type AutonomyPlannerArtifact,
} from "./missionHarness";
import {
  createLocalAutonomyPreview,
  type AutonomyMissionId,
} from "./missionAutonomy";
import type {
  AutonomyCompileAssetContext,
  AutonomyCompileRequest,
  AutonomyCompileResponse,
  AutonomyHarnessInspectResponse,
} from "../../types/api";
import {
  inspectAgentCoreAssetBindings,
  isAgentCoreUnavailable,
  planWithAgentCore,
} from "./agentCorePlanning";
import type { AgentCoreMissionPrepareSummary } from "./agentCore";

export type AutonomyPlanningModel =
  | {
      accessMode: "platform";
      provider: ManagedModelCatalogEntry["provider"];
      model: string;
    }
  | {
      accessMode: "byok";
      provider: string;
      model: string;
      agentCoreProfileId?: string | null;
      agentCoreSelectionId?: string | null;
    };

export interface AutonomyPlanningInput {
  edition: BrandEditionId;
  workspace: AutonomyWorkspaceState;
  intent: string;
  instruction: string;
  conversationId: string;
  turnId: string;
  chinese: boolean;
  selectedModel: AutonomyPlanningModel;
  accountId: string | null;
  publicDemo: boolean;
  requestPurpose: "initial_plan" | "runtime_replan";
  runtimeContext?: Record<string, unknown> | null;
  attachments?: File[];
  inputChannel?: "text" | "voice" | "camera" | "api" | "webhook" | "scheduled";
  transcriptSource?: "web-speech" | "audio-attachment" | null;
}

export interface AutonomyPlanningResult {
  planningBrief: string;
  planningRunId: string | null;
  planningArtifactSha256: string | null;
  plannerArtifact: AutonomyPlannerArtifact | null;
  harnessInspection: AutonomyHarnessInspectResponse;
  compileRequest: AutonomyCompileRequest | null;
  compileResult: AutonomyCompileResponse | null;
  compiledPlan: AutonomyMissionPlanSnapshot | null;
}

export function requiresAgentCoreRuntime(
  _edition: BrandEditionId,
  publicDemo: boolean,
): boolean {
  return !publicDemo;
}

export function autonomyExecutionAuthority(
  edition: BrandEditionId,
  source: AutonomyMissionPlanSnapshot["source"] | null | undefined,
): "agent-core" | "public-runtime" | "blocked" {
  if (edition === "autonomy") return source === "agent-core" ? "agent-core" : "blocked";
  return source === "agent-core" ? "agent-core" : "public-runtime";
}

export function autonomyMapPackQualified(mapPack: AutonomyMapPack): boolean {
  const runtimeContract = mapPack.agentCoreRuntimeContract;
  const agentCoreQualificationValid = typeof mapPack.agentCoreAssetId === "string"
    && mapPack.agentCoreAssetId.length >= 3
    && typeof mapPack.agentCoreContentSha256 === "string"
    && mapPack.contentHash === mapPack.agentCoreContentSha256
    && typeof mapPack.qualificationReceiptId === "string"
    && /^asset-qualification-[0-9a-f]{24}$/u.test(mapPack.qualificationReceiptId)
    && runtimeContract?.assetId === mapPack.agentCoreAssetId
    && runtimeContract.contentSha256 === mapPack.agentCoreContentSha256;
  return agentCoreQualificationValid
    && mapPack.status === "qualified"
    && mapPack.calibrated
    && mapPack.sourceFiles.length > 0
    && mapPack.sourceFiles.every((file) => file.admission === "admitted");
}

export function autonomyAssetPairQualified(workspace: AutonomyWorkspaceState): boolean {
  return isAutonomyAircraftAssetQualified(workspace.aircraft)
    && autonomyMapPackQualified(workspace.mapPack)
    && workspace.aircraft.qualificationReceiptId === workspace.mapPack.qualificationReceiptId;
}

function inferredSceneId(_intent: string, mapPack: AutonomyMapPack): string {
  return mapPack.compilerSceneId || "school-campus-v1";
}

export function compileRequestForWorkspace(
  edition: BrandEditionId,
  workspace: AutonomyWorkspaceState,
  intent: string,
  locale: AutonomyCompileRequest["locale"],
  assetContext: AutonomyCompileAssetContext,
): AutonomyCompileRequest {
  const visualSensors = workspace.aircraft.sensors.some((sensor) => (
    sensor === "rgb"
    || sensor === "depth"
    || sensor === "stereo"
    || sensor === "thermal"
    || sensor === "vio"
  ));
  const mapReady = autonomyMapPackQualified(workspace.mapPack);
  return {
    edition,
    locale,
    execution_target: "simulation",
    natural_language: intent,
    scene_id: inferredSceneId(intent, workspace.mapPack),
    perception_mode: visualSensors && mapReady ? "fusion" : visualSensors ? "vision" : "map",
    vehicle: {
      dry_mass_kg: workspace.aircraft.dryMassKg,
      launch_payload_kg: 0,
      pickup_payload_kg: workspace.aircraft.maximumPickupPayloadKg,
      max_takeoff_mass_kg: workspace.aircraft.maximumTakeoffMassKg,
      max_total_thrust_n: workspace.aircraft.maximumThrustN,
      radius_m: autonomyAircraftRadiusM(workspace.aircraft),
      max_speed_mps: workspace.aircraft.maximumSpeedMps,
      max_acceleration_mps2: workspace.aircraft.maximumAccelerationMps2,
      reserve_battery_percent: workspace.aircraft.reserveBatteryPercent,
    },
    evidence: {
      simulation_qualified: false,
      signed_vehicle_pack_id: null,
      operator_confirmed: false,
      localization_ready: false,
      link_ready: false,
      geofence_ready: false,
      battery_ready: false,
    },
    asset_context: assetContext,
  };
}

function missionIdForScene(sceneId: string, intent = ""): AutonomyMissionId {
  if (sceneId === "forest-gate-inspection") return "gates";
  if (sceneId === "service-corridor-dock") return "narrow";
  const normalized = intent.toLocaleLowerCase();
  if (/gate|圆门|圆环|穿门/u.test(normalized)) return "gates";
  if (/narrow|dock|走廊|corridor|停靠|狭窄|楼梯/u.test(normalized)) return "narrow";
  return "coffee";
}

export function missionPlanSnapshot(
  response: AutonomyCompileResponse,
  workspace: AutonomyWorkspaceState,
  source: AutonomyMissionPlanSnapshot["source"],
  plannerBinding: AutonomyCompileAssetContext["planner_binding"],
): AutonomyMissionPlanSnapshot {
  const aircraftReady = isAutonomyAircraftAssetQualified(workspace.aircraft);
  const mapReady = autonomyMapPackQualified(workspace.mapPack);
  const chinese = response.contract.locale === "zh-CN";
  const assetIssues: AutonomyMissionPlanSnapshot["issues"] = [
    ...(!aircraftReady ? [{
      code: "asset.aircraft.not-qualified",
      severity: "error" as const,
      message: chinese
        ? "所选机型包未通过本任务专属的飞行包络检查。"
        : "The selected Vehicle Pack does not pass its task-specific flight-envelope checks.",
    }] : []),
    ...(!mapReady ? [{
      code: "asset.map.not-qualified",
      severity: "error" as const,
      message: chinese
        ? "所选地图包尚未完成标定，也未绑定已编译的三维场景。"
        : "The selected Map Pack is not calibrated and bound to a compiled three-dimensional scene.",
    }] : []),
  ];
  const pairReady = autonomyAssetPairQualified(workspace);
  const assetsReady = aircraftReady && mapReady && pairReady;
  if (aircraftReady && mapReady && !pairReady) {
    assetIssues.push({
      code: "asset.pair.qualification-mismatch",
      severity: "error",
      message: chinese
        ? "所选地图与无人机不是同一次成对真实仿真认证的资产。"
        : "The selected map and aircraft do not share the same paired real-simulation qualification.",
    });
  }
  const authoritative = source === "backend";
  return {
    schemaVersion: 1,
    source,
    contractId: response.contract.contract_id,
    sceneId: response.scene.id,
    sceneName: response.scene.name,
    feasible: response.feasible && assetsReady && authoritative,
    readiness: assetsReady && authoritative ? response.execution_policy.readiness : "denied",
    canExecute: assetsReady && authoritative && response.execution_policy.can_execute,
    perceptionMode: response.contract.perception_mode,
    plannerBinding,
    steps: response.contract.steps.map((step) => ({
      order: step.order,
      action: step.action,
      label: step.label,
      payloadDeltaKg: step.payload_delta_kg,
    })),
    taskGraph: response.contract.task_graph,
    issues: [...assetIssues, ...response.issues],
    metrics: {
      routeLengthM: response.metrics.route_length_m,
      verticalTravelM: response.metrics.vertical_travel_m,
      estimatedDurationS: response.metrics.estimated_duration_s,
      minimumClearanceM: response.metrics.minimum_clearance_m,
      launchMassKg: response.metrics.launch_mass_kg,
      postPickupMassKg: response.metrics.post_pickup_mass_kg,
      postPickupThrustToWeight: response.metrics.post_pickup_thrust_to_weight,
      brakingDistanceM: response.metrics.braking_distance_m,
    },
    immutableSafetyRules: response.contract.immutable_safety_rules,
    compiledAt: new Date().toISOString(),
  };
}

function agentCoreMissionPlanSnapshot(
  summary: AgentCoreMissionPrepareSummary,
  plannerBinding: NonNullable<AutonomyCompileAssetContext["planner_binding"]>,
): AutonomyMissionPlanSnapshot {
  const plan = summary.mission_plan;
  if (
    plan.schema_version !== "dronedream.agent-core-mission-plan.v1"
    || plan.source !== "agent-core"
    || plan.contract_id !== summary.contract_id
    || !/^[0-9a-f]{64}$/u.test(plan.prepared_mission_sha256)
    || !/^[0-9a-f]{64}$/u.test(plan.asset_bindings.map_content_sha256)
    || !/^[0-9a-f]{64}$/u.test(plan.asset_bindings.vehicle_content_sha256)
    || plan.task_graph.schema_version !== "dronedream.autonomy.task-graph.v1"
    || !plan.task_graph.nodes.length
  ) {
    throw new Error("AGENT Core mission plan projection is invalid.");
  }
  const taskIds = new Set(plan.task_graph.nodes.map((node) => node.task_id));
  if (
    taskIds.size !== plan.task_graph.nodes.length
    || plan.task_graph.nodes.some((node) => node.depends_on.some((dependency) => !taskIds.has(dependency)))
  ) {
    throw new Error("AGENT Core mission task graph binding is invalid.");
  }
  return {
    schemaVersion: 1,
    source: "agent-core",
    contractId: plan.contract_id,
    sceneId: plan.scene_id,
    sceneName: plan.scene_name,
    feasible: plan.feasible,
    readiness: plan.readiness,
    canExecute: plan.can_execute && plan.feasible,
    perceptionMode: plan.perception_mode,
    plannerBinding,
    steps: plan.steps.map((step) => ({
      order: step.order,
      action: step.action,
      label: step.label,
      payloadDeltaKg: step.payload_delta_kg,
    })),
    taskGraph: plan.task_graph,
    issues: plan.issues,
    metrics: {
      routeLengthM: plan.metrics.route_length_m,
      verticalTravelM: plan.metrics.vertical_travel_m,
      estimatedDurationS: plan.metrics.estimated_duration_s,
      minimumClearanceM: plan.metrics.minimum_clearance_m,
      launchMassKg: plan.metrics.launch_mass_kg,
      postPickupMassKg: plan.metrics.post_pickup_mass_kg,
      postPickupThrustToWeight: plan.metrics.post_pickup_thrust_to_weight,
      brakingDistanceM: plan.metrics.braking_distance_m,
    },
    immutableSafetyRules: plan.immutable_safety_rules,
    compiledAt: new Date().toISOString(),
  };
}

export async function planAutonomyMission(
  input: AutonomyPlanningInput,
): Promise<AutonomyPlanningResult> {
  const harnessRequest = autonomyHarnessRequest(input.edition, input.workspace, input.intent);
  let harnessInspection = input.publicDemo
    ? await localAutonomyHarnessInspection(harnessRequest)
    : await inspectAgentCoreAssetBindings(harnessRequest, input.workspace);
  let planningBrief = "";
  let planningRunId: string | null = input.conversationId;
  let planningArtifactSha256: string | null = null;
  let plannerArtifact: AutonomyPlannerArtifact | null = null;

  // AGENT owns a hash-bound local planning and execution authority. Imported
  // assets qualified by that Core must never be reconstructed from the public
  // shell's bundled School Map/My Drone defaults. Try the Core first and, when
  // present, return its PreparedMission projection without a second compiler.
  if (requiresAgentCoreRuntime(input.edition, input.publicDemo)) {
    try {
      const coreSummary = await planWithAgentCore({
        edition: input.edition,
        accountId: input.accountId,
        conversationId: input.conversationId,
        instruction: input.instruction,
        locale: input.chinese ? "zh-CN" : "en-US",
        accessMode: input.selectedModel.accessMode,
        provider: input.selectedModel.provider,
        model: input.selectedModel.model,
        agentCoreProfileId: input.selectedModel.accessMode === "byok"
          ? input.selectedModel.agentCoreProfileId ?? null
          : null,
        agentCoreSelectionId: input.selectedModel.accessMode === "byok"
          ? input.selectedModel.agentCoreSelectionId ?? null
          : null,
        workspace: input.workspace,
        harnessContextSha256: harnessInspection.context_sha256,
        requestPurpose: input.requestPurpose,
        runtimeContext: input.runtimeContext,
        attachments: input.attachments,
        inputChannel: input.inputChannel,
        transcriptSource: input.transcriptSource,
      });
      plannerArtifact = parseAutonomyPlannerArtifact(coreSummary.integration_artifact);
      if (!plannerArtifact) throw new Error("AGENT Core returned an invalid planner artifact.");
      const localArtifactSha256 = await autonomyCanonicalSha256(plannerArtifact);
      if (localArtifactSha256 !== coreSummary.integration_artifact_sha256) {
        throw new Error("AGENT Core planner artifact digest mismatch.");
      }
      const bindingIssues = autonomyPlannerBindingIssues(
        plannerArtifact,
        harnessRequest,
        harnessInspection,
      );
      if (bindingIssues.length) {
        throw new Error(`AGENT Core planner binding failed: ${bindingIssues.join(", ")}`);
      }
      planningRunId = coreSummary.plan_revision_id;
      planningArtifactSha256 = coreSummary.integration_artifact_sha256;
      planningBrief = coreSummary.notifications?.find((item) => item.kind === "plan")?.content.trim()
        || (input.chinese
          ? `计划已生成：${coreSummary.goal}（${coreSummary.model_calls} 次模型调用，${coreSummary.planning_attempts} 轮规划验证）`
          : `Plan ready: ${coreSummary.goal} (${coreSummary.model_calls} model calls, ${coreSummary.planning_attempts} planning rounds)`);
      const plannerBinding: NonNullable<AutonomyCompileAssetContext["planner_binding"]> = {
        schema_version: "dronedream.autonomy.planner-binding.v1",
        status: "draft",
        run_id: planningRunId,
        provider: input.selectedModel.provider,
        model: input.selectedModel.model,
        artifact_sha256: planningArtifactSha256,
        goal: plannerArtifact.goal,
        aircraft_id: plannerArtifact.asset_bindings.aircraft_id,
        aircraft_version: plannerArtifact.asset_bindings.aircraft_version,
        map_id: plannerArtifact.asset_bindings.map_id,
        map_version: plannerArtifact.asset_bindings.map_version,
        context_sha256: plannerArtifact.asset_bindings.context_sha256,
        task_graph: plannerArtifact.task_graph,
      };
      return {
        planningBrief,
        planningRunId,
        planningArtifactSha256,
        plannerArtifact,
        harnessInspection,
        compileRequest: null,
        compileResult: null,
        compiledPlan: agentCoreMissionPlanSnapshot(coreSummary, plannerBinding),
      };
    } catch (reason) {
      // The installed AGENT edition has exactly one planning and execution
      // authority. A Core failure must never be hidden by charging a second
      // planner or silently switching to the public compiler/runtime.
      if (!isAgentCoreUnavailable(reason)) throw reason;
      throw reason;
    }
  }

  if (!input.publicDemo) {
    try {
      const workflow = await apiClient.compileTaskWorkflow({
        request_id: `autonomy:${input.conversationId}:${input.turnId}`,
        edition: input.edition,
        requested_task_type: "mission_autonomy",
        message: input.instruction,
        locale: input.chinese ? "zh-CN" : "en",
        conversation_summary: input.workspace.mission.planningBrief.slice(0, 4_000),
        context: [
          {
            key: "autonomy.harness",
            value: JSON.stringify(autonomyModelContext(harnessRequest, harnessInspection)).slice(0, 4_000),
            source: "asset_receipt",
          },
          {
            key: "planning.model",
            value: `${input.selectedModel.accessMode}:${input.selectedModel.provider}:${input.selectedModel.model}`,
            source: "workspace",
          },
          {
            key: "autonomy.request_purpose",
            value: input.requestPurpose,
            source: "workspace",
          },
          ...(input.runtimeContext ? [{
            key: "autonomy.runtime_interruption",
            value: JSON.stringify(input.runtimeContext).slice(0, 4_000),
            source: "workspace" as const,
          }] : []),
        ],
        requested_tool_ids: [],
      });
      planningRunId = workflow.contract_id;
      if (workflow.status === "blocked") {
        harnessInspection = {
          ...harnessInspection,
          status: "blocked",
          planning_ready: false,
          blockers: [...new Set([...harnessInspection.blockers, ...workflow.blockers])],
        };
        planningBrief = autonomyAssetBlockerMessage(harnessInspection, input.chinese);
      }
    } catch {
      harnessInspection = {
        ...harnessInspection,
        status: "blocked",
        planning_ready: false,
        blockers: [...new Set([
          ...harnessInspection.blockers,
          "The deterministic task workflow could not be compiled.",
        ])],
      };
      planningBrief = autonomyAssetBlockerMessage(harnessInspection, input.chinese);
    }
  }

  try {
    if (!harnessInspection.planning_ready) {
      throw new Error("The deterministic workflow gate blocked model planning.");
    }
    if (input.selectedModel.accessMode !== "platform") {
      throw new Error("Custom model planning requires the local AGENT Core runtime.");
    }
    const response = (await orchestrateAssistantTurn({
      edition: input.edition,
      workspaceId: input.conversationId,
      organizationId: activeAssistantTenantContext(input.accountId ?? "local").organizationId,
      idempotencyKey: `autonomy:${input.conversationId}:${input.turnId}`,
      message: input.instruction,
      requestedTaskType: "mission_autonomy",
      locale: input.chinese ? "zh-CN" : "en",
      selectedModel: input.selectedModel,
      currentValues: {
        autonomy_context: autonomyModelContext(harnessRequest, harnessInspection),
        request_purpose: input.requestPurpose,
        runtime_interruption: input.runtimeContext ?? null,
      },
      documentContext: null,
    })).response;
    plannerArtifact = parseAutonomyPlannerArtifact(response.orchestration?.artifact_payload);
    if (!plannerArtifact) throw new Error("The model did not return a valid autonomy planner artifact.");
    const serverArtifactSha256 = response.orchestration?.artifact_sha256;
    const localArtifactSha256 = await autonomyCanonicalSha256(plannerArtifact);
    if (
      !serverArtifactSha256
      || !/^[0-9a-f]{64}$/u.test(serverArtifactSha256)
      || serverArtifactSha256 !== localArtifactSha256
    ) {
      throw new Error("The model planner artifact did not match its server-issued digest.");
    }
    planningArtifactSha256 = serverArtifactSha256;
    const bindingIssues = autonomyPlannerBindingIssues(
      plannerArtifact,
      harnessRequest,
      harnessInspection,
    );
    if (bindingIssues.length) {
      throw new Error(`The model planner artifact failed binding: ${bindingIssues.join(", ")}`);
    }
    planningBrief = response.assistant_message?.trim() || response.experiment_summary.trim();
    planningRunId = response.orchestration?.run_id ?? planningRunId;
    if (plannerArtifact.status !== "draft") {
      harnessInspection = {
        ...harnessInspection,
        status: plannerArtifact.status,
        planning_ready: false,
        blockers: [...new Set([...harnessInspection.blockers, ...plannerArtifact.blockers])],
      };
    }
  } catch (reason) {
    planningBrief = planningBrief || autonomyAssetBlockerMessage(harnessInspection, input.chinese);
    if (!input.publicDemo) throw reason;
  }

  if (!harnessInspection.planning_ready) {
    return {
      planningBrief,
      planningRunId,
      planningArtifactSha256,
      plannerArtifact,
      harnessInspection,
      compileRequest: null,
      compileResult: null,
      compiledPlan: null,
    };
  }
  const compileRequest = compileRequestForWorkspace(
    input.edition,
    input.workspace,
    input.intent,
    input.chinese ? "zh-CN" : "en",
    {
      schema_version: "dronedream.autonomy.compile-assets.v1",
      harness_context_sha256: harnessInspection.context_sha256,
      aircraft: harnessRequest.aircraft,
      map_pack: harnessRequest.map_pack,
      planner_binding: input.publicDemo || !plannerArtifact || !planningRunId || !planningArtifactSha256
        ? null
        : {
            schema_version: "dronedream.autonomy.planner-binding.v1",
            status: "draft",
            run_id: planningRunId,
            provider: input.selectedModel.provider,
            model: input.selectedModel.model,
            artifact_sha256: planningArtifactSha256,
            goal: plannerArtifact.goal,
            aircraft_id: plannerArtifact.asset_bindings.aircraft_id,
            aircraft_version: plannerArtifact.asset_bindings.aircraft_version,
            map_id: plannerArtifact.asset_bindings.map_id,
            map_version: plannerArtifact.asset_bindings.map_version,
            context_sha256: plannerArtifact.asset_bindings.context_sha256,
            task_graph: plannerArtifact.task_graph,
          },
    },
  );
  const compileResult = input.publicDemo
    ? createLocalAutonomyPreview(
        missionIdForScene(compileRequest.scene_id, compileRequest.natural_language),
        compileRequest,
      )
    : await apiClient.compileAutonomyMission(compileRequest);
  const compiledPlan = missionPlanSnapshot(
    compileResult,
    input.workspace,
    input.publicDemo ? "local-preview" : "backend",
    compileRequest.asset_context?.planner_binding ?? null,
  );
  return {
    planningBrief,
    planningRunId,
    planningArtifactSha256,
    plannerArtifact,
    harnessInspection,
    compileRequest,
    compileResult,
    compiledPlan,
  };
}
