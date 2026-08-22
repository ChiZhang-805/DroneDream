import { open } from "@tauri-apps/plugin-dialog";
import type { AutonomyPlannerArtifact } from "./missionHarness";

export type AgentCoreActivationMode = "single" | "multiple" | "pipeline";

export interface AgentCoreStatus {
  available: boolean;
  restarting: boolean;
  endpoint: "loopback-random-port";
  authentication: "per-launch-bearer-token";
  processIsolation: "sidecar-and-plugin-isolator";
  startupIssue: "agent-core-startup-failed" | "agent-core-unavailable" | null;
}

export interface AgentCorePluginEntry {
  plugin_id: string;
  name: string;
  version: string;
  authority: string;
  enabled: boolean;
  builtin: boolean;
  description: string;
  publisher: string;
  runtime_kind: string;
  status: string;
  health: string;
  removable: boolean;
  disable_allowed: boolean;
  slot_required: boolean;
  package_sha256: string;
  last_error: string | null;
  trust_status: "verified" | "local-approved" | "unverified" | "revoked";
  update_ring: "stable" | "preview" | "canary" | "pinned";
  capabilities: Array<{
    capability_id: string;
    kind: string;
    name: string;
    description: string;
    authority: string;
    metadata: Record<string, unknown>;
  }>;
  permissions: string[];
  placement: {
    category_id: string;
    category_label: string;
    slot_id: string;
    slot_label: string;
    activation_mode: AgentCoreActivationMode;
    scope: "general" | "mission" | "runtime" | "interface";
    failure_mode: "fail-closed" | "isolate" | "advisory";
    swap_policy: "anytime" | "next-mission" | "safe-hold" | "restart" | "certified-update";
    category_order: number;
    slot_order: number;
    plugin_order: number;
    pipeline_order: number;
    runs_after: string[];
    runs_before: string[];
  };
}

export interface AgentCorePluginGovernancePolicy {
  schema_version: string;
  mode: "personal" | "managed";
  require_verified_signatures: boolean;
  allow_local_approval: boolean;
  maximum_external_plugins: number;
  allowed_publishers: string[];
  allowed_plugin_ids: string[];
  denied_permissions: string[];
}

export interface AgentCorePluginMarketplaceSource {
  schema_version: string;
  source_id: string;
  name: string;
  index_url: string;
  enabled: boolean;
}

export interface AgentCorePluginMarketplaceCatalog {
  sources: AgentCorePluginMarketplaceSource[];
  entries: Array<{
    source_id: string;
    plugin_id: string;
    version: string;
    name: string;
    publisher: string;
    description: string;
  }>;
  errors: Array<{ source_id: string; issue_code: string }>;
}

export type AgentCoreHarnessNodeKind =
  | "input"
  | "output"
  | "model_call"
  | "tool_call"
  | "transform"
  | "branch"
  | "join"
  | "safety_barrier"
  | "bounded_loop"
  | "human_approval"
  | "composite"
  | "stage";

export interface AgentCoreHarnessPort {
  port_id: string;
  schema_ref: string;
  required: boolean;
  cardinality: "one" | "many" | "stream" | "event";
  confidentiality: "public" | "task" | "sensitive" | "secret";
  maximum_connections: number;
}

export interface AgentCoreHarnessNodePolicy {
  timeout_seconds: number;
  retry_limit: number;
  failure_mode: "fail-closed" | "isolate" | "fallback";
  fallback_handler_id: string | null;
  cacheable: boolean;
  authority: "read" | "plan" | "simulate";
  maximum_model_calls: number | null;
  maximum_tool_calls: number | null;
}

export interface AgentCoreHarnessNode {
  node_id: string;
  descriptor_id: string;
  title: string;
  title_zh: string;
  node_kind: AgentCoreHarnessNodeKind;
  handler_id: string;
  runtime_node_kind: "core" | "plugin" | "barrier";
  required_inputs: string[];
  output_key: string | null;
  input_ports: AgentCoreHarnessPort[];
  output_ports: AgentCoreHarnessPort[];
  policy: AgentCoreHarnessNodePolicy;
  capabilities: {
    removable: boolean;
    replaceable: boolean;
    branchable: boolean;
    wrappable_in_loop: boolean;
    protected: boolean;
    allowed_operations: string[];
  };
  category: string;
  icon: string;
}

export type AgentCoreHarnessNodeDescriptor = Omit<AgentCoreHarnessNode, "node_id"> & {
  schema_version: string;
};

export interface AgentCoreHarnessEdge {
  schema_version: "dronedream.harness-edge-binding.v1";
  edge_id: string;
  source: { node_id: string; port_id: string };
  target: { node_id: string; port_id: string };
  schema_ref: string;
  transform_plugin_id: string | null;
  binding_mode: "direct" | "control" | "transform";
}

export interface AgentCoreHarnessCandidate {
  schema_version: "dronedream.harness-topology-candidate.v2";
  topology_id: string;
  name: string;
  profile_id: string;
  base_revision: number;
  nodes: AgentCoreHarnessNode[];
  edges: AgentCoreHarnessEdge[];
  loops: Array<Record<string, unknown>>;
  maximum_parallelism: number;
  layout: {
    positions: Record<string, { x: number; y: number; pinned: boolean }>;
    viewport: { x: number; y: number; zoom: number };
    collapsed_node_ids: string[];
    selected_node_id: string | null;
  };
  metadata: Record<string, unknown>;
}

export interface AgentCoreHarnessValidation {
  valid: boolean;
  issues: Array<{
    code: string;
    message: string;
    node_id: string | null;
    port_id: string | null;
    edge_id: string | null;
    severity: "error" | "warning";
  }>;
  semantic_sha256: string | null;
  layout_sha256: string | null;
  compiled_topology: Record<string, unknown> | null;
}

export interface AgentCoreHarnessRevision {
  revision: number;
  parent_revision: number | null;
  state: "candidate" | "active" | "applies_next_run" | "rejected" | "frozen";
  candidate: AgentCoreHarnessCandidate;
  validation: AgentCoreHarnessValidation;
  created_at: string;
  activated_at: string | null;
  applies_next_run: boolean;
}

export interface AgentCoreHarnessState {
  active: AgentCoreHarnessRevision;
  current: AgentCoreHarnessRevision;
  can_undo: boolean;
  can_redo: boolean;
}

export interface AgentCoreHarnessCatalog {
  schema_version: "dronedream.harness-catalog.v1";
  node_descriptors: AgentCoreHarnessNodeDescriptor[];
  topology_templates: Array<{
    topology_id: string;
    name: string;
    node_count: number;
    maximum_parallelism: number;
    metadata: Record<string, unknown>;
  }>;
  plugins: Array<{
    plugin_id: string;
    name: string;
    description: string;
    slot_id: string;
    slot_label: string;
    activation_mode: string;
    enabled: boolean;
    health: string;
    trust_status: string;
    version: string;
    package_sha256: string;
    granularity: "large" | "small";
    composition_level: 1 | 3;
    owner_item_ids: string[];
  }>;
  profiles: AgentCoreHarnessProfile[];
  composition_items: AgentCoreHarnessCompositionItem[];
  context_commands: Record<string, string[]>;
}

export interface AgentCoreHarnessCompositionItem {
  schema_version: "dronedream.harness-composition-item.v1";
  item_id: string;
  level: 1 | 2 | 3;
  parent_item_id: string | null;
  kind: "phase" | "stage" | "plugin-slot" | "policy";
  granularity: "large" | "medium" | "small";
  title: string;
  title_zh: string;
  description: string;
  description_zh: string;
  color_token: "amber" | "green" | "blue" | "red" | "violet" | "cyan" | string;
  icon: string;
  order: number;
  member_node_ids: string[];
  plugin_slot_ids: string[];
  child_item_ids: string[];
  enterable: boolean;
  replaceable: boolean;
  protected: boolean;
  scope: "workflow" | "phase" | "node";
}

export interface AgentCoreHarnessProfile {
  profile_id: string;
  name: string;
  description: string;
  enabled: boolean;
  health: string;
  trust_status: string;
}

export type AgentCoreHarnessOperation = {
  schema_version: "dronedream.harness-edit-operation.v1";
  client_operation_id: string;
  base_revision: number;
  operation:
    | "add_node"
    | "remove_node"
    | "connect"
    | "disconnect"
    | "move_node"
    | "update_layout"
    | "update_node"
    | "apply_profile"
    | "apply_template";
  payload: Record<string, unknown>;
};

export interface AgentCoreHarnessDryRun {
  valid: boolean;
  validation: AgentCoreHarnessValidation;
  layers: string[][];
  node_count: number;
  edge_count: number;
  protected_node_count: number;
  projected_model_nodes: string[];
  projected_tool_nodes: string[];
  external_calls_executed: 0;
  note: string;
}

export type AgentCoreAssetKind = "map" | "world" | "vehicle";
export type AgentCoreAssetImportState =
  | "created"
  | "quarantining"
  | "parsing"
  | "needs_input"
  | "normalizing"
  | "building"
  | "validating"
  | "qualified"
  | "failed"
  | "cancelled";

export interface AgentCoreAssetImportJob {
  schema_version: "dronedream.asset-import-job.v1";
  job_id: string;
  owner_id: string;
  source_name: string;
  source_format: string;
  detected_source_format: string | null;
  source_adapter_id: string | null;
  package_sha256: string;
  normalized_content_sha256: string | null;
  qualified_content_sha256: string | null;
  state: AgentCoreAssetImportState;
  progress_percent: number;
  revision: number;
  asset_id: string | null;
  asset_kind: AgentCoreAssetKind | null;
  issue_codes: string[];
  required_inputs: string[];
  created_at: string;
  updated_at: string;
}

export interface AgentCoreAssetSourceAdapter {
  adapter_id: string;
  name: string;
  version: string;
  availability: "builtin" | "companion_required" | "plugin_required";
  source_formats: string[];
  file_extensions: string[];
  asset_kinds: AgentCoreAssetKind[];
  output_format: "ddpkg";
  execution_boundary: "declarative-parser" | "isolated-local-companion" | "isolated-plugin";
  required_application: string | null;
  documentation_url: string | null;
  enabled: boolean;
  provider_plugin_ids: string[];
}

export interface AgentCoreAssetQualificationJob {
  schema_version: "dronedream.asset-pair-qualification-job.v1";
  job_id: string;
  map_asset_id: string;
  map_content_sha256: string;
  vehicle_asset_id: string;
  vehicle_content_sha256: string;
  state: "created" | "preparing" | "running" | "validating" | "paused" | "qualified" | "failed" | "cancelled";
  progress_percent: number;
  qualification_id: string | null;
  result_map_content_sha256: string | null;
  result_vehicle_content_sha256: string | null;
  issue_codes: string[];
  cancel_requested: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentCoreAssetIssue {
  schema_version: "dronedream.asset-issue.v1";
  code: string;
  severity: "info" | "warning" | "error";
  stage: string;
  location: string;
  title: Record<"zh-CN" | "en-US", string>;
  detail: Record<"zh-CN" | "en-US", string>;
  actions: Array<Record<"zh-CN" | "en-US", string>>;
}

export interface AgentCoreAssetIssueReport {
  schema_version: "dronedream.asset-issue-report.v1";
  job_id: string;
  issues: AgentCoreAssetIssue[];
}

export interface AgentCoreAssetPairRuntimeContracts {
  schema_version: "dronedream.asset-pair-runtime-contracts.v1";
  map: {
    asset_id: string;
    content_sha256: string;
    coordinate_frame: "ENU";
    node_count: number;
    edge_count: number;
    named_entity_count: number;
    navigation_bounds_m: {
      minimum: { x: number; y: number; z: number };
      maximum: { x: number; y: number; z: number };
      span: { x: number; y: number; z: number };
    };
    semantic_layers: string[];
    simulation_targets: AgentCoreSimulationTarget[];
  };
  vehicle: {
    schema_version: "dronedream.vehicle.v1";
    asset_id: string;
    content_sha256: string;
    name: string;
    coordinate_frame: "base_link_frd";
    dry_mass_kg: number;
    max_takeoff_mass_kg: number;
    body_radius_m: number;
    body_height_m: number;
    collision_center_offset_model_m: { x: number; y: number; z: number } | null;
    max_speed_mps: number;
    max_acceleration_mps2: number;
    qualified_range_m: number;
    reserve_battery_percent: number;
    max_pickup_payload_kg: number;
    sensors: string[];
    vehicle_class: "multirotor" | "fixed_wing" | "vtol" | "ground" | "other" | "unknown";
    simulation_targets: AgentCoreSimulationTarget[];
  };
}

export interface AgentCoreSimulationTarget {
  target_id: string;
  simulator: "gazebo-classic" | "gazebo-harmonic" | "isaac-sim" | "webots" | "other";
  simulator_version: string;
  ros_distribution: string | null;
  autopilot: "px4" | "ardupilot" | "none" | "other";
  entrypoint: string;
}

export interface AgentCoreAssetQualificationEvidence {
  schema_version: "dronedream.asset-qualification-evidence.v1";
  job_id: string;
  qualification_id: string;
  map_asset_id: string;
  map_content_sha256: string;
  vehicle_asset_id: string;
  vehicle_content_sha256: string;
  evidence_sha256: string;
  runtime_contracts: AgentCoreAssetPairRuntimeContracts;
  receipt: {
    schema_version: "dronedream.asset-pair-qualification-receipt.v1";
    qualification_id: string;
    status: "verified";
    map_asset_id: string;
    map_content_sha256: string;
    vehicle_asset_id: string;
    vehicle_content_sha256: string;
    environment_versions: Record<string, string>;
    runtime_evidence_sha256: string;
    plugin_snapshot?: {
      schema_version: "dronedream.plugin-snapshot.v1";
      snapshot_id: string;
      catalog_sha256: string;
      created_at: string;
      plugins: Array<{
        plugin_id: string;
        version: string;
        package_sha256: string;
        manifest_sha256: string;
        configuration_sha256: string;
        configuration: Record<string, unknown>;
        capability_ids: string[];
        manifest?: Record<string, unknown> | null;
        bundle_root: null;
      }>;
    } | null;
    plugin_snapshot_sha256?: string | null;
    plugin_checks?: Array<{
      check_id: string;
      plugin_id: string;
      capability_id: string;
      accepted: boolean;
      issue_codes: string[];
      details: Record<string, unknown>;
    }>;
    plugin_hook_receipts?: Array<Record<string, unknown>>;
    runtime_evidence: {
      schema_version?: string;
      status: "verified";
      gates: Record<string, boolean>;
      measurements?: Record<string, unknown>;
      artifacts?: Record<string, unknown>;
    };
    qualified_at: string;
    [key: string]: unknown;
  };
}

export interface AgentCoreModelEntry {
  id: string;
  model: string;
  label: string;
  provider: string;
  source: "default" | "custom";
  profile_id?: string;
}

export interface AgentCoreCustomModelProfile {
  profile_id: string;
  selection_id: string;
  display_name: string;
  provider: string;
  icon: string;
  base_url: string;
  api_style: "responses" | "chat-completions";
  model_id: string;
  enabled: boolean;
  has_api_key: boolean;
}

export interface AgentCoreCustomModelGrant {
  grant: string;
  expires_at: string;
}

export interface AgentCoreThread {
  thread_id: string;
  title: string;
  state: string;
  selected_model: string;
  selected_map_id: string | null;
  selected_map_content_sha256: string | null;
  selected_vehicle_id: string | null;
  selected_vehicle_content_sha256: string | null;
  pinned: boolean;
  archived: boolean;
  created_at: string;
  updated_at: string;
  messages?: Array<{
    message_id: string;
    sequence: number;
    role: "user" | "assistant" | "system";
    kind: "text" | "status" | "plan" | "error";
    content: string;
    metadata: Record<string, unknown>;
    created_at: string;
  }>;
}

export interface AgentCoreRuntimeStatus {
  distribution: string;
  runtime_available: boolean;
  resources_ready: boolean;
  provisioned: boolean;
  issue: string | null;
}

export interface AgentCoreExecutionReceipt {
  execution_id: string;
  state: "executing";
  run_dir: string;
  execution_root: string;
}

export interface AgentCoreExecutionEvidence {
  schema_version: "dronedream.agent-execution-evidence.v1";
  thread_id: string;
  execution_id: string;
  state: "executing" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  return_code?: number | null;
  result: null | {
    status: "verified" | "failed";
    contract_id: string;
    prepared_mission_sha256: string;
    workflow_result_sha256: string;
    workflow_evidence_chain_head: string;
    completion_assessment: {
      schema_version: "dronedream.completion-assessment.v1";
      accepted: boolean;
      issue_codes: string[];
    };
    gates: Record<string, boolean>;
    measurements: {
      pose_sample_count: number;
      ros_observation_rows: number;
      minimum_goal_distance_m: number | null;
      landing_state: string | null;
      abort_reason: string | null;
      executor_return_code: number | null;
      tolerated_landing_contact_samples: number;
      minimum_tolerated_landing_clearance_m: number | null;
    };
    artifact_hashes: Record<string, string | number>;
    checkpoint_decision_count: number;
    runtime_interruption_count: number;
    plugin_hook_receipt_count: number;
  };
}

export interface AgentCoreAttachment {
  attachment_id: string;
  thread_id: string;
  display_name: string;
  content_type: string;
  byte_size: number;
  created_at: string;
}

export interface AgentCoreAssetEntry {
  asset_id: string;
  kind: "map" | "vehicle";
  name: string;
  status: "qualified" | "draft" | "invalid";
  manifest: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AgentCoreAssetVersion {
  asset_id: string;
  content_sha256: string;
  kind: AgentCoreAssetKind;
  maturity: "visual_only" | "physics_ready" | "simulation_ready" | "flight_ready" | "qualified";
  manifest: Record<string, unknown>;
  asset_ir: Record<string, unknown>;
  imported_at: string;
}

export interface AgentCoreBootstrap {
  models: AgentCoreModelEntry[];
  threads: AgentCoreThread[];
  maps: AgentCoreAssetEntry[];
  vehicles: AgentCoreAssetEntry[];
  asset_import_jobs: AgentCoreAssetImportJob[];
  asset_versions: AgentCoreAssetVersion[];
  asset_qualification_jobs: AgentCoreAssetQualificationJob[];
  asset_source_adapters: AgentCoreAssetSourceAdapter[];
  plugins: AgentCorePluginEntry[];
  settings: Record<string, unknown>;
}

export interface AgentCoreMissionPrepareSummary {
  locale: "zh-CN" | "en-US";
  thread_id: string;
  mission_id: string;
  plan_revision_id: string;
  status: "awaiting_confirmation";
  contract_id: string;
  goal: string;
  target_entity: string;
  return_entity: string;
  planning_attempts: number;
  model_calls: number;
  model_selection_id: string;
  model_id: string;
  model_source: "default" | "custom";
  plugin_snapshot_id: string;
  plugin_catalog_sha256: string;
  route_nodes: string[];
  minimum_clearance_m: number;
  mission_plan: {
    schema_version: "dronedream.agent-core-mission-plan.v1";
    source: "agent-core";
    contract_id: string;
    prepared_mission_sha256: string;
    scene_id: string;
    scene_name: string;
    feasible: boolean;
    readiness: "simulation_ready";
    can_execute: boolean;
    requires_confirmation: true;
    perception_mode: "map" | "vision" | "fusion";
    asset_bindings: {
      map_asset_id: string;
      map_content_sha256: string;
      vehicle_asset_id: string;
      vehicle_content_sha256: string;
    };
    steps: Array<{
      order: number;
      action: string;
      label: string;
      payload_delta_kg: number;
    }>;
    task_graph: {
      schema_version: "dronedream.autonomy.task-graph.v1";
      revision: number;
      nodes: Array<{
        task_id: string;
        label: string;
        status: "pending" | "ready" | "active" | "blocked" | "completed" | "failed" | "skipped";
        depends_on: string[];
        executor: "language_model" | "mission_executive" | "perception" | "global_planner" | "local_planner" | "payload_controller" | "px4_bridge" | "operator";
        risk: "low" | "medium" | "high" | "critical";
        max_retries: number;
        timeout_s: number;
        fallback: "continue" | "hold" | "land" | "abort";
        expected_output: string;
        completion_evidence: string[];
        inserted_by: "compiler" | "runtime" | "operator";
      }>;
      active_node_ids: string[];
      change_reason: string;
    };
    issues: Array<{
      code: string;
      severity: "info" | "warning" | "error";
      message: string;
    }>;
    metrics: {
      route_length_m: number;
      vertical_travel_m: number;
      estimated_duration_s: number;
      minimum_clearance_m: number;
      launch_mass_kg: number | null;
      post_pickup_mass_kg: number | null;
      post_pickup_thrust_to_weight: number | null;
      braking_distance_m: number | null;
    };
    immutable_safety_rules: string[];
  };
  capability_broker_receipts: number;
  capability_broker_receipts_sha256: string;
  integration_artifact: AutonomyPlannerArtifact;
  integration_artifact_sha256: string;
  notifications?: Array<{ kind: "plan" | "status"; content: string; metadata?: Record<string, unknown> }>;
}

interface AgentCoreDesktopResponse {
  status: number;
  contentType: string | null;
  bodyBase64: string;
}

interface TauriCore {
  invoke(command: string, args?: Record<string, unknown>): Promise<unknown>;
}

export class AgentCoreUnavailableError extends Error {
  constructor() {
    super("AGENT Core is available in the DroneDream desktop application.");
    this.name = "AgentCoreUnavailableError";
  }
}

export class AgentCoreRequestError extends Error {
  readonly status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "AgentCoreRequestError";
    this.status = status;
  }
}

function tauriCore(): TauriCore | null {
  if (typeof window === "undefined") return null;
  const core = (window as Window & { __TAURI__?: { core?: TauriCore } }).__TAURI__?.core;
  return core && typeof core.invoke === "function" ? core : null;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const result = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) result[index] = binary.charCodeAt(index);
  return result;
}

function isDesktopResponse(value: unknown): value is AgentCoreDesktopResponse {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<AgentCoreDesktopResponse>;
  return Number.isInteger(candidate.status)
    && typeof candidate.bodyBase64 === "string"
    && (candidate.contentType === null || typeof candidate.contentType === "string");
}

function detailFromBody(body: Uint8Array): string {
  const text = new TextDecoder().decode(body);
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    // The Core may return a short plain-text diagnostic before JSON is available.
  }
  return text.trim() || "AGENT Core request failed.";
}

async function requestBytes(
  path: string,
  init: { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: Uint8Array; contentType?: string } = {},
): Promise<Uint8Array> {
  const core = tauriCore();
  if (!core) throw new AgentCoreUnavailableError();
  const value = await core.invoke("agent_core_request", {
    request: {
      method: init.method ?? "GET",
      path,
      bodyBase64: init.body ? bytesToBase64(init.body) : null,
      contentType: init.contentType ?? null,
    },
  });
  if (!isDesktopResponse(value)) throw new Error("AGENT Core returned an invalid desktop response.");
  const body = base64ToBytes(value.bodyBase64);
  if (value.status < 200 || value.status >= 300) {
    throw new AgentCoreRequestError(value.status, detailFromBody(body));
  }
  return body;
}

async function requestJson<T>(
  path: string,
  init: { method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; body?: unknown } = {},
): Promise<T> {
  const body = init.body === undefined
    ? undefined
    : new TextEncoder().encode(JSON.stringify(init.body));
  const bytes = await requestBytes(path, {
    method: init.method,
    body,
    contentType: body ? "application/json" : undefined,
  });
  return JSON.parse(new TextDecoder().decode(bytes)) as T;
}

function multipartFile(file: File, fieldName: string): { body: Uint8Array; contentType: string } {
  const boundary = `----DroneDreamAgent${crypto.randomUUID().replaceAll("-", "")}`;
  const safeName = file.name.replace(/[\r\n"\\]/gu, "_");
  const head = new TextEncoder().encode(
    `--${boundary}\r\nContent-Disposition: form-data; name="${fieldName}"; filename="${safeName}"\r\n`
      + `Content-Type: ${file.type || "application/octet-stream"}\r\n\r\n`,
  );
  const tail = new TextEncoder().encode(`\r\n--${boundary}--\r\n`);
  return {
    body: new Uint8Array(head.length + file.size + tail.length),
    contentType: `multipart/form-data; boundary=${boundary}`,
  };
}

async function multipartFileBytes(file: File, fieldName: string): Promise<{ body: Uint8Array; contentType: string }> {
  const value = multipartFile(file, fieldName);
  const boundary = value.contentType.slice("multipart/form-data; boundary=".length);
  const safeName = file.name.replace(/[\r\n"\\]/gu, "_");
  const head = new TextEncoder().encode(
    `--${boundary}\r\nContent-Disposition: form-data; name="${fieldName}"; filename="${safeName}"\r\n`
      + `Content-Type: ${file.type || "application/octet-stream"}\r\n\r\n`,
  );
  const fileBytes = new Uint8Array(await file.arrayBuffer());
  const tail = new TextEncoder().encode(`\r\n--${boundary}--\r\n`);
  value.body.set(head, 0);
  value.body.set(fileBytes, head.length);
  value.body.set(tail, head.length + fileBytes.length);
  return value;
}

export async function getAgentCoreStatus(): Promise<AgentCoreStatus> {
  const core = tauriCore();
  if (!core) throw new AgentCoreUnavailableError();
  const value = await core.invoke("agent_core_status");
  if (
    !value
    || typeof value !== "object"
    || typeof (value as { available?: unknown }).available !== "boolean"
    || typeof (value as { restarting?: unknown }).restarting !== "boolean"
  ) {
    throw new Error("AGENT Core status is invalid.");
  }
  return value as AgentCoreStatus;
}

export async function restartAgentCore(): Promise<AgentCoreStatus> {
  const core = tauriCore();
  if (!core) throw new AgentCoreUnavailableError();
  const value = await core.invoke("agent_core_restart");
  if (
    !value
    || typeof value !== "object"
    || (value as { available?: unknown }).available !== true
    || (value as { restarting?: unknown }).restarting !== false
  ) {
    throw new Error("AGENT Core restart did not return a ready status.");
  }
  return value as AgentCoreStatus;
}

export function getAgentCoreBootstrap(): Promise<AgentCoreBootstrap> {
  return requestJson("/v1/bootstrap");
}

export function createAgentCoreThread(payload: {
  title: string;
  selected_model: string;
}): Promise<AgentCoreThread> {
  return requestJson("/v1/threads", { method: "POST", body: payload });
}

export function getAgentCoreThread(threadId: string): Promise<AgentCoreThread> {
  return requestJson(`/v1/threads/${encodeURIComponent(threadId)}`);
}

export async function uploadAgentCoreAttachment(
  threadId: string,
  file: File,
): Promise<AgentCoreAttachment> {
  if (!file.name.trim() || file.size <= 0) throw new Error("AGENT_CORE_ATTACHMENT_EMPTY");
  if (file.size > 25 * 1024 * 1024) throw new Error("AGENT_CORE_ATTACHMENT_TOO_LARGE");
  const multipart = await multipartFileBytes(file, "attachment");
  const response = await requestBytes(
    `/v1/threads/${encodeURIComponent(threadId)}/attachments`,
    { method: "POST", body: multipart.body, contentType: multipart.contentType },
  );
  return JSON.parse(new TextDecoder().decode(response)) as AgentCoreAttachment;
}

export function patchAgentCoreThread(
  threadId: string,
  payload: Partial<Pick<AgentCoreThread,
    | "title"
    | "selected_model"
    | "selected_map_id"
    | "selected_map_content_sha256"
    | "selected_vehicle_id"
    | "selected_vehicle_content_sha256"
    | "pinned"
    | "archived"
  >>,
): Promise<AgentCoreThread> {
  return requestJson(`/v1/threads/${encodeURIComponent(threadId)}`, {
    method: "PATCH",
    body: payload,
  });
}

export function prepareAgentCoreMission(
  threadId: string,
  payload: {
    message: string;
    map_id: string;
    map_content_sha256: string;
    vehicle_id: string;
    vehicle_content_sha256: string;
    model_id: string;
    model_grant: string;
    gateway_base_url: string | null;
    locale: "zh-CN" | "en-US";
    start_entity: string;
    attachment_ids?: string[];
    role_models?: Array<Record<string, unknown>>;
    input_channel?: "text" | "voice" | "camera" | "api" | "webhook" | "scheduled";
    input_metadata?: Record<string, unknown>;
  },
): Promise<AgentCoreMissionPrepareSummary> {
  return requestJson(`/v1/threads/${encodeURIComponent(threadId)}/prepare`, {
    method: "POST",
    body: payload,
  });
}

export function createAgentCoreCustomModel(payload: {
  display_name: string;
  base_url: string;
  model_id: string;
  api_key: string;
  api_style: "responses" | "chat-completions";
  provider?: string;
}): Promise<AgentCoreCustomModelProfile> {
  return requestJson("/v1/custom-models", { method: "POST", body: payload });
}

export function testAgentCoreCustomModel(profileId: string): Promise<{
  ok: boolean;
  provider: string;
  model_id: string;
  model_count: number;
}> {
  return requestJson(`/v1/custom-models/${encodeURIComponent(profileId)}/test`, { method: "POST" });
}

export function deleteAgentCoreCustomModel(profileId: string): Promise<{
  deleted: true;
  profile_id: string;
}> {
  return requestJson(`/v1/custom-models/${encodeURIComponent(profileId)}`, { method: "DELETE" });
}

export function issueAgentCoreCustomModelGrant(
  profileId: string,
  threadId: string,
): Promise<AgentCoreCustomModelGrant> {
  const query = new URLSearchParams({ thread_id: threadId });
  return requestJson(
    `/v1/custom-models/${encodeURIComponent(profileId)}/grants?${query.toString()}`,
    { method: "POST" },
  );
}

export function submitAgentCoreRuntimeMessage(
  threadId: string,
  text: string,
): Promise<Record<string, unknown>> {
  return requestJson(`/v1/threads/${encodeURIComponent(threadId)}/runtime-message`, {
    method: "POST",
    body: { text },
  });
}

export function getAgentCoreRuntimeStatus(): Promise<AgentCoreRuntimeStatus> {
  return requestJson("/v1/runtime/status");
}

export function executeAgentCoreMission(
  threadId: string,
  payload: {
    model_id: string;
    model_grant: string;
    gateway_base_url: string | null;
  },
): Promise<AgentCoreExecutionReceipt> {
  return requestJson(`/v1/threads/${encodeURIComponent(threadId)}/execute`, {
    method: "POST",
    body: payload,
  });
}

export function getAgentCoreExecutionEvidence(
  threadId: string,
): Promise<AgentCoreExecutionEvidence> {
  return requestJson(`/v1/threads/${encodeURIComponent(threadId)}/execution-evidence`);
}

export function listAgentCoreAssetSourceAdapters(): Promise<AgentCoreAssetSourceAdapter[]> {
  return requestJson("/v1/asset-source-adapters");
}

export function listAgentCoreAssetImportJobs(): Promise<AgentCoreAssetImportJob[]> {
  return requestJson("/v1/asset-import-jobs");
}

export function createAgentCoreRemoteAssetImportJob(payload: {
  source_type: "direct_url" | "git";
  location: string;
  source_format?: string;
  expected_kind: AgentCoreAssetKind;
  expected_sha256?: string;
  git_ref?: string;
  subpath?: string;
}): Promise<AgentCoreAssetImportJob> {
  return requestJson("/v1/asset-import-jobs/remote", {
    method: "POST",
    body: { source_format: "auto", ...payload },
  });
}

export function getAgentCoreAssetImportJobIssues(jobId: string): Promise<AgentCoreAssetIssueReport> {
  return requestJson(`/v1/asset-import-jobs/${encodeURIComponent(jobId)}/issues`);
}

export async function pickAndCreateAgentCoreAssetImportJob(
  expectedKind: AgentCoreAssetKind,
  sourceKind: "file" | "directory" = "file",
  locale: "zh-CN" | "en-US" = "en-US",
  adapters: AgentCoreAssetSourceAdapter[] = [],
): Promise<AgentCoreAssetImportJob | null> {
  if (!tauriCore()) throw new AgentCoreUnavailableError();
  const chinese = locale === "zh-CN";
  const extensions = Array.from(new Set(
    adapters
      .filter((adapter) => adapter.asset_kinds.includes(expectedKind))
      .flatMap((adapter) => adapter.file_extensions)
      .map((extension) => extension.replace(/^\./u, "").toLowerCase())
      .filter((extension) => /^[a-z0-9]+$/u.test(extension)),
  )).sort();
  const selection = await open({
    multiple: false,
    directory: sourceKind === "directory",
    title: expectedKind === "vehicle"
      ? sourceKind === "directory"
        ? chinese ? "导入无人机资产文件夹" : "Import vehicle asset directory"
        : chinese ? "导入无人机资产" : "Import vehicle asset"
      : sourceKind === "directory"
        ? chinese ? "导入地图或世界文件夹" : "Import map or world directory"
        : chinese ? "导入地图或世界资产" : "Import map or world asset",
    filters: sourceKind === "file" && extensions.length
      ? [{ name: chinese ? "可用的三维资产" : "Supported 3D assets", extensions }]
      : undefined,
  });
  if (!selection || Array.isArray(selection)) return null;
  const core = tauriCore();
  if (!core) throw new AgentCoreUnavailableError();
  const response = await core.invoke("agent_core_import_asset_path", {
    request: {
      filePath: selection,
      sourceFormat: "auto",
      expectedKind,
    },
  });
  if (!isDesktopResponse(response)) throw new Error("AGENT Core returned an invalid asset response.");
  const body = base64ToBytes(response.bodyBase64);
  if (response.status < 200 || response.status >= 300) {
    throw new AgentCoreRequestError(response.status, detailFromBody(body));
  }
  return JSON.parse(new TextDecoder().decode(body)) as AgentCoreAssetImportJob;
}

export function processAgentCoreAssetImportJob(jobId: string): Promise<AgentCoreAssetImportJob> {
  return requestJson(`/v1/asset-import-jobs/${encodeURIComponent(jobId)}/process`, { method: "POST" });
}

export async function pickAndSubmitAgentCoreCompanionResult(
  job: AgentCoreAssetImportJob,
  locale: "zh-CN" | "en-US" = "en-US",
): Promise<AgentCoreAssetImportJob | null> {
  if (!job.package_sha256 || !job.source_adapter_id) {
    throw new Error("The import job is missing its source binding.");
  }
  if (!tauriCore()) throw new AgentCoreUnavailableError();
  const chinese = locale === "zh-CN";
  const selection = await open({
    multiple: false,
    directory: false,
    title: chinese ? "选择已转换的 DroneDream 资产包" : "Select the converted DroneDream package",
    filters: [{ name: chinese ? "DroneDream 资产包" : "DroneDream package", extensions: ["ddpkg", "zip"] }],
  });
  if (!selection || Array.isArray(selection)) return null;
  const core = tauriCore();
  if (!core) throw new AgentCoreUnavailableError();
  const response = await core.invoke("agent_core_submit_companion_result_path", {
    request: {
      jobId: job.job_id,
      filePath: selection,
      sourcePackageSha256: job.package_sha256,
      adapterId: job.source_adapter_id,
    },
  });
  if (!isDesktopResponse(response)) {
    throw new Error("AGENT Core returned an invalid companion result response.");
  }
  const body = base64ToBytes(response.bodyBase64);
  if (response.status < 200 || response.status >= 300) {
    throw new AgentCoreRequestError(response.status, detailFromBody(body));
  }
  return JSON.parse(new TextDecoder().decode(body)) as AgentCoreAssetImportJob;
}

export function cancelAgentCoreAssetImportJob(jobId: string): Promise<AgentCoreAssetImportJob> {
  return requestJson(`/v1/asset-import-jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

export function listAgentCoreAssetQualificationJobs(): Promise<AgentCoreAssetQualificationJob[]> {
  return requestJson("/v1/asset-qualification-jobs");
}

export function getAgentCoreAssetQualificationJob(jobId: string): Promise<AgentCoreAssetQualificationJob> {
  return requestJson(`/v1/asset-qualification-jobs/${encodeURIComponent(jobId)}`);
}

export function getAgentCoreAssetQualificationJobIssues(jobId: string): Promise<AgentCoreAssetIssueReport> {
  return requestJson(`/v1/asset-qualification-jobs/${encodeURIComponent(jobId)}/issues`);
}

export function getAgentCoreAssetQualificationEvidence(jobId: string): Promise<AgentCoreAssetQualificationEvidence> {
  return requestJson(`/v1/asset-qualification-jobs/${encodeURIComponent(jobId)}/evidence`);
}

export function createAgentCoreAssetQualificationJob(payload: {
  map_asset_id: string;
  map_content_sha256: string;
  vehicle_asset_id: string;
  vehicle_content_sha256: string;
}): Promise<AgentCoreAssetQualificationJob> {
  return requestJson("/v1/asset-qualification-jobs", { method: "POST", body: payload });
}

export function startAgentCoreAssetQualificationJob(jobId: string): Promise<AgentCoreAssetQualificationJob> {
  return requestJson(`/v1/asset-qualification-jobs/${encodeURIComponent(jobId)}/start`, { method: "POST" });
}

export function pauseAgentCoreAssetQualificationJob(jobId: string): Promise<AgentCoreAssetQualificationJob> {
  return requestJson(`/v1/asset-qualification-jobs/${encodeURIComponent(jobId)}/pause`, { method: "POST" });
}

export function cancelAgentCoreAssetQualificationJob(jobId: string): Promise<AgentCoreAssetQualificationJob> {
  return requestJson(`/v1/asset-qualification-jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
}

export function listAgentCorePlugins(): Promise<AgentCorePluginEntry[]> {
  return requestJson<AgentCorePluginEntry[]>("/v1/plugins");
}

export function getAgentCoreHarnessCatalog(): Promise<AgentCoreHarnessCatalog> {
  return requestJson("/v1/harness/catalog");
}

export function getAgentCoreHarnessProfiles(): Promise<AgentCoreHarnessProfile[]> {
  return requestJson("/v1/harness/profiles");
}

export function getAgentCoreHarnessState(): Promise<AgentCoreHarnessState> {
  return requestJson("/v1/harness/topologies/current");
}

export function editAgentCoreHarness(
  operation: AgentCoreHarnessOperation,
): Promise<{ revision: AgentCoreHarnessRevision; receipt: Record<string, unknown> }> {
  return requestJson("/v1/harness/topologies/current", { method: "PATCH", body: operation });
}

export function undoAgentCoreHarness(
  baseRevision: number,
): Promise<{ revision: AgentCoreHarnessRevision; receipt: Record<string, unknown> }> {
  return requestJson("/v1/harness/topologies/undo", {
    method: "POST",
    body: { base_revision: baseRevision },
  });
}

export function redoAgentCoreHarness(
  baseRevision: number,
): Promise<{ revision: AgentCoreHarnessRevision; receipt: Record<string, unknown> }> {
  return requestJson("/v1/harness/topologies/redo", {
    method: "POST",
    body: { base_revision: baseRevision },
  });
}

export function dryRunAgentCoreHarness(
  candidate?: AgentCoreHarnessCandidate,
): Promise<AgentCoreHarnessDryRun> {
  return requestJson("/v1/harness/topologies/dry-run", {
    method: "POST",
    body: candidate,
  });
}

export function listAgentCoreHarnessReceipts(
  limit = 100,
): Promise<Array<Record<string, unknown>>> {
  return requestJson(`/v1/harness/receipts?limit=${Math.max(1, Math.min(limit, 500))}`);
}

export function setAgentCorePlugin(pluginId: string, enabled: boolean): Promise<unknown> {
  return requestJson(`/v1/plugins/${encodeURIComponent(pluginId)}/${enabled ? "enable" : "disable"}`, { method: "POST" });
}

export function healthcheckAgentCorePlugin(pluginId: string): Promise<unknown> {
  return requestJson(`/v1/plugins/${encodeURIComponent(pluginId)}/healthcheck`, { method: "POST" });
}

export function trustAgentCorePlugin(pluginId: string): Promise<unknown> {
  return requestJson(`/v1/plugins/${encodeURIComponent(pluginId)}/trust-local-package`, { method: "POST" });
}

export function revokeAgentCorePlugin(pluginId: string): Promise<unknown> {
  return requestJson(`/v1/plugins/${encodeURIComponent(pluginId)}/revoke-package`, { method: "POST" });
}

export function uninstallAgentCorePlugin(pluginId: string): Promise<unknown> {
  return requestJson(`/v1/plugins/${encodeURIComponent(pluginId)}`, { method: "DELETE" });
}

export async function importAgentCorePlugin(file: File): Promise<unknown> {
  const multipart = await multipartFileBytes(file, "bundle");
  const response = await requestBytes("/v1/plugins/import", {
    method: "POST",
    body: multipart.body,
    contentType: multipart.contentType,
  });
  return JSON.parse(new TextDecoder().decode(response)) as unknown;
}

export function getAgentCorePluginGovernance(): Promise<{ policy: AgentCorePluginGovernancePolicy }> {
  return requestJson("/v1/plugin-governance");
}

export function replaceAgentCorePluginGovernance(policy: AgentCorePluginGovernancePolicy): Promise<unknown> {
  return requestJson("/v1/plugin-governance", { method: "PUT", body: policy });
}

export function getAgentCorePluginMarketplace(): Promise<AgentCorePluginMarketplaceCatalog> {
  return requestJson("/v1/plugin-marketplace");
}

export function replaceAgentCorePluginMarketplaceSources(
  sources: AgentCorePluginMarketplaceSource[],
): Promise<unknown> {
  return requestJson("/v1/plugin-marketplace/sources", { method: "PUT", body: sources });
}

export function installAgentCoreMarketplacePlugin(
  sourceId: string,
  pluginId: string,
  version: string,
): Promise<unknown> {
  return requestJson("/v1/plugin-marketplace/install", {
    method: "POST",
    body: { source_id: sourceId, plugin_id: pluginId, version },
  });
}
