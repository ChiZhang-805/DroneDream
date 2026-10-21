import type { BrandEditionId } from "../../brand/edition-brand.generated";
import {
  issueManagedModelGrant,
} from "../settings/cloudModelAccess";
import {
  AgentCoreUnavailableError,
  createAgentCoreThread,
  executeAgentCoreMission,
  getAgentCoreAssetQualificationEvidence,
  getAgentCoreThread,
  getAgentCoreBootstrap,
  issueAgentCoreCustomModelGrant,
  patchAgentCoreThread,
  prepareAgentCoreMission,
  requestAgentCoreAssetInterpretation,
  submitAgentCoreRuntimeMessage,
  uploadAgentCoreAttachment,
  type AgentCoreAssetKind,
  type AgentCoreAssetQualificationEvidence,
  type AgentCoreAssetQualificationJob,
  type AgentCoreAssetVersion,
  type AgentCoreMissionPrepareSummary,
  type AgentCoreThread,
} from "./agentCore";
import type {
  AutonomyHarnessInspectRequest,
  AutonomyHarnessInspectResponse,
} from "../../types/api";
import { verifiedAutonomyHarnessInspection } from "./missionHarness";
import type { AutonomyWorkspaceState } from "./workspaceStore";

const THREAD_BINDING_PREFIX = "dronedream:agent-core-thread:v1";

export interface AgentCorePlanningInput {
  edition: BrandEditionId;
  accountId: string | null;
  conversationId: string;
  instruction: string;
  locale: "zh-CN" | "en-US";
  accessMode: "platform" | "byok";
  provider: string;
  model: string;
  agentCoreProfileId: string | null;
  agentCoreSelectionId: string | null;
  workspace: AutonomyWorkspaceState;
  harnessContextSha256: string;
  requestPurpose: "initial_plan" | "runtime_replan";
  runtimeContext?: Record<string, unknown> | null;
  attachments?: File[];
  inputChannel?: "text" | "voice" | "camera" | "api" | "webhook" | "scheduled";
  transcriptSource?: "web-speech" | "audio-attachment" | null;
}

/** BYOK selects a Core-owned credential profile, never a key copied into the draft. */
function selectedModelId(input: Pick<AgentCorePlanningInput,
  "accessMode" | "model" | "agentCoreProfileId" | "agentCoreSelectionId"
>): string {
  if (input.accessMode === "platform") return input.model;
  if (
    !input.agentCoreProfileId
    || !input.agentCoreSelectionId
    || input.agentCoreSelectionId !== `custom:${input.agentCoreProfileId}`
  ) {
    throw new Error("AGENT_CORE_CUSTOM_MODEL_NOT_SECURELY_CONFIGURED");
  }
  return input.agentCoreSelectionId;
}

/** Extract optional grant routing; the receiving Core still validates the endpoint. */
function modelGatewayBaseUrl(grant: unknown): string | null {
  if (typeof grant !== "object" || grant === null || !("gateway_base_url" in grant)) {
    return null;
  }
  const gatewayBaseUrl = grant.gateway_base_url;
  return typeof gatewayBaseUrl === "string" && gatewayBaseUrl.trim()
    ? gatewayBaseUrl
    : null;
}

/** Namespace UI-to-Core thread hints by account, edition and public conversation. */
function bindingKey(input: Pick<AgentCorePlanningInput, "edition" | "accountId" | "conversationId">): string {
  return [
    THREAD_BINDING_PREFIX,
    encodeURIComponent(input.accountId || "local"),
    input.edition,
    encodeURIComponent(input.conversationId),
  ].join(":");
}

/** Storage is a lookup hint only; Core must still authorize the referenced thread. */
function readThreadBinding(input: Pick<AgentCorePlanningInput, "edition" | "accountId" | "conversationId">): string | null {
  try {
    return window.localStorage.getItem(bindingKey(input));
  } catch {
    return null;
  }
}

/** Persist only a thread identifier; failing to save must not invalidate this turn. */
function saveThreadBinding(
  input: Pick<AgentCorePlanningInput, "edition" | "accountId" | "conversationId">,
  threadId: string,
): void {
  try {
    window.localStorage.setItem(bindingKey(input), threadId);
  } catch {
    // A private browsing policy may disable persistence. The current turn still works.
  }
}

/**
 * An explicit content hash is a pin: never substitute a newer/different asset.
 * Without a pin, choose only a qualified version, not merely the newest import.
 */
function latestAssetVersion(
  versions: AgentCoreAssetVersion[],
  assetId: string | null | undefined,
  explicitSha256: string | null | undefined,
  kind: AgentCoreAssetKind,
): AgentCoreAssetVersion {
  const candidates = versions
    .filter((version) => (
      version.asset_id === assetId
      && (version.kind === kind || (kind === "map" && version.kind === "world"))
    ))
    .sort((left, right) => right.imported_at.localeCompare(left.imported_at));
  const selected = explicitSha256
    ? candidates.find((version) => (
        version.content_sha256 === explicitSha256 && version.maturity === "qualified"
      ))
    : candidates.find((version) => version.maturity === "qualified");
  if (!selected) throw new Error(`AGENT_CORE_ASSET_VERSION_NOT_FOUND:${kind}:${assetId || "unbound"}`);
  return selected;
}

function sha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/u.test(value);
}

// 功能：
//   使用当前模型解析单个精确资产版本，模型授权只在调用前申请。
// 输入：
//   input：当前账户、版本、模型及卡片对应的资产。
// 输出：
//   result：实际模型解析或同版本缓存结果。
export async function interpretAgentCoreAsset(input: Pick<AgentCorePlanningInput, "edition" | "accountId" | "locale" | "accessMode" | "provider" | "model" | "agentCoreProfileId" | "agentCoreSelectionId"> & {
  kind: "map" | "vehicle"; assetId: string | null; contentSha256: string | null;
}) {
  if (!input.accountId) throw new Error("AGENT_CORE_ACCOUNT_REQUIRED");
  const modelId = selectedModelId(input);
  const bootstrap = await getAgentCoreBootstrap();
  const entry = bootstrap.models.find((item) => item.id === modelId);
  if (!entry || (input.accessMode === "platform" && (entry.source !== "default" || entry.provider !== input.provider))
    || (input.accessMode === "byok" && (entry.source !== "custom" || entry.profile_id !== input.agentCoreProfileId))) {
    throw new Error("AGENT_CORE_MODEL_NOT_AVAILABLE");
  }
  const version = latestAssetVersion(bootstrap.asset_versions, input.assetId, input.contentSha256, input.kind);
  const thread = await createAgentCoreThread({ title: input.locale === "zh-CN" ? "资产解析" : "Asset interpretation", selected_model: modelId });
  const grant = input.accessMode === "platform"
    ? await issueManagedModelGrant("assistant", thread.thread_id, input.provider as "openai" | "deepseek" | "qwen" | "kimi", input.model)
    : await issueAgentCoreCustomModelGrant(input.agentCoreProfileId!, thread.thread_id);
  const result = await requestAgentCoreAssetInterpretation(thread.thread_id, {
    expected_owner_account_id: input.accountId, source_edition: input.edition,
    kind: input.kind, asset_id: version.asset_id, content_sha256: version.content_sha256,
    model_id: modelId, model_grant: grant.grant, gateway_base_url: modelGatewayBaseUrl(grant),
    locale: input.locale, force: false,
  });
  if (result.source.asset_id !== version.asset_id || result.source.content_sha256 !== version.content_sha256
    || result.source.kind !== input.kind) throw new Error("AGENT_CORE_ASSET_INTERPRETATION_BINDING_INVALID");
  return result;
}

/**
 * Cross-check the map/vehicle pair, runtime contracts and successful receipt.
 * This client check complements Core's byte/hash verification; UI "100%" alone
 * is not qualification, nor does asset qualification authorize mission execution.
 */
function assertVerifiedPairEvidence(
  evidence: AgentCoreAssetQualificationEvidence,
  expected: {
    jobId: string;
    qualificationId: string;
    mapAssetId: string;
    mapContentSha256: string;
    sourceMapContentSha256: string;
    vehicleAssetId: string;
    vehicleContentSha256: string;
    sourceVehicleContentSha256: string;
  },
): void {
  const receipt = evidence.receipt;
  const failures: string[] = [];
  const exact = (actual: unknown, value: string, field: string) => {
    if (actual !== value) failures.push(`${field}.mismatch`);
  };
  if (evidence.schema_version !== "dronedream.asset-qualification-evidence.v1") {
    failures.push("evidence.schema.invalid");
  }
  exact(evidence.job_id, expected.jobId, "evidence.job-id");
  exact(evidence.qualification_id, expected.qualificationId, "evidence.qualification-id");
  exact(evidence.map_asset_id, expected.mapAssetId, "evidence.map-id");
  exact(evidence.map_content_sha256, expected.mapContentSha256, "evidence.map-hash");
  exact(evidence.vehicle_asset_id, expected.vehicleAssetId, "evidence.vehicle-id");
  exact(evidence.vehicle_content_sha256, expected.vehicleContentSha256, "evidence.vehicle-hash");
  if (!sha256(evidence.evidence_sha256)) failures.push("evidence.hash.invalid");
  const runtimeContracts = evidence.runtime_contracts;
  if (runtimeContracts?.schema_version !== "dronedream.asset-pair-runtime-contracts.v1") {
    failures.push("runtime-contracts.schema.invalid");
  } else {
    exact(runtimeContracts.map.asset_id, expected.mapAssetId, "runtime-contracts.map-id");
    exact(runtimeContracts.map.content_sha256, expected.mapContentSha256, "runtime-contracts.map-hash");
    exact(runtimeContracts.vehicle.asset_id, expected.vehicleAssetId, "runtime-contracts.vehicle-id");
    exact(runtimeContracts.vehicle.content_sha256, expected.vehicleContentSha256, "runtime-contracts.vehicle-hash");
    const mapTargets = runtimeContracts.map.simulation_targets;
    const vehicleTargets = runtimeContracts.vehicle.simulation_targets;
    const targetIdentity = (target: (typeof mapTargets)[number]) => [
      target.simulator,
      target.simulator_version,
      target.ros_distribution ?? "none",
    ].join(":");
    const unsafeTarget = (target: (typeof mapTargets)[number]) => (
      !target.target_id
      || !target.simulator_version
      || !target.entrypoint
      || target.entrypoint.startsWith("/")
      || /^[a-z]:/iu.test(target.entrypoint)
      || target.entrypoint.includes("\\")
      || target.entrypoint.split("/").some((segment) => segment === ".." || segment === "")
    );
    // 场景可以不含飞控；只有声明了飞控约束的地图才要求与飞机一致。
    const compatibleRuntimeTarget = mapTargets.some((mapTarget) => vehicleTargets.some((vehicleTarget) => (
      targetIdentity(mapTarget) === targetIdentity(vehicleTarget)
      && (mapTarget.autopilot === "none" || mapTarget.autopilot === vehicleTarget.autopilot)
    )));
    if (
      runtimeContracts.map.coordinate_frame !== "ENU"
      || runtimeContracts.vehicle.coordinate_frame !== "base_link_frd"
      || runtimeContracts.map.node_count < 2
      || runtimeContracts.map.edge_count < 1
      || runtimeContracts.vehicle.dry_mass_kg <= 0
      || runtimeContracts.vehicle.max_takeoff_mass_kg <= runtimeContracts.vehicle.dry_mass_kg
      || runtimeContracts.vehicle.body_radius_m <= 0
      || runtimeContracts.vehicle.body_height_m <= 0
      || runtimeContracts.vehicle.max_speed_mps <= 0
      || runtimeContracts.vehicle.max_acceleration_mps2 <= 0
      || runtimeContracts.vehicle.sensors.length === 0
      || mapTargets.length === 0
      || vehicleTargets.length === 0
      || mapTargets.some(unsafeTarget)
      || vehicleTargets.some(unsafeTarget)
      || !compatibleRuntimeTarget
    ) {
      failures.push("runtime-contracts.values.invalid");
    }
  }
  if (receipt.schema_version !== "dronedream.asset-pair-qualification-receipt.v1") {
    failures.push("receipt.schema.invalid");
  }
  if (receipt.status !== "verified") failures.push("receipt.status.invalid");
  exact(receipt.qualification_id, expected.qualificationId, "receipt.qualification-id");
  exact(receipt.map_asset_id, expected.mapAssetId, "receipt.map-id");
  // 原始回执绑定认证输入；外层证据及运行契约绑定加入回执后的输出包。
  exact(receipt.map_content_sha256, expected.sourceMapContentSha256, "receipt.map-hash");
  exact(receipt.vehicle_asset_id, expected.vehicleAssetId, "receipt.vehicle-id");
  exact(receipt.vehicle_content_sha256, expected.sourceVehicleContentSha256, "receipt.vehicle-hash");
  if (!sha256(receipt.runtime_evidence_sha256)) failures.push("receipt.runtime-evidence-hash.invalid");
  if (!receipt.environment_versions || Object.keys(receipt.environment_versions).length === 0) {
    failures.push("receipt.environment-versions.missing");
  }
  const runtimeEvidence = receipt.runtime_evidence;
  if (!runtimeEvidence || runtimeEvidence.status !== "verified") {
    failures.push("receipt.runtime-evidence.status.invalid");
  }
  const gates = runtimeEvidence?.gates;
  if (
    !gates
    || Object.keys(gates).length === 0
    || Object.values(gates).some((accepted) => accepted !== true)
  ) {
    failures.push("receipt.runtime-evidence.gates.invalid");
  }
  if ((receipt.plugin_checks ?? []).some((check) => check.accepted !== true)) {
    failures.push("receipt.plugin-check.rejected");
  }
  if ((receipt.plugin_hook_receipts ?? []).some((item) => item.outcome !== "accepted")) {
    failures.push("receipt.plugin-hook.rejected");
  }
  const hasPluginEvidence = (receipt.plugin_checks?.length ?? 0) > 0
    || (receipt.plugin_hook_receipts?.length ?? 0) > 0;
  if (hasPluginEvidence && (!receipt.plugin_snapshot || !sha256(receipt.plugin_snapshot_sha256))) {
    failures.push("receipt.plugin-snapshot.missing");
  }
  if (failures.length) {
    throw new Error(`AGENT_CORE_ASSET_PAIR_EVIDENCE_INVALID:${failures.join(",")}`);
  }
}

// 功能：
//   为当前所选资产解析同一份后端认证；已有内容摘要固定版本，未固定时才选最新合格版本。
// 输入：
//   workspace：当前地图与飞机选择；页面缓存的回执标识不作为认证依据。
// 输出：
//   pair：通过输入包、输出包、运行契约及回执交叉校验的资产组合。
export async function resolveAgentCoreAssetPair(workspace: AutonomyWorkspaceState) {
  const bootstrap = await getAgentCoreBootstrap();
  const mapVersion = latestAssetVersion(
    bootstrap.asset_versions,
    workspace.mapPack.agentCoreAssetId,
    workspace.mapPack.agentCoreContentSha256,
    "map",
  );
  const vehicleVersion = latestAssetVersion(
    bootstrap.asset_versions,
    workspace.aircraft.agentCoreAssetId,
    workspace.aircraft.agentCoreContentSha256,
    "vehicle",
  );
  const jobs = bootstrap.asset_qualification_jobs.filter((candidate) => (
    candidate.state === "qualified"
    && candidate.progress_percent === 100
    && /^asset-qualification-[0-9a-f]{24}$/u.test(candidate.qualification_id ?? "")
    && candidate.map_asset_id === mapVersion.asset_id
    && candidate.result_map_content_sha256 === mapVersion.content_sha256
    && candidate.vehicle_asset_id === vehicleVersion.asset_id
    && candidate.result_vehicle_content_sha256 === vehicleVersion.content_sha256
  )).sort((left, right) => right.updated_at.localeCompare(left.updated_at));
  const job = jobs.find((candidate) => (
    candidate.qualification_id === workspace.mapPack.qualificationReceiptId
    && candidate.qualification_id === workspace.aircraft.qualificationReceiptId
  )) ?? jobs[0];
  if (!job) throw new Error("AGENT_CORE_ASSET_PAIR_QUALIFICATION_JOB_NOT_FOUND");
  const qualificationId = job.qualification_id!;
  if (!sha256(job.map_content_sha256) || !sha256(job.vehicle_content_sha256)) {
    throw new Error("AGENT_CORE_ASSET_PAIR_EVIDENCE_INVALID:job.source-hash.invalid");
  }
  const evidence = await getAgentCoreAssetQualificationEvidence(job.job_id);
  assertVerifiedPairEvidence(evidence, {
    jobId: job.job_id,
    qualificationId,
    mapAssetId: mapVersion.asset_id,
    mapContentSha256: mapVersion.content_sha256,
    sourceMapContentSha256: job.map_content_sha256,
    vehicleAssetId: vehicleVersion.asset_id,
    vehicleContentSha256: vehicleVersion.content_sha256,
    sourceVehicleContentSha256: job.vehicle_content_sha256,
  });
  return { job: job as AgentCoreAssetQualificationJob, mapVersion, vehicleVersion, evidence };
}

// 功能：
//   检查请求与工作区的同一认证绑定，再把后端验证的证据加入 Harness。
// 输入：
//   request：由当前工作区生成的规划请求。
//   workspace：已同步认证的地图和飞机。
// 输出：
//   inspection：规划检查结果；不授予飞行权限。
export async function inspectAgentCoreAssetBindings(request: AutonomyHarnessInspectRequest, workspace: AutonomyWorkspaceState): Promise<AutonomyHarnessInspectResponse> {
  const qualificationId = workspace.mapPack.qualificationReceiptId;
  if (!qualificationId || !workspace.aircraft.qualificationReceiptId) {
    throw new Error("AGENT_CORE_ASSET_PAIR_BINDING_REQUIRED");
  }
  if (qualificationId !== workspace.aircraft.qualificationReceiptId
    || qualificationId !== request.map_pack.qualification_receipt_id
    || qualificationId !== request.aircraft.qualification_receipt_id
    || !/^asset-qualification-[0-9a-f]{24}$/u.test(qualificationId)
    || request.map_pack.content_hash !== workspace.mapPack.agentCoreContentSha256
    || request.aircraft.content_hash !== workspace.aircraft.agentCoreContentSha256) {
    throw new Error("AGENT_CORE_ASSET_PAIR_QUALIFICATION_ID_MISMATCH");
  }
  const { job, mapVersion, vehicleVersion, evidence } = await resolveAgentCoreAssetPair(workspace);
  if (job.qualification_id !== qualificationId) {
    throw new Error("AGENT_CORE_ASSET_PAIR_QUALIFICATION_ID_MISMATCH");
  }
  // The loopback Core verifies the receipt bytes and evidence SHA-256 before
  // returning this response. The public shell binds that server-verified digest
  // into its own Harness context rather than reserializing Python JSON in JS.
  return verifiedAutonomyHarnessInspection(request, {
    authority: "agent-core",
    job_id: job.job_id,
    qualification_id: qualificationId,
    evidence_sha256: evidence.evidence_sha256,
    map_asset_id: mapVersion.asset_id,
    map_content_sha256: mapVersion.content_sha256,
    vehicle_asset_id: vehicleVersion.asset_id,
    vehicle_content_sha256: vehicleVersion.content_sha256,
    runtime_evidence_sha256: evidence.receipt.runtime_evidence_sha256,
  });
}

/** Reconcile saved UI hints with Core's current model catalog and asset hashes. */
async function ensureThread(input: AgentCorePlanningInput): Promise<{
  thread: AgentCoreThread;
  mapVersion: AgentCoreAssetVersion;
  vehicleVersion: AgentCoreAssetVersion;
}> {
  const bootstrap = await getAgentCoreBootstrap();
  const modelSelectionId = selectedModelId(input);
  const catalogEntry = bootstrap.models.find((entry) => entry.id === modelSelectionId);
  if (
    !catalogEntry
    || (input.accessMode === "platform" && (
      catalogEntry.source !== "default"
      || catalogEntry.provider !== input.provider
    ))
    || (input.accessMode === "byok" && (
      catalogEntry.source !== "custom"
      || catalogEntry.profile_id !== input.agentCoreProfileId
    ))
  ) {
    throw new Error(`AGENT_CORE_MODEL_NOT_AVAILABLE:${input.provider}:${modelSelectionId}`);
  }
  const mapVersion = latestAssetVersion(
    bootstrap.asset_versions,
    input.workspace.mapPack.agentCoreAssetId,
    input.workspace.mapPack.agentCoreContentSha256,
    "map",
  );
  const vehicleVersion = latestAssetVersion(
    bootstrap.asset_versions,
    input.workspace.aircraft.agentCoreAssetId,
    input.workspace.aircraft.agentCoreContentSha256,
    "vehicle",
  );
  const rememberedThreadId = readThreadBinding(input);
  let thread = bootstrap.threads.find((entry) => entry.thread_id === rememberedThreadId) ?? null;
  const title = input.instruction.trim().slice(0, 120) || (input.locale === "zh-CN" ? "自主任务" : "Autonomous mission");
  if (!thread) {
    thread = await createAgentCoreThread({ title, selected_model: modelSelectionId });
    saveThreadBinding(input, thread.thread_id);
  }
  thread = await patchAgentCoreThread(thread.thread_id, {
    title,
    selected_model: modelSelectionId,
    selected_map_id: mapVersion.asset_id,
    selected_map_content_sha256: mapVersion.content_sha256,
    selected_vehicle_id: vehicleVersion.asset_id,
    selected_vehicle_content_sha256: vehicleVersion.content_sha256,
  });
  return { thread, mapVersion, vehicleVersion };
}

/**
 * Prepare, but do not execute, a mission using a scoped platform/BYOK grant.
 * Attachments and asset hashes accompany the request; returned bindings must
 * match exactly before the plan can be shown for confirmation.
 */
export async function planWithAgentCore(
  input: AgentCorePlanningInput,
): Promise<AgentCoreMissionPrepareSummary> {
  if (!input.accountId) throw new Error("AGENT_CORE_ACCOUNT_REQUIRED");
  const { thread, mapVersion, vehicleVersion } = await ensureThread(input);
  const modelSelectionId = selectedModelId(input);
  const attachmentIds: string[] = [];
  for (const file of (input.attachments ?? []).slice(0, 8)) {
    const uploaded = await uploadAgentCoreAttachment(thread.thread_id, file);
    attachmentIds.push(uploaded.attachment_id);
  }
  const grant = input.accessMode === "platform"
    ? await issueManagedModelGrant(
        "assistant",
        thread.thread_id,
        input.provider as "openai" | "deepseek" | "qwen" | "kimi",
        input.model,
      )
    : await issueAgentCoreCustomModelGrant(input.agentCoreProfileId!, thread.thread_id);
  const summary = await prepareAgentCoreMission(thread.thread_id, {
    expected_owner_account_id: input.accountId,
    source_edition: input.edition,
    message: input.instruction,
    map_id: mapVersion.asset_id,
    map_content_sha256: mapVersion.content_sha256,
    vehicle_id: vehicleVersion.asset_id,
    vehicle_content_sha256: vehicleVersion.content_sha256,
    model_id: modelSelectionId,
    model_grant: grant.grant,
    gateway_base_url: modelGatewayBaseUrl(grant),
    locale: input.locale,
    start_entity: "__auto__",
    attachment_ids: attachmentIds,
    role_models: [],
    input_channel: input.inputChannel ?? "text",
    input_metadata: {
      public_harness_context_sha256: input.harnessContextSha256,
      public_asset_bindings: {
        map_id: input.workspace.mapPack.id,
        map_version: input.workspace.mapPack.version,
        aircraft_id: input.workspace.aircraft.id,
        aircraft_version: input.workspace.aircraft.version,
      },
      public_edition: input.edition,
      public_conversation_id: input.conversationId,
      request_purpose: input.requestPurpose,
      runtime_context: input.runtimeContext ?? null,
      transcript_source: input.transcriptSource ?? null,
      attachment_count: attachmentIds.length,
    },
  });
  if (
    summary.mission_plan.asset_bindings.map_asset_id !== mapVersion.asset_id
    || summary.mission_plan.asset_bindings.map_content_sha256 !== mapVersion.content_sha256
    || summary.mission_plan.asset_bindings.vehicle_asset_id !== vehicleVersion.asset_id
    || summary.mission_plan.asset_bindings.vehicle_content_sha256 !== vehicleVersion.content_sha256
  ) {
    throw new Error("AGENT_CORE_PREPARED_ASSET_BINDING_MISMATCH");
  }
  return summary;
}

export function isAgentCoreUnavailable(reason: unknown): boolean {
  return reason instanceof AgentCoreUnavailableError;
}

/** Forward a user amendment to Core; the UI does not apply it directly to flight. */
export async function submitRuntimeMessageToBoundAgentCore(input: {
  edition: BrandEditionId;
  accountId: string | null;
  conversationId: string;
  text: string;
}): Promise<Record<string, unknown> | null> {
  const threadId = readThreadBinding(input);
  if (!threadId) return null;
  return submitAgentCoreRuntimeMessage(threadId, input.text);
}

export interface AgentCoreExecutionInput {
  edition: BrandEditionId;
  accountId: string | null;
  conversationId: string;
  accessMode: "platform" | "byok";
  provider: string;
  model: string;
  agentCoreProfileId: string | null;
  agentCoreSelectionId: string | null;
  planRevisionId: string;
}

function executionModelId(input: AgentCoreExecutionInput): string {
  return selectedModelId(input);
}

/** Read the authoritative Core state, not a cached plan or local success flag. */
export async function getBoundAgentCoreThread(
  input: Pick<AgentCoreExecutionInput, "edition" | "accountId" | "conversationId">,
) {
  const threadId = readThreadBinding(input);
  if (!threadId) return null;
  return getAgentCoreThread(threadId);
}

// 功能：
//   复读后端任务，确认页面所展示的精确计划仍为当前计划，再申请授权并启动仿真。
// 输入：
//   input：当前账户、版本、任务、模型及用户已确认的计划修订标识。
// 输出：
//   receipt：后端启动回执，不代表已经起飞或任务成功。
export async function executeBoundAgentCoreMission(input: AgentCoreExecutionInput) {
  if (!input.accountId) throw new Error("AGENT_CORE_ACCOUNT_REQUIRED");
  if (!/^plan-[0-9a-f]{32}$/u.test(input.planRevisionId)) {
    throw new Error("AGENT_CORE_EXPLICIT_PLAN_CONFIRMATION_REQUIRED");
  }
  const threadId = readThreadBinding(input);
  if (!threadId) throw new Error("AGENT_CORE_THREAD_NOT_BOUND");
  const modelId = executionModelId(input);
  const thread = await getAgentCoreThread(threadId);
  if (thread.selected_model !== modelId || thread.state !== "awaiting_confirmation") {
    throw new Error(`AGENT_CORE_TASK_NOT_CONFIRMABLE:${thread.state}`);
  }
  const currentPlan = (thread.messages ?? []).filter(
    (message) => message.role === "assistant" && message.kind === "plan",
  ).at(-1);
  if (currentPlan?.metadata?.plan_revision_id !== input.planRevisionId) {
    throw new Error("AGENT_CORE_PLAN_CHANGED_REVIEW_AGAIN");
  }
  const grant = input.accessMode === "platform"
    ? await issueManagedModelGrant(
        "assistant",
        threadId,
        input.provider as "openai" | "deepseek" | "qwen" | "kimi",
        input.model,
      )
    : await issueAgentCoreCustomModelGrant(input.agentCoreProfileId!, threadId);
  const receipt = await executeAgentCoreMission(threadId, {
    expected_owner_account_id: input.accountId,
    source_edition: input.edition,
    plan_revision_id: input.planRevisionId,
    model_id: modelId,
    model_grant: grant.grant,
    gateway_base_url: modelGatewayBaseUrl(grant),
  });
  return receipt;
}
