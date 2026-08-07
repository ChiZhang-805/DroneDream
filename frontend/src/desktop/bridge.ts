export interface WindowsInfo {
  caption: string;
  version: string;
  buildNumber: string;
  architecture: string;
}

export interface WslDistribution {
  name: string;
  version: number | null;
  isDefault: boolean;
}

export interface WslInfo {
  executableAvailable: boolean;
  distributions: WslDistribution[];
}

export interface MemoryInfo {
  totalBytes: number;
  availableBytes: number;
}

export interface DiskInfo {
  drive: string;
  totalBytes: number;
  freeBytes: number;
  isSystemDrive: boolean;
}

export interface GpuInfo {
  name: string;
  driverVersion: string | null;
  adapterRamBytes: number | null;
}

export interface SystemPrerequisiteReport {
  platform: string;
  supported: boolean;
  windows: WindowsInfo | null;
  wsl: WslInfo;
  memory: MemoryInfo | null;
  disks: DiskInfo[];
  gpus: GpuInfo[];
  probeErrors: string[];
}

export type RuntimeComponentState =
  | "ready"
  | "missing"
  | "stopped"
  | "unhealthy"
  | "unknown";

export interface RuntimeComponentStatus {
  id: string;
  label: string;
  status: RuntimeComponentState;
  required: boolean;
  version?: string | null;
  detail?: string | null;
}

export interface RuntimeStatusReport {
  runtimeName: string;
  installed: boolean;
  running: boolean;
  ready: boolean;
  version?: string | null;
  dataRoot?: string | null;
  components: RuntimeComponentStatus[];
  diagnostics: string[];
}

export interface EnginePackStatus {
  supported: boolean;
  updateRequired: boolean;
  embeddedPackId: string;
  embeddedSourceCommit: string;
  installedPackId: string | null;
  installedSourceCommit: string | null;
  message: string | null;
}

export interface FieldTuningStatus {
  schemaVersion: 1;
  kind: "dronedream-field-tuning-status";
  editionId: "field";
  executionDomain: "real-hardware";
  runtimeProfile: "field-lightweight";
  sourceCommit: string;
  enginePackId: string;
  contractSha256: string;
  simulationSupported: false;
  modelRole: "proposal-only";
  harnessRole: "bounded-execution-evidence-and-rollback";
  demoAvailable: boolean;
  hardwareAuthority: false;
  validatedPackCount: number;
  blockers: string[];
}

export interface FieldDiscoveredDevice {
  observationId: string;
  portName: string;
  registryValueNameSha256: string;
  transport: "windows-serial-registry-readonly";
  portOpened: false;
  validationStatus: "unknown-unvalidated";
  hardwareAuthority: false;
}

export interface FieldDeviceDiscoveryReport {
  schemaVersion: 1;
  kind: "dronedream-field-device-discovery-report";
  editionId: "field";
  source: "windows-serial-registry-readonly";
  supported: boolean;
  portOpenAttempts: 0;
  writeAttempts: 0;
  hardwareAuthority: false;
  devices: FieldDiscoveredDevice[];
  diagnostics: string[];
}

export interface FieldTuningDemoRequest {
  objective: string;
  maxIterations: number;
  targetScore: number;
}

export interface FieldTuningCandidateReceipt {
  iteration: number;
  proposalSource: "deterministic-model-fixture";
  parameters: Record<string, number>;
  candidateSha256: string;
  trackingError: number;
  overshootPercent: number;
  controlEffort: number;
  score: number;
  accepted: boolean;
  failureClass: "none";
}

export interface FieldTuningDemoReceipt {
  schemaVersion: 1;
  kind: "dronedream-field-tuning-demo-receipt";
  jobId: string;
  editionId: "field";
  executionDomain: "real-hardware";
  executionMode: "fixture-only-no-device-io";
  sourceCommit: string;
  enginePackId: string;
  objective: string;
  budget: {
    maxIterations: number;
    usedIterations: number;
    providerRequests: 0;
    hardwareTrials: 0;
  };
  candidates: FieldTuningCandidateReceipt[];
  selectedCandidateSha256: string;
  holdout: { independent: true; score: number; passed: boolean; fixture: true };
  qualification: {
    status: "demo-qualified" | "demo-rejected";
    hardwareValid: false;
    reason: string;
  };
  hardwareActionsPerformed: string[];
  hardwareAuthority: false;
  receiptSha256: string;
}

export interface FieldHardwareTuningRequest {
  deviceId: string;
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  objective: string;
}

export interface FieldHardwareTuningPlan {
  schemaVersion: 1;
  kind: "dronedream-field-hardware-tuning-plan";
  editionId: "field";
  executionDomain: "real-hardware";
  requestSha256: string;
  canExecute: false;
  hardwareAuthority: false;
  requiredEvidence: string[];
  blockers: string[];
}

export interface DesktopApiRequest {
  method: "GET" | "POST" | "PATCH" | "DELETE";
  path: string;
  body?: string | null;
  accessToken?: string | null;
  accept?: "application/json" | "application/octet-stream" | "text/csv";
  idempotencyKey?: string | null;
}

export interface DesktopApiResponse {
  status: number;
  contentType: string | null;
  bodyBase64: string;
}

export interface DesktopArtifactDownloadRequest {
  artifactId: string;
  filename: string;
  accessToken?: string | null;
}

export interface DesktopArtifactDownloadResponse {
  savedPath: string;
  bytes: number;
}

export interface BrowserAuthRequest {
  locale: InstallerLocale;
}

export interface BrowserAuthSession {
  protocolVersion: "desktop-browser-auth-pkce-v1";
  editionId: "universal" | "sim" | "lab" | "field";
  authClientId: string;
  accessToken: string;
  refreshToken: string;
  attemptIdHash: string;
  stateHash: string;
  subjectHash: string;
  issuedAt: string;
  completedAt: string;
}

export interface DistributionPlanSelection {
  schemaVersion: 1;
  editionId: string;
  region: string;
  vehiclePackId: string;
  controllerKey: string | null;
  optionalModules: string[];
}

export interface DistributionPlanRollbackReference {
  installationId: string;
  manifestSha256: string;
  sourceCommit: string;
}

export interface DistributionPlanRequest {
  selection: DistributionPlanSelection;
  rollbackReference: DistributionPlanRollbackReference | null;
}

export interface DistributionPlanValidation {
  schemaVersion: 1;
  kind: "dronedream-distribution-plan-validation";
  planVersion: "1.0.0";
  productDisplayVersion: "1.0.0";
  sourceCommit: string;
  sourceTreeClean: boolean;
  planSha256: string;
  selection: DistributionPlanSelection;
  catalog: {
    registryManifestSha256: string;
    capabilityPolicySha256: string;
    editionManifestSha256: string;
    vehiclePackManifestSha256: string;
    vehiclePackPayloadSha256: string;
    vehiclePackSignatureState: string;
    validationTier: string;
  };
  requiredModules: string[];
  optionalModules: string[];
  capabilities: {
    defaultDecision: "deny";
    frontendIsAuthority: false;
    enabledOrConditioned: string[];
    denied: string[];
  };
  rollback: {
    status: "missing" | "reference-only";
    reference: DistributionPlanRollbackReference | null;
  };
  blockers: string[];
  canApply: false;
  executionAuthorized: false;
}

export interface RuntimeInstallStep {
  id: string;
  title: string;
  description: string;
  requiresAdministrator: boolean;
  destructive: boolean;
  estimatedBytes?: number | null;
}

export interface RuntimeInstallPlan {
  runtimeName: string;
  targetRoot: string;
  estimatedDownloadBytes: number;
  estimatedInstalledBytes: number;
  requiresAdministrator: boolean;
  requiresRestart: boolean;
  canInstall: boolean;
  blockers: string[];
  steps: RuntimeInstallStep[];
}

export type RuntimeInstallPhase =
  | "idle"
  | "queued"
  | "verifyingManifest"
  | "downloading"
  | "verifyingArchive"
  | "importing"
  | "starting"
  | "healthChecking"
  | "waitingForRestart"
  | "completed"
  | "failed"
  | "cancelled";

export interface RuntimeInstallError {
  code: string;
  message: string;
  retryable: boolean;
  diagnosticsPath: string | null;
}

export interface RuntimeInstallSnapshot {
  operationId: string | null;
  phase: RuntimeInstallPhase;
  bytesDownloaded: number;
  bytesTotal: number | null;
  currentPart: number | null;
  totalParts: number | null;
  message: string | null;
  error: RuntimeInstallError | null;
  resumable: boolean;
  requiresRestart: boolean;
  targetRoot: string | null;
  installedVersion: string | null;
  updatedAt: string | null;
}

export interface RuntimeInstallRequest {
  targetRoot: string;
  releaseManifestUrl?: string | null;
}

export type InstallerRuntimeDisposition =
  | "none"
  | "desktopOnly"
  | "started"
  | "resumed"
  | "invalid"
  | "alreadyInstalled";

export type InstallerRuntimeMode =
  | "install-all"
  | "custom"
  | "install-app-only";

export type InstallerRuntimeIntentStatus =
  | "none"
  | "ready"
  | "desktopOnly"
  | "invalid";

export interface InstallerRuntimeIntent {
  status: InstallerRuntimeIntentStatus;
  mode: InstallerRuntimeMode | null;
  targetRoot: string | null;
  message: string | null;
}

export interface InstallerRuntimeAutoStartResult {
  disposition: InstallerRuntimeDisposition;
  mode: InstallerRuntimeMode | null;
  targetRoot: string | null;
  snapshot: RuntimeInstallSnapshot | null;
  message: string | null;
}

export interface InstallerRuntimeDiscardResult {
  discarded: boolean;
  message: string | null;
}

interface TauriCore {
  invoke(command: string, args?: Record<string, unknown>): Promise<unknown>;
}

export interface DesktopCloseRequestedEvent {
  preventDefault(): void;
}

export interface DesktopWindowHandle {
  onCloseRequested(
    handler: (event: DesktopCloseRequestedEvent) => void | Promise<void>,
  ): Promise<() => void>;
  destroy(): Promise<void>;
}

interface TauriWindowApi {
  getCurrentWindow(): DesktopWindowHandle;
}

interface TauriGlobal {
  core?: TauriCore;
  window?: TauriWindowApi;
}

type UnknownRecord = Record<string, unknown>;

const RUNTIME_NAME = "DroneDreamRuntime";
const REQUIRED_RUNTIME_COMPONENT_IDS = [
  "wsl-runtime",
  "host-ownership",
  "runtime-manifest",
  "local-backend",
  "px4",
  "gazebo",
] as const;
const REQUIRED_INSTALL_STEP_IDS = [
  "preflight",
  "enable-wsl",
  "download",
  "import",
  "smoke-test",
] as const;

const COMPONENT_STATES = new Set<RuntimeComponentState>([
  "ready",
  "missing",
  "stopped",
  "unhealthy",
  "unknown",
]);
const INSTALL_PHASES = new Set<RuntimeInstallPhase>([
  "idle",
  "queued",
  "verifyingManifest",
  "downloading",
  "verifyingArchive",
  "importing",
  "starting",
  "healthChecking",
  "waitingForRestart",
  "completed",
  "failed",
  "cancelled",
]);
const INSTALLER_RUNTIME_DISPOSITIONS = new Set<InstallerRuntimeDisposition>([
  "none",
  "desktopOnly",
  "started",
  "resumed",
  "invalid",
  "alreadyInstalled",
]);
const INSTALLER_RUNTIME_MODES = new Set<InstallerRuntimeMode>([
  "install-all",
  "custom",
  "install-app-only",
]);
const INSTALLER_RUNTIME_INTENT_STATUSES = new Set<InstallerRuntimeIntentStatus>([
  "none",
  "ready",
  "desktopOnly",
  "invalid",
]);

declare global {
  interface Window {
    __TAURI__?: TauriGlobal;
  }
}

function getTauriCore(): TauriCore | null {
  if (typeof window === "undefined") return null;
  const core = window.__TAURI__?.core;
  return core && typeof core.invoke === "function" ? core : null;
}

export function getDesktopWindowHandle(): DesktopWindowHandle | null {
  if (typeof window === "undefined") return null;
  const windowApi = window.__TAURI__?.window;
  if (!windowApi || typeof windowApi.getCurrentWindow !== "function") return null;
  try {
    const handle = windowApi.getCurrentWindow();
    return handle &&
      typeof handle.onCloseRequested === "function" &&
      typeof handle.destroy === "function"
      ? handle
      : null;
  } catch {
    return null;
  }
}

export class DesktopRuntimeUnavailableError extends Error {
  constructor() {
    super("DroneDream desktop commands are unavailable in this browser.");
    this.name = "DesktopRuntimeUnavailableError";
  }
}

export class DesktopCommandContractError extends Error {
  readonly command: string;

  constructor(command: string, detail: string) {
    super(`${command} returned an invalid response: ${detail}`);
    this.name = "DesktopCommandContractError";
    this.command = command;
  }
}

async function invokeDesktop<T>(
  command: string,
  parse: (value: unknown) => T,
  args?: Record<string, unknown>,
): Promise<T> {
  const core = getTauriCore();
  if (!core) throw new DesktopRuntimeUnavailableError();
  const value = await core.invoke(command, args);
  try {
    return parse(value);
  } catch (error) {
    if (error instanceof DesktopCommandContractError) throw error;
    throw new DesktopCommandContractError(command, contractErrorMessage(error));
  }
}

export function isDesktopRuntime(): boolean {
  return getTauriCore() !== null;
}

export type InstallerLocale = "en" | "zh-CN";

export function getInstallerLocale(): Promise<InstallerLocale> {
  return invokeDesktop("get_installer_locale", (value) => {
    if (value === "en" || value === "zh-CN") return value;
    throw new Error("installer locale must be en or zh-CN");
  });
}

export function getFieldTuningStatus(): Promise<FieldTuningStatus> {
  return invokeDesktop("get_field_tuning_status", parseFieldTuningStatus);
}

export function discoverFieldDevices(): Promise<FieldDeviceDiscoveryReport> {
  return invokeDesktop("discover_field_devices", parseFieldDeviceDiscoveryReport);
}

export function runFieldTuningDemo(
  request: FieldTuningDemoRequest,
): Promise<FieldTuningDemoReceipt> {
  if (
    request.objective.trim() === "" ||
    request.objective.length > 120 ||
    !Number.isInteger(request.maxIterations) ||
    request.maxIterations < 2 ||
    request.maxIterations > 8 ||
    !Number.isFinite(request.targetScore) ||
    request.targetScore < 0.15 ||
    request.targetScore > 0.9
  ) {
    return Promise.reject(new Error("Field tuning demo request is outside its bounded contract."));
  }
  return invokeDesktop("run_field_tuning_demo", parseFieldTuningDemoReceipt, { request });
}

export function prepareFieldHardwareTuning(
  request: FieldHardwareTuningRequest,
): Promise<FieldHardwareTuningPlan> {
  for (const value of Object.values(request)) {
    if (value.trim() === "" || value.length > 160) {
      return Promise.reject(new Error("Field hardware tuning request is invalid."));
    }
  }
  return invokeDesktop("prepare_field_hardware_tuning", parseFieldHardwareTuningPlan, {
    request,
  });
}

export function beginBrowserAuth(
  request: BrowserAuthRequest,
): Promise<BrowserAuthSession> {
  const normalizedRequest = {
    locale: request.locale,
  };
  if (normalizedRequest.locale !== "en" && normalizedRequest.locale !== "zh-CN") {
    return Promise.reject(new Error("Browser sign-in locale must be en or zh-CN."));
  }
  return invokeDesktop(
    "begin_browser_auth",
    parseBrowserAuthSession,
    { request: normalizedRequest },
  );
}

export function cancelBrowserAuth(): Promise<boolean> {
  return invokeDesktop("cancel_browser_auth", (value) =>
    expectBoolean(value, "response"));
}

export function clearBrowserAuthVault(): Promise<boolean> {
  return invokeDesktop("clear_browser_auth_vault", (value) =>
    expectBoolean(value, "response"),
  );
}

export function restoreBrowserAuthVault(): Promise<BrowserAuthSession | null> {
  return invokeDesktop("restore_browser_auth_vault", (value) =>
    value === null ? null : parseBrowserAuthSession(value),
  );
}

export function validateDistributionPlan(
  request: DistributionPlanRequest,
): Promise<DistributionPlanValidation> {
  const normalizedRequest = parseDistributionPlanRequest(request, "request");
  return invokeDesktop(
    "validate_distribution_plan",
    (value) => parseDistributionPlanValidation(value, normalizedRequest),
    { request: normalizedRequest },
  );
}

export function probeSystemPrerequisites(): Promise<SystemPrerequisiteReport> {
  return invokeDesktop("probe_system_prerequisites", parsePrerequisiteReport);
}

export function probeRuntimeStatus(): Promise<RuntimeStatusReport> {
  return invokeDesktop("probe_runtime_status", parseRuntimeStatus);
}

export function getEnginePackStatus(): Promise<EnginePackStatus> {
  return invokeDesktop("get_engine_pack_status", parseEnginePackStatus);
}

export function ensureAppUpdateIdle(): Promise<void> {
  return invokeDesktop("ensure_app_update_idle", () => undefined);
}

export function installEmbeddedEnginePack(): Promise<EnginePackStatus> {
  return invokeDesktop("install_embedded_engine_pack", parseEnginePackStatus);
}

export async function getRuntimeInstallPlan(
  targetRoot?: string,
): Promise<RuntimeInstallPlan> {
  const expectedTargetRoot = targetRoot == null
    ? undefined
    : normalizeRequestedTargetRoot(targetRoot);
  return invokeDesktop(
    "get_runtime_install_plan",
    (value) => parseInstallPlan(value, expectedTargetRoot),
    expectedTargetRoot ? { targetRoot: expectedTargetRoot } : undefined,
  );
}

export function startRuntimeInstall(
  request: RuntimeInstallRequest,
): Promise<RuntimeInstallSnapshot> {
  const normalizedRequest = normalizeRuntimeInstallRequest(request);
  return invokeDesktop(
    "start_runtime_install",
    parseRuntimeInstallSnapshot,
    { request: normalizedRequest },
  );
}

export function getRuntimeInstallProgress(): Promise<RuntimeInstallSnapshot> {
  return invokeDesktop(
    "get_runtime_install_progress",
    parseRuntimeInstallSnapshot,
  );
}

export function cancelRuntimeInstall(): Promise<RuntimeInstallSnapshot> {
  return invokeDesktop(
    "cancel_runtime_install",
    parseRuntimeInstallSnapshot,
  );
}

export function autoStartInstallerRuntime(): Promise<InstallerRuntimeAutoStartResult> {
  return invokeDesktop(
    "auto_start_installer_runtime",
    parseInstallerRuntimeAutoStartResult,
  );
}

export function getInstallerRuntimeIntent(): Promise<InstallerRuntimeIntent> {
  return invokeDesktop(
    "get_installer_runtime_intent",
    parseInstallerRuntimeIntent,
  );
}

export function discardInstallerRuntimeIntent(): Promise<InstallerRuntimeDiscardResult> {
  return invokeDesktop(
    "discard_installer_runtime_intent",
    parseInstallerRuntimeDiscardResult,
  );
}

export function startRuntime(): Promise<RuntimeStatusReport> {
  return invokeDesktop("start_runtime", parseRuntimeStatus);
}

export function repairRuntime(): Promise<RuntimeStatusReport> {
  return invokeDesktop("repair_runtime", parseRuntimeStatus);
}

export function stopRuntimeForExit(): Promise<void> {
  return invokeDesktop("stop_runtime_for_exit", (value) => {
    if (value !== null) {
      throw new Error("stop_runtime_for_exit must return null");
    }
  });
}

export function desktopApiRequest(
  request: DesktopApiRequest,
): Promise<DesktopApiResponse> {
  if (!request.path.startsWith("/api/v1/")) {
    return Promise.reject(
      new Error("Desktop API paths must remain inside /api/v1/."),
    );
  }
  return invokeDesktop(
    "desktop_api_request",
    parseDesktopApiResponse,
    { request },
  );
}

export function desktopDownloadArtifact(
  request: DesktopArtifactDownloadRequest,
): Promise<DesktopArtifactDownloadResponse> {
  return invokeDesktop(
    "desktop_download_artifact",
    parseDesktopArtifactDownloadResponse,
    { request },
  );
}

function parseBrowserAuthSession(value: unknown): BrowserAuthSession {
  const record = expectExactRecord(value, "response", [
    "protocolVersion",
    "editionId",
    "authClientId",
    "accessToken",
    "refreshToken",
    "attemptIdHash",
    "stateHash",
    "subjectHash",
    "issuedAt",
    "completedAt",
  ]);
  if (record.protocolVersion !== "desktop-browser-auth-pkce-v1") {
    throw new Error("response.protocolVersion is unsupported");
  }
  if (!(["universal", "sim", "lab", "field"] as unknown[]).includes(record.editionId)) {
    throw new Error("response.editionId is unsupported");
  }
  const issuedAt = expectIsoTimestamp(record.issuedAt, "response.issuedAt");
  const completedAt = expectIsoTimestamp(record.completedAt, "response.completedAt");
  if (Date.parse(completedAt) < Date.parse(issuedAt)) {
    throw new Error("response.completedAt must not precede response.issuedAt");
  }
  return {
    protocolVersion: "desktop-browser-auth-pkce-v1",
    editionId: record.editionId as BrowserAuthSession["editionId"],
    authClientId: expectIdentifier(record.authClientId, "response.authClientId"),
    accessToken: expectBrowserAuthToken(
      record.accessToken,
      "response.accessToken",
    ),
    refreshToken: expectBrowserAuthToken(
      record.refreshToken,
      "response.refreshToken",
    ),
    attemptIdHash: expectLowercaseHex(
      record.attemptIdHash,
      "response.attemptIdHash",
      64,
    ),
    stateHash: expectLowercaseHex(record.stateHash, "response.stateHash", 64),
    subjectHash: expectLowercaseHex(record.subjectHash, "response.subjectHash", 64),
    issuedAt,
    completedAt,
  };
}

function parseDistributionPlanSelection(
  value: unknown,
  path: string,
): DistributionPlanSelection {
  const record = expectExactRecord(value, path, [
    "schemaVersion",
    "editionId",
    "region",
    "vehiclePackId",
    "controllerKey",
    "optionalModules",
  ]);
  if (record.schemaVersion !== 1) {
    throw new Error(`${path}.schemaVersion must equal 1`);
  }
  const selection: DistributionPlanSelection = {
    schemaVersion: 1,
    editionId: expectIdentifier(record.editionId, `${path}.editionId`),
    region: expectIdentifier(record.region, `${path}.region`),
    vehiclePackId: expectIdentifier(record.vehiclePackId, `${path}.vehiclePackId`),
    controllerKey: record.controllerKey == null
      ? null
      : expectControllerKey(record.controllerKey, `${path}.controllerKey`),
    optionalModules: parseIdentifierArray(
      record.optionalModules,
      `${path}.optionalModules`,
    ),
  };
  if (selection.optionalModules.length > 64) {
    throw new Error(`${path}.optionalModules exceeds the bounded module count`);
  }
  return selection;
}

function parseDistributionRollbackReference(
  value: unknown,
  path: string,
): DistributionPlanRollbackReference {
  const record = expectExactRecord(value, path, [
    "installationId",
    "manifestSha256",
    "sourceCommit",
  ]);
  const installationId = expectSafeNonEmptyString(
    record.installationId,
    `${path}.installationId`,
  );
  if (!/^[A-Za-z0-9_.:-]{1,128}$/u.test(installationId)) {
    throw new Error(`${path}.installationId is malformed`);
  }
  return {
    installationId,
    manifestSha256: expectLowercaseHex(
      record.manifestSha256,
      `${path}.manifestSha256`,
      64,
    ),
    sourceCommit: expectLowercaseHex(
      record.sourceCommit,
      `${path}.sourceCommit`,
      40,
    ),
  };
}

function parseDistributionPlanRequest(
  value: unknown,
  path: string,
): DistributionPlanRequest {
  const record = expectExactRecord(value, path, ["selection", "rollbackReference"]);
  return {
    selection: parseDistributionPlanSelection(record.selection, `${path}.selection`),
    rollbackReference: record.rollbackReference == null
      ? null
      : parseDistributionRollbackReference(
          record.rollbackReference,
          `${path}.rollbackReference`,
        ),
  };
}

function parseDistributionPlanValidation(
  value: unknown,
  request: DistributionPlanRequest,
): DistributionPlanValidation {
  const record = expectExactRecord(value, "response", [
    "schemaVersion",
    "kind",
    "planVersion",
    "productDisplayVersion",
    "sourceCommit",
    "sourceTreeClean",
    "planSha256",
    "selection",
    "catalog",
    "requiredModules",
    "optionalModules",
    "capabilities",
    "rollback",
    "blockers",
    "canApply",
    "executionAuthorized",
  ]);
  if (
    record.schemaVersion !== 1
    || record.kind !== "dronedream-distribution-plan-validation"
    || record.planVersion !== "1.0.0"
    || record.productDisplayVersion !== "1.0.0"
  ) {
    throw new Error("response distribution plan identity is unsupported");
  }
  const selection = parseDistributionPlanSelection(record.selection, "response.selection");
  if (JSON.stringify(selection) !== JSON.stringify(request.selection)) {
    throw new Error("response.selection must exactly match the requested selection");
  }

  const catalogRecord = expectExactRecord(record.catalog, "response.catalog", [
    "registryManifestSha256",
    "capabilityPolicySha256",
    "editionManifestSha256",
    "vehiclePackManifestSha256",
    "vehiclePackPayloadSha256",
    "vehiclePackSignatureState",
    "validationTier",
  ]);
  const catalog = {
    registryManifestSha256: expectLowercaseHex(
      catalogRecord.registryManifestSha256,
      "response.catalog.registryManifestSha256",
      64,
    ),
    capabilityPolicySha256: expectLowercaseHex(
      catalogRecord.capabilityPolicySha256,
      "response.catalog.capabilityPolicySha256",
      64,
    ),
    editionManifestSha256: expectLowercaseHex(
      catalogRecord.editionManifestSha256,
      "response.catalog.editionManifestSha256",
      64,
    ),
    vehiclePackManifestSha256: expectLowercaseHex(
      catalogRecord.vehiclePackManifestSha256,
      "response.catalog.vehiclePackManifestSha256",
      64,
    ),
    vehiclePackPayloadSha256: expectLowercaseHex(
      catalogRecord.vehiclePackPayloadSha256,
      "response.catalog.vehiclePackPayloadSha256",
      64,
    ),
    vehiclePackSignatureState: expectSafeNonEmptyString(
      catalogRecord.vehiclePackSignatureState,
      "response.catalog.vehiclePackSignatureState",
    ),
    validationTier: expectSafeNonEmptyString(
      catalogRecord.validationTier,
      "response.catalog.validationTier",
    ),
  };

  const capabilityRecord = expectExactRecord(
    record.capabilities,
    "response.capabilities",
    ["defaultDecision", "frontendIsAuthority", "enabledOrConditioned", "denied"],
  );
  if (capabilityRecord.defaultDecision !== "deny" || capabilityRecord.frontendIsAuthority !== false) {
    throw new Error("response capability decision must remain native deny-by-default");
  }
  const enabledOrConditioned = parseIdentifierArray(
    capabilityRecord.enabledOrConditioned,
    "response.capabilities.enabledOrConditioned",
  );
  const denied = parseIdentifierArray(
    capabilityRecord.denied,
    "response.capabilities.denied",
  );
  if (
    selection.editionId === "sim"
    && !["hardware.arm", "hardware.flight", "hardware.parameter.write"]
      .every((capability) => denied.includes(capability))
  ) {
    throw new Error("response Sim plan must deny every physical flight authority");
  }

  const rollbackRecord = expectExactRecord(record.rollback, "response.rollback", [
    "status",
    "reference",
  ]);
  const rollbackReference = rollbackRecord.reference == null
    ? null
    : parseDistributionRollbackReference(
        rollbackRecord.reference,
        "response.rollback.reference",
      );
  if (
    (request.rollbackReference === null
      && (rollbackRecord.status !== "missing" || rollbackReference !== null))
    || (request.rollbackReference !== null
      && (
        rollbackRecord.status !== "reference-only"
        || JSON.stringify(rollbackReference) !== JSON.stringify(request.rollbackReference)
      ))
  ) {
    throw new Error("response.rollback must preserve the structural rollback reference");
  }

  const requiredModules = parseIdentifierArray(record.requiredModules, "response.requiredModules");
  const optionalModules = parseIdentifierArray(record.optionalModules, "response.optionalModules");
  if (!optionalModules.every((moduleId) => selection.optionalModules.includes(moduleId))) {
    throw new Error("response.optionalModules must be a validated subset of the request");
  }
  const blockers = parseIdentifierArray(record.blockers, "response.blockers");
  if (!blockers.includes("native-apply-not-implemented")) {
    throw new Error("response must preserve the native apply implementation blocker");
  }
  if (record.canApply !== false || record.executionAuthorized !== false) {
    throw new Error("response must never authorize apply or execution in preview mode");
  }
  const sourceTreeClean = expectBoolean(record.sourceTreeClean, "response.sourceTreeClean");
  if (blockers.includes("source-tree-dirty-at-build") === sourceTreeClean) {
    throw new Error("response source tree state must agree with its dirty-build blocker");
  }

  return {
    schemaVersion: 1,
    kind: "dronedream-distribution-plan-validation",
    planVersion: "1.0.0",
    productDisplayVersion: "1.0.0",
    sourceCommit: expectLowercaseHex(record.sourceCommit, "response.sourceCommit", 40),
    sourceTreeClean,
    planSha256: expectLowercaseHex(record.planSha256, "response.planSha256", 64),
    selection,
    catalog,
    requiredModules,
    optionalModules,
    capabilities: {
      defaultDecision: "deny",
      frontendIsAuthority: false,
      enabledOrConditioned,
      denied,
    },
    rollback: {
      status: rollbackRecord.status as "missing" | "reference-only",
      reference: rollbackReference,
    },
    blockers,
    canApply: false,
    executionAuthorized: false,
  };
}

function expectBrowserAuthToken(value: unknown, path: string): string {
  const token = expectString(value, path);
  if (
    token.length === 0 ||
    token.length > 16 * 1024 ||
    /\s/u.test(token) ||
    [...token].some((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint < 32 || codePoint === 127;
    })
  ) {
    throw new Error(`${path} must be a bounded non-empty token`);
  }
  return token;
}

function parseDesktopArtifactDownloadResponse(
  value: unknown,
): DesktopArtifactDownloadResponse {
  const record = expectRecord(value, "response");
  return {
    savedPath: expectSafeNonEmptyString(record.savedPath, "response.savedPath"),
    bytes: expectNonNegativeInteger(record.bytes, "response.bytes"),
  };
}

function parseDesktopApiResponse(value: unknown): DesktopApiResponse {
  const record = expectRecord(value, "response");
  const status = expectNonNegativeInteger(record.status, "response.status");
  if (status < 100 || status > 599) {
    throw new Error("response.status must be an HTTP status");
  }
  const bodyBase64 = expectString(record.bodyBase64, "response.bodyBase64");
  if (
    bodyBase64.length % 4 !== 0 ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
      bodyBase64,
    )
  ) {
    throw new Error("response.bodyBase64 must be canonical base64");
  }
  return {
    status,
    contentType: expectNullableString(
      record.contentType,
      "response.contentType",
    ),
    bodyBase64,
  };
}

function parsePrerequisiteReport(value: unknown): SystemPrerequisiteReport {
  const record = expectRecord(value, "report");
  return {
    platform: expectString(record.platform, "report.platform"),
    supported: expectBoolean(record.supported, "report.supported"),
    windows: record.windows == null ? null : parseWindowsInfo(record.windows),
    wsl: parseWslInfo(record.wsl),
    memory: record.memory == null ? null : parseMemoryInfo(record.memory),
    disks: expectArray(record.disks, "report.disks").map((disk, index) =>
      parseDiskInfo(disk, `report.disks[${index}]`),
    ),
    gpus: expectArray(record.gpus, "report.gpus").map((gpu, index) =>
      parseGpuInfo(gpu, `report.gpus[${index}]`),
    ),
    probeErrors: parseStringArray(record.probeErrors, "report.probeErrors"),
  };
}

function parseWindowsInfo(value: unknown): WindowsInfo {
  const record = expectRecord(value, "report.windows");
  return {
    caption: expectString(record.caption, "report.windows.caption"),
    version: expectString(record.version, "report.windows.version"),
    buildNumber: expectString(record.buildNumber, "report.windows.buildNumber"),
    architecture: expectString(record.architecture, "report.windows.architecture"),
  };
}

function parseWslInfo(value: unknown): WslInfo {
  const record = expectRecord(value, "report.wsl");
  return {
    executableAvailable: expectBoolean(
      record.executableAvailable,
      "report.wsl.executableAvailable",
    ),
    distributions: expectArray(record.distributions, "report.wsl.distributions").map(
      (distribution, index) => {
        const item = expectRecord(
          distribution,
          `report.wsl.distributions[${index}]`,
        );
        return {
          name: expectString(item.name, `report.wsl.distributions[${index}].name`),
          version: item.version == null
            ? null
            : expectNonNegativeInteger(
                item.version,
                `report.wsl.distributions[${index}].version`,
              ),
          isDefault: expectBoolean(
            item.isDefault,
            `report.wsl.distributions[${index}].isDefault`,
          ),
        };
      },
    ),
  };
}

function parseMemoryInfo(value: unknown): MemoryInfo {
  const record = expectRecord(value, "report.memory");
  const memory = {
    totalBytes: expectNonNegativeNumber(record.totalBytes, "report.memory.totalBytes"),
    availableBytes: expectNonNegativeNumber(
      record.availableBytes,
      "report.memory.availableBytes",
    ),
  };
  if (memory.availableBytes > memory.totalBytes) {
    throw new Error("report.memory.availableBytes cannot exceed totalBytes");
  }
  return memory;
}

function parseDiskInfo(value: unknown, path: string): DiskInfo {
  const record = expectRecord(value, path);
  const disk = {
    drive: expectString(record.drive, `${path}.drive`),
    totalBytes: expectNonNegativeNumber(record.totalBytes, `${path}.totalBytes`),
    freeBytes: expectNonNegativeNumber(record.freeBytes, `${path}.freeBytes`),
    isSystemDrive: expectBoolean(record.isSystemDrive, `${path}.isSystemDrive`),
  };
  if (disk.freeBytes > disk.totalBytes) {
    throw new Error(`${path}.freeBytes cannot exceed totalBytes`);
  }
  return disk;
}

function parseGpuInfo(value: unknown, path: string): GpuInfo {
  const record = expectRecord(value, path);
  return {
    name: expectString(record.name, `${path}.name`),
    driverVersion: expectNullableString(record.driverVersion, `${path}.driverVersion`),
    adapterRamBytes: record.adapterRamBytes == null
      ? null
      : expectNonNegativeNumber(record.adapterRamBytes, `${path}.adapterRamBytes`),
  };
}

function parseRuntimeStatus(value: unknown): RuntimeStatusReport {
  const record = expectRecord(value, "report");
  const components = expectArray(record.components, "report.components").map(
    (component, index) => parseRuntimeComponent(component, index),
  );
  assertUnique(components.map((component) => component.id), "report.components ids");
  const report: RuntimeStatusReport = {
    runtimeName: expectString(record.runtimeName, "report.runtimeName"),
    installed: expectBoolean(record.installed, "report.installed"),
    running: expectBoolean(record.running, "report.running"),
    ready: expectBoolean(record.ready, "report.ready"),
    version: expectNullableString(record.version, "report.version"),
    dataRoot: expectNullableString(record.dataRoot, "report.dataRoot"),
    components,
    diagnostics: parseStringArray(record.diagnostics, "report.diagnostics"),
  };
  validateRuntimeSemantics(report);
  return report;
}

function parseEnginePackStatus(value: unknown): EnginePackStatus {
  const record = expectRecord(value, "enginePack");
  const status: EnginePackStatus = {
    supported: expectBoolean(record.supported, "enginePack.supported"),
    updateRequired: expectBoolean(record.updateRequired, "enginePack.updateRequired"),
    embeddedPackId: expectSafeNonEmptyString(
      record.embeddedPackId,
      "enginePack.embeddedPackId",
    ),
    embeddedSourceCommit: expectSafeNonEmptyString(
      record.embeddedSourceCommit,
      "enginePack.embeddedSourceCommit",
    ),
    installedPackId: expectNullableSafeNonEmptyString(
      record.installedPackId,
      "enginePack.installedPackId",
    ),
    installedSourceCommit: expectNullableSafeNonEmptyString(
      record.installedSourceCommit,
      "enginePack.installedSourceCommit",
    ),
    message: expectNullableString(record.message, "enginePack.message"),
  };
  const packIdPattern = /^sha256:[0-9a-f]{64}$/;
  const commitPattern = /^[0-9a-f]{40}$/;
  if (!packIdPattern.test(status.embeddedPackId)) {
    throw new Error("enginePack.embeddedPackId must be a SHA-256 identity");
  }
  if (!commitPattern.test(status.embeddedSourceCommit)) {
    throw new Error("enginePack.embeddedSourceCommit must be a full Git commit");
  }
  if (status.installedPackId && !packIdPattern.test(status.installedPackId)) {
    throw new Error("enginePack.installedPackId must be a SHA-256 identity");
  }
  if (
    status.installedSourceCommit &&
    !commitPattern.test(status.installedSourceCommit)
  ) {
    throw new Error("enginePack.installedSourceCommit must be a full Git commit");
  }
  if (!status.supported && !status.updateRequired) {
    throw new Error("an unsupported Engine Pack manager must require a Runtime Base update");
  }
  return status;
}

function parseFieldTuningStatus(value: unknown): FieldTuningStatus {
  const record = expectRecord(value, "fieldTuningStatus");
  const status: FieldTuningStatus = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, "fieldTuningStatus.schemaVersion"),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-tuning-status",
      "fieldTuningStatus.kind",
    ),
    editionId: expectLiteral(record.editionId, "field", "fieldTuningStatus.editionId"),
    executionDomain: expectLiteral(
      record.executionDomain,
      "real-hardware",
      "fieldTuningStatus.executionDomain",
    ),
    runtimeProfile: expectLiteral(
      record.runtimeProfile,
      "field-lightweight",
      "fieldTuningStatus.runtimeProfile",
    ),
    sourceCommit: expectLowercaseHex(record.sourceCommit, "fieldTuningStatus.sourceCommit", 40),
    enginePackId: expectSha256Id(record.enginePackId, "fieldTuningStatus.enginePackId"),
    contractSha256: expectLowercaseHex(
      record.contractSha256,
      "fieldTuningStatus.contractSha256",
      64,
    ),
    simulationSupported: expectLiteral(
      record.simulationSupported,
      false,
      "fieldTuningStatus.simulationSupported",
    ),
    modelRole: expectLiteral(record.modelRole, "proposal-only", "fieldTuningStatus.modelRole"),
    harnessRole: expectLiteral(
      record.harnessRole,
      "bounded-execution-evidence-and-rollback",
      "fieldTuningStatus.harnessRole",
    ),
    demoAvailable: expectBoolean(record.demoAvailable, "fieldTuningStatus.demoAvailable"),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldTuningStatus.hardwareAuthority",
    ),
    validatedPackCount: expectNonNegativeInteger(
      record.validatedPackCount,
      "fieldTuningStatus.validatedPackCount",
    ),
    blockers: parseSafeNonEmptyStringArray(record.blockers, "fieldTuningStatus.blockers"),
  };
  const zeroPackBlocked = status.blockers.includes("field.registry.zero-validated-packs");
  if (
    status.blockers.length === 0
    || status.blockers.includes("field.device.transport-unavailable") === false
    || status.blockers.includes("field.quorum.missing") === false
    || zeroPackBlocked !== (status.validatedPackCount === 0)
  ) {
    throw new Error("Field tuning status weakened its source-bound safety denial");
  }
  return status;
}

function parseFieldDeviceDiscoveryReport(value: unknown): FieldDeviceDiscoveryReport {
  const record = expectRecord(value, "fieldDeviceDiscovery");
  const devices = expectArray(record.devices, "fieldDeviceDiscovery.devices").map(
    (item, index): FieldDiscoveredDevice => {
      const path = `fieldDeviceDiscovery.devices[${index}]`;
      const device = expectRecord(item, path);
      return {
        observationId: expectLowercaseHex(device.observationId, `${path}.observationId`, 64),
        portName: expectCanonicalComPort(device.portName, `${path}.portName`),
        registryValueNameSha256: expectLowercaseHex(
          device.registryValueNameSha256,
          `${path}.registryValueNameSha256`,
          64,
        ),
        transport: expectLiteral(
          device.transport,
          "windows-serial-registry-readonly",
          `${path}.transport`,
        ),
        portOpened: expectLiteral(device.portOpened, false, `${path}.portOpened`),
        validationStatus: expectLiteral(
          device.validationStatus,
          "unknown-unvalidated",
          `${path}.validationStatus`,
        ),
        hardwareAuthority: expectLiteral(
          device.hardwareAuthority,
          false,
          `${path}.hardwareAuthority`,
        ),
      };
    },
  );
  const report: FieldDeviceDiscoveryReport = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, "fieldDeviceDiscovery.schemaVersion"),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-device-discovery-report",
      "fieldDeviceDiscovery.kind",
    ),
    editionId: expectLiteral(record.editionId, "field", "fieldDeviceDiscovery.editionId"),
    source: expectLiteral(
      record.source,
      "windows-serial-registry-readonly",
      "fieldDeviceDiscovery.source",
    ),
    supported: expectBoolean(record.supported, "fieldDeviceDiscovery.supported"),
    portOpenAttempts: expectLiteral(
      record.portOpenAttempts,
      0,
      "fieldDeviceDiscovery.portOpenAttempts",
    ),
    writeAttempts: expectLiteral(record.writeAttempts, 0, "fieldDeviceDiscovery.writeAttempts"),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldDeviceDiscovery.hardwareAuthority",
    ),
    devices,
    diagnostics: parseSafeNonEmptyStringArray(
      record.diagnostics,
      "fieldDeviceDiscovery.diagnostics",
    ),
  };
  if (new Set(devices.map((device) => device.portName)).size !== devices.length) {
    throw new Error("fieldDeviceDiscovery devices must use unique ports");
  }
  return report;
}

function parseFieldTuningCandidate(
  value: unknown,
  index: number,
): FieldTuningCandidateReceipt {
  const path = `fieldTuningReceipt.candidates[${index}]`;
  const record = expectRecord(value, path);
  const rawParameters = expectRecord(record.parameters, `${path}.parameters`);
  const parameters = Object.fromEntries(
    Object.entries(rawParameters).map(([name, parameter]) => [
      name,
      expectFiniteNumber(parameter, `${path}.parameters.${name}`),
    ]),
  );
  if (Object.keys(parameters).length === 0) throw new Error(`${path}.parameters must not be empty`);
  return {
    iteration: expectPositiveInteger(record.iteration, `${path}.iteration`),
    proposalSource: expectLiteral(
      record.proposalSource,
      "deterministic-model-fixture",
      `${path}.proposalSource`,
    ),
    parameters,
    candidateSha256: expectLowercaseHex(record.candidateSha256, `${path}.candidateSha256`, 64),
    trackingError: expectFiniteNumber(record.trackingError, `${path}.trackingError`),
    overshootPercent: expectFiniteNumber(record.overshootPercent, `${path}.overshootPercent`),
    controlEffort: expectFiniteNumber(record.controlEffort, `${path}.controlEffort`),
    score: expectFiniteNumber(record.score, `${path}.score`),
    accepted: expectBoolean(record.accepted, `${path}.accepted`),
    failureClass: expectLiteral(record.failureClass, "none", `${path}.failureClass`),
  };
}

function parseFieldTuningDemoReceipt(value: unknown): FieldTuningDemoReceipt {
  const record = expectRecord(value, "fieldTuningReceipt");
  const budget = expectRecord(record.budget, "fieldTuningReceipt.budget");
  const holdout = expectRecord(record.holdout, "fieldTuningReceipt.holdout");
  const qualification = expectRecord(record.qualification, "fieldTuningReceipt.qualification");
  const status = expectString(qualification.status, "fieldTuningReceipt.qualification.status");
  if (status !== "demo-qualified" && status !== "demo-rejected") {
    throw new Error("fieldTuningReceipt.qualification.status is unsupported");
  }
  const receipt: FieldTuningDemoReceipt = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, "fieldTuningReceipt.schemaVersion"),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-tuning-demo-receipt",
      "fieldTuningReceipt.kind",
    ),
    jobId: expectSafeNonEmptyString(record.jobId, "fieldTuningReceipt.jobId"),
    editionId: expectLiteral(record.editionId, "field", "fieldTuningReceipt.editionId"),
    executionDomain: expectLiteral(
      record.executionDomain,
      "real-hardware",
      "fieldTuningReceipt.executionDomain",
    ),
    executionMode: expectLiteral(
      record.executionMode,
      "fixture-only-no-device-io",
      "fieldTuningReceipt.executionMode",
    ),
    sourceCommit: expectLowercaseHex(record.sourceCommit, "fieldTuningReceipt.sourceCommit", 40),
    enginePackId: expectSha256Id(record.enginePackId, "fieldTuningReceipt.enginePackId"),
    objective: expectSafeNonEmptyString(record.objective, "fieldTuningReceipt.objective"),
    budget: {
      maxIterations: expectPositiveInteger(budget.maxIterations, "fieldTuningReceipt.budget.maxIterations"),
      usedIterations: expectPositiveInteger(budget.usedIterations, "fieldTuningReceipt.budget.usedIterations"),
      providerRequests: expectLiteral(budget.providerRequests, 0, "fieldTuningReceipt.budget.providerRequests"),
      hardwareTrials: expectLiteral(budget.hardwareTrials, 0, "fieldTuningReceipt.budget.hardwareTrials"),
    },
    candidates: expectArray(record.candidates, "fieldTuningReceipt.candidates")
      .map(parseFieldTuningCandidate),
    selectedCandidateSha256: expectLowercaseHex(
      record.selectedCandidateSha256,
      "fieldTuningReceipt.selectedCandidateSha256",
      64,
    ),
    holdout: {
      independent: expectLiteral(holdout.independent, true, "fieldTuningReceipt.holdout.independent"),
      score: expectFiniteNumber(holdout.score, "fieldTuningReceipt.holdout.score"),
      passed: expectBoolean(holdout.passed, "fieldTuningReceipt.holdout.passed"),
      fixture: expectLiteral(holdout.fixture, true, "fieldTuningReceipt.holdout.fixture"),
    },
    qualification: {
      status,
      hardwareValid: expectLiteral(
        qualification.hardwareValid,
        false,
        "fieldTuningReceipt.qualification.hardwareValid",
      ),
      reason: expectSafeNonEmptyString(
        qualification.reason,
        "fieldTuningReceipt.qualification.reason",
      ),
    },
    hardwareActionsPerformed: parseStringArray(
      record.hardwareActionsPerformed,
      "fieldTuningReceipt.hardwareActionsPerformed",
    ),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldTuningReceipt.hardwareAuthority",
    ),
    receiptSha256: expectLowercaseHex(record.receiptSha256, "fieldTuningReceipt.receiptSha256", 64),
  };
  if (
    receipt.candidates.length !== receipt.budget.usedIterations ||
    receipt.hardwareActionsPerformed.length !== 0 ||
    !receipt.candidates.some((candidate) => candidate.candidateSha256 === receipt.selectedCandidateSha256)
  ) {
    throw new Error("Field tuning receipt violates its bounded fixture semantics");
  }
  return receipt;
}

function parseFieldHardwareTuningPlan(value: unknown): FieldHardwareTuningPlan {
  const record = expectRecord(value, "fieldHardwarePlan");
  const plan: FieldHardwareTuningPlan = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, "fieldHardwarePlan.schemaVersion"),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-hardware-tuning-plan",
      "fieldHardwarePlan.kind",
    ),
    editionId: expectLiteral(record.editionId, "field", "fieldHardwarePlan.editionId"),
    executionDomain: expectLiteral(
      record.executionDomain,
      "real-hardware",
      "fieldHardwarePlan.executionDomain",
    ),
    requestSha256: expectLowercaseHex(record.requestSha256, "fieldHardwarePlan.requestSha256", 64),
    canExecute: expectLiteral(record.canExecute, false, "fieldHardwarePlan.canExecute"),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldHardwarePlan.hardwareAuthority",
    ),
    requiredEvidence: parseSafeNonEmptyStringArray(
      record.requiredEvidence,
      "fieldHardwarePlan.requiredEvidence",
    ),
    blockers: parseSafeNonEmptyStringArray(record.blockers, "fieldHardwarePlan.blockers"),
  };
  if (plan.blockers.length === 0 || plan.requiredEvidence.length < 8) {
    throw new Error("Field hardware plan removed mandatory safety evidence");
  }
  return plan;
}

function validateRuntimeSemantics(report: RuntimeStatusReport): void {
  if (report.runtimeName !== RUNTIME_NAME) {
    throw new Error(`report.runtimeName must equal ${RUNTIME_NAME}`);
  }

  const requiredIds = report.components
    .filter((component) => component.required)
    .map((component) => component.id);
  const requiredIdSet = new Set(requiredIds);
  if (REQUIRED_RUNTIME_COMPONENT_IDS.some((id) => !requiredIdSet.has(id))) {
    throw new Error(
      `report.components must mark all known runtime components as required: ${REQUIRED_RUNTIME_COMPONENT_IDS.join(", ")}`,
    );
  }

  const hasDataRoot = typeof report.dataRoot === "string" && report.dataRoot.trim() !== "";
  if (report.installed !== hasDataRoot) {
    throw new Error(
      "report.dataRoot must be non-empty exactly when the runtime is installed",
    );
  }
  if (report.running && !report.installed) {
    throw new Error("report.running cannot be true when report.installed is false");
  }
  if (report.ready && (!report.installed || !report.running)) {
    throw new Error("report.ready requires an installed and running runtime");
  }
  if (report.ready) {
    if (typeof report.version !== "string" || report.version.trim() === "") {
      throw new Error("report.ready requires a non-empty runtime version");
    }
    const nonReadyRequired = report.components.find(
      (component) => component.required && component.status !== "ready",
    );
    if (nonReadyRequired) {
      throw new Error(
        `report.ready cannot be true while required component ${nonReadyRequired.id} is ${nonReadyRequired.status}`,
      );
    }
  }
}

function parseRuntimeComponent(value: unknown, index: number): RuntimeComponentStatus {
  const path = `report.components[${index}]`;
  const record = expectRecord(value, path);
  const status = expectString(record.status, `${path}.status`);
  if (!COMPONENT_STATES.has(status as RuntimeComponentState)) {
    throw new Error(`${path}.status has the unknown value ${JSON.stringify(status)}`);
  }
  return {
    id: expectString(record.id, `${path}.id`),
    label: expectString(record.label, `${path}.label`),
    status: status as RuntimeComponentState,
    required: expectBoolean(record.required, `${path}.required`),
    version: expectNullableString(record.version, `${path}.version`),
    detail: expectNullableString(record.detail, `${path}.detail`),
  };
}

function parseInstallPlan(
  value: unknown,
  expectedTargetRoot?: string,
): RuntimeInstallPlan {
  const record = expectRecord(value, "plan");
  const steps = expectArray(record.steps, "plan.steps").map((step, index) =>
    parseInstallStep(step, index),
  );
  assertUnique(steps.map((step) => step.id), "plan.steps ids");
  const plan: RuntimeInstallPlan = {
    runtimeName: expectSafeNonEmptyString(record.runtimeName, "plan.runtimeName"),
    targetRoot: expectCanonicalRuntimeTargetRoot(record.targetRoot, "plan.targetRoot"),
    estimatedDownloadBytes: expectNonNegativeNumber(
      record.estimatedDownloadBytes,
      "plan.estimatedDownloadBytes",
    ),
    estimatedInstalledBytes: expectNonNegativeNumber(
      record.estimatedInstalledBytes,
      "plan.estimatedInstalledBytes",
    ),
    requiresAdministrator: expectBoolean(
      record.requiresAdministrator,
      "plan.requiresAdministrator",
    ),
    requiresRestart: expectBoolean(record.requiresRestart, "plan.requiresRestart"),
    canInstall: expectBoolean(record.canInstall, "plan.canInstall"),
    blockers: parseSafeNonEmptyStringArray(record.blockers, "plan.blockers"),
    steps,
  };
  if (plan.runtimeName !== RUNTIME_NAME) {
    throw new Error(`plan.runtimeName must equal ${RUNTIME_NAME}`);
  }
  if (expectedTargetRoot && plan.targetRoot !== expectedTargetRoot) {
    throw new Error(
      `plan.targetRoot must match the requested target ${expectedTargetRoot}`,
    );
  }
  if (
    plan.steps.length !== REQUIRED_INSTALL_STEP_IDS.length ||
    REQUIRED_INSTALL_STEP_IDS.some((id, index) => plan.steps[index]?.id !== id)
  ) {
    throw new Error(
      `plan.steps must contain ${REQUIRED_INSTALL_STEP_IDS.join(", ")} in that order`,
    );
  }
  if (plan.canInstall !== (plan.blockers.length === 0)) {
    throw new Error("plan.canInstall must be true exactly when plan.blockers is empty");
  }
  const enableWslStep = plan.steps.find((step) => step.id === "enable-wsl");
  if (enableWslStep?.requiresAdministrator !== plan.requiresAdministrator) {
    throw new Error(
      "plan.requiresAdministrator must match the enable-wsl step",
    );
  }
  const unexpectedAdministratorStep = plan.steps.find(
    (step) => step.id !== "enable-wsl" && step.requiresAdministrator,
  );
  if (unexpectedAdministratorStep) {
    throw new Error(
      `plan step ${unexpectedAdministratorStep.id} cannot require administrator approval`,
    );
  }
  return plan;
}

function parseInstallStep(value: unknown, index: number): RuntimeInstallStep {
  const path = `plan.steps[${index}]`;
  const record = expectRecord(value, path);
  return {
    id: expectSafeNonEmptyString(record.id, `${path}.id`),
    title: expectSafeNonEmptyString(record.title, `${path}.title`),
    description: expectSafeNonEmptyString(record.description, `${path}.description`),
    requiresAdministrator: expectBoolean(
      record.requiresAdministrator,
      `${path}.requiresAdministrator`,
    ),
    destructive: expectBoolean(record.destructive, `${path}.destructive`),
    estimatedBytes: record.estimatedBytes == null
      ? null
      : expectNonNegativeNumber(record.estimatedBytes, `${path}.estimatedBytes`),
  };
}

function normalizeRuntimeInstallRequest(
  request: RuntimeInstallRequest,
): Required<RuntimeInstallRequest> {
  const targetRoot = normalizeRequestedTargetRoot(request.targetRoot);
  const releaseManifestUrl = request.releaseManifestUrl == null
    ? null
    : normalizeReleaseManifestUrl(request.releaseManifestUrl);
  return { targetRoot, releaseManifestUrl };
}

function normalizeReleaseManifestUrl(value: string): string {
  const urlString = expectSafeNonEmptyString(value, "releaseManifestUrl");
  let url: URL;
  try {
    url = new URL(urlString);
  } catch {
    throw new Error("releaseManifestUrl must be an absolute HTTPS URL");
  }
  if (url.protocol !== "https:" || url.username !== "" || url.password !== "") {
    throw new Error("releaseManifestUrl must be an absolute HTTPS URL without credentials");
  }
  return url.toString();
}

function parseRuntimeInstallSnapshot(value: unknown): RuntimeInstallSnapshot {
  const record = expectRecord(value, "snapshot");
  const phase = expectString(record.phase, "snapshot.phase");
  if (!INSTALL_PHASES.has(phase as RuntimeInstallPhase)) {
    throw new Error(`snapshot.phase has the unknown value ${JSON.stringify(phase)}`);
  }
  const currentPart = record.currentPart == null
    ? null
    : expectNonNegativeInteger(record.currentPart, "snapshot.currentPart");
  const totalParts = record.totalParts == null
    ? null
    : expectNonNegativeInteger(record.totalParts, "snapshot.totalParts");
  const snapshot: RuntimeInstallSnapshot = {
    operationId: expectNullableSafeNonEmptyString(
      record.operationId,
      "snapshot.operationId",
    ),
    phase: phase as RuntimeInstallPhase,
    bytesDownloaded: expectNonNegativeNumber(
      record.bytesDownloaded,
      "snapshot.bytesDownloaded",
    ),
    bytesTotal: record.bytesTotal == null
      ? null
      : expectNonNegativeNumber(record.bytesTotal, "snapshot.bytesTotal"),
    currentPart,
    totalParts,
    message: expectNullableSafeNonEmptyString(record.message, "snapshot.message"),
    error: record.error == null ? null : parseRuntimeInstallError(record.error),
    resumable: expectBoolean(record.resumable, "snapshot.resumable"),
    requiresRestart: expectBoolean(
      record.requiresRestart,
      "snapshot.requiresRestart",
    ),
    targetRoot: record.targetRoot == null
      ? null
      : expectCanonicalRuntimeTargetRoot(record.targetRoot, "snapshot.targetRoot"),
    installedVersion: expectNullableSafeNonEmptyString(
      record.installedVersion,
      "snapshot.installedVersion",
    ),
    updatedAt: parseNullableTimestamp(record.updatedAt, "snapshot.updatedAt"),
  };
  validateRuntimeInstallSnapshot(snapshot);
  return snapshot;
}

function parseInstallerRuntimeAutoStartResult(
  value: unknown,
): InstallerRuntimeAutoStartResult {
  const record = expectRecord(value, "result");
  const disposition = expectString(record.disposition, "result.disposition");
  if (
    !INSTALLER_RUNTIME_DISPOSITIONS.has(
      disposition as InstallerRuntimeDisposition,
    )
  ) {
    throw new Error(
      `result.disposition has the unknown value ${JSON.stringify(disposition)}`,
    );
  }
  const rawMode = record.mode == null
    ? null
    : expectString(record.mode, "result.mode");
  if (rawMode !== null && !INSTALLER_RUNTIME_MODES.has(rawMode as InstallerRuntimeMode)) {
    throw new Error(`result.mode has the unknown value ${JSON.stringify(rawMode)}`);
  }
  const result: InstallerRuntimeAutoStartResult = {
    disposition: disposition as InstallerRuntimeDisposition,
    mode: rawMode as InstallerRuntimeMode | null,
    targetRoot: record.targetRoot == null
      ? null
      : expectCanonicalRuntimeTargetRoot(record.targetRoot, "result.targetRoot"),
    snapshot: record.snapshot == null
      ? null
      : parseRuntimeInstallSnapshot(record.snapshot),
    message: expectNullableSafeNonEmptyString(record.message, "result.message"),
  };
  validateInstallerRuntimeAutoStartResult(result);
  return result;
}

function parseInstallerRuntimeIntent(value: unknown): InstallerRuntimeIntent {
  const record = expectRecord(value, "intent");
  const status = expectString(record.status, "intent.status");
  if (!INSTALLER_RUNTIME_INTENT_STATUSES.has(status as InstallerRuntimeIntentStatus)) {
    throw new Error(`intent.status has the unknown value ${JSON.stringify(status)}`);
  }
  const rawMode = record.mode == null
    ? null
    : expectString(record.mode, "intent.mode");
  if (rawMode !== null && !INSTALLER_RUNTIME_MODES.has(rawMode as InstallerRuntimeMode)) {
    throw new Error(`intent.mode has the unknown value ${JSON.stringify(rawMode)}`);
  }
  const intent: InstallerRuntimeIntent = {
    status: status as InstallerRuntimeIntentStatus,
    mode: rawMode as InstallerRuntimeMode | null,
    targetRoot: record.targetRoot == null
      ? null
      : expectCanonicalRuntimeTargetRoot(record.targetRoot, "intent.targetRoot"),
    message: expectNullableSafeNonEmptyString(record.message, "intent.message"),
  };
  validateInstallerRuntimeIntent(intent);
  return intent;
}

function parseInstallerRuntimeDiscardResult(
  value: unknown,
): InstallerRuntimeDiscardResult {
  const record = expectRecord(value, "discardResult");
  return {
    discarded: expectBoolean(record.discarded, "discardResult.discarded"),
    message: expectNullableSafeNonEmptyString(
      record.message,
      "discardResult.message",
    ),
  };
}

function validateInstallerRuntimeIntent(intent: InstallerRuntimeIntent): void {
  if (intent.status === "ready") {
    if (intent.mode !== "install-all" && intent.mode !== "custom") {
      throw new Error("intent.ready requires install-all or custom mode");
    }
    if (intent.targetRoot === null) {
      throw new Error("intent.ready requires targetRoot");
    }
    return;
  }
  if (intent.targetRoot !== null) {
    throw new Error(`intent.${intent.status} cannot return targetRoot`);
  }
  if (intent.status === "desktopOnly") {
    if (intent.mode !== "install-app-only") {
      throw new Error("intent.desktopOnly requires install-app-only mode");
    }
    return;
  }
  if (intent.mode !== null) {
    throw new Error(`intent.${intent.status} requires a null mode`);
  }
}

function validateInstallerRuntimeAutoStartResult(
  result: InstallerRuntimeAutoStartResult,
): void {
  const started = result.disposition === "started" || result.disposition === "resumed";
  if (started) {
    if (result.mode !== "install-all" && result.mode !== "custom") {
      throw new Error(
        `result.${result.disposition} requires install-all or custom mode`,
      );
    }
    if (result.targetRoot === null || result.snapshot === null) {
      throw new Error(
        `result.${result.disposition} requires targetRoot and snapshot`,
      );
    }
    if (result.snapshot.targetRoot !== result.targetRoot) {
      throw new Error("result.targetRoot must match result.snapshot.targetRoot");
    }
    if (result.snapshot.phase === "idle") {
      throw new Error(`result.${result.disposition} cannot return an idle snapshot`);
    }
    return;
  }

  if (result.targetRoot !== null || result.snapshot !== null) {
    throw new Error(
      `result.${result.disposition} cannot return targetRoot or snapshot`,
    );
  }
  if (result.disposition === "none" && result.mode !== null) {
    throw new Error("result.none requires a null mode");
  }
  if (
    result.disposition === "desktopOnly" &&
    result.mode !== "install-app-only"
  ) {
    throw new Error("result.desktopOnly requires install-app-only mode");
  }
  if (result.disposition === "invalid" && result.mode !== null) {
    throw new Error("result.invalid requires a null mode");
  }
  if (
    result.disposition === "alreadyInstalled" &&
    result.mode !== "install-all" &&
    result.mode !== "custom"
  ) {
    throw new Error(
      "result.alreadyInstalled requires install-all or custom mode",
    );
  }
}

function parseRuntimeInstallError(value: unknown): RuntimeInstallError {
  const record = expectRecord(value, "snapshot.error");
  return {
    code: expectSafeNonEmptyString(record.code, "snapshot.error.code"),
    message: normalizeRuntimeInstallErrorMessage(
      record.message,
      "snapshot.error.message",
    ),
    retryable: expectBoolean(record.retryable, "snapshot.error.retryable"),
    diagnosticsPath: record.diagnosticsPath == null
      ? null
      : expectAbsoluteWindowsPath(
        record.diagnosticsPath,
        "snapshot.error.diagnosticsPath",
      ),
  };
}

const MAX_RUNTIME_INSTALL_ERROR_MESSAGE_LENGTH = 4096;

/**
 * Runtime failures can contain stderr supplied by curl, WSL, or systemd. Keep
 * the rest of the native snapshot contract strict, but make this human-facing
 * field safe to render without discarding the error code or diagnostic path.
 * String#slice deliberately measures the bound in JavaScript UTF-16 code
 * units; the surrogate check avoids ending the rendered message with half of
 * a non-BMP character.
 */
function normalizeRuntimeInstallErrorMessage(value: unknown, path: string): string {
  const raw = expectString(value, path);
  if (raw.length === 0) throw new Error(`${path} must not be empty`);

  let readable = "";
  let separatorPending = false;
  let truncated = false;
  for (const character of raw) {
    if (runtimeErrorCharacterIsSeparator(character)) {
      separatorPending = readable.length > 0;
      continue;
    }
    const token = `${separatorPending ? " " : ""}${character}`;
    if (readable.length + token.length > MAX_RUNTIME_INSTALL_ERROR_MESSAGE_LENGTH) {
      truncated = true;
      break;
    }
    readable += token;
    separatorPending = false;
  }
  if (readable.length === 0) {
    return "Runtime installer returned an unreadable error message.";
  }
  if (!truncated) return readable;

  const suffix = "…";
  let prefix = readable.slice(0, MAX_RUNTIME_INSTALL_ERROR_MESSAGE_LENGTH - suffix.length);
  const finalCodeUnit = prefix.charCodeAt(prefix.length - 1);
  if (finalCodeUnit >= 0xd800 && finalCodeUnit <= 0xdbff) {
    prefix = prefix.slice(0, -1);
  }
  return `${prefix.trimEnd()}${suffix}`;
}

function runtimeErrorCharacterIsSeparator(character: string): boolean {
  const codePoint = character.codePointAt(0) ?? 0;
  return codePoint <= 0x1f ||
    (codePoint >= 0x7f && codePoint <= 0x9f) ||
    (codePoint >= 0xd800 && codePoint <= 0xdfff) ||
    codePoint === 0x2028 ||
    codePoint === 0x2029 ||
    /\p{Cf}/u.test(character) ||
    /\s/u.test(character);
}

function validateRuntimeInstallSnapshot(snapshot: RuntimeInstallSnapshot): void {
  if (
    snapshot.bytesTotal !== null &&
    snapshot.bytesDownloaded > snapshot.bytesTotal
  ) {
    throw new Error("snapshot.bytesDownloaded cannot exceed bytesTotal");
  }
  if (snapshot.currentPart !== null && snapshot.totalParts === null) {
    throw new Error("snapshot.currentPart requires totalParts");
  }
  if (
    snapshot.currentPart !== null &&
    snapshot.totalParts !== null &&
    (snapshot.totalParts === 0 || snapshot.currentPart > snapshot.totalParts)
  ) {
    throw new Error("snapshot.currentPart cannot exceed a positive totalParts");
  }
  if (snapshot.phase === "idle") {
    if (
      snapshot.operationId !== null ||
      snapshot.targetRoot !== null ||
      snapshot.error !== null ||
      snapshot.bytesDownloaded !== 0 ||
      snapshot.bytesTotal !== null ||
      snapshot.currentPart !== null ||
      snapshot.totalParts !== null ||
      snapshot.message !== null ||
      snapshot.installedVersion !== null ||
      snapshot.updatedAt !== null ||
      snapshot.resumable ||
      snapshot.requiresRestart
    ) {
      throw new Error("snapshot idle state must not contain operation progress");
    }
    return;
  }
  if (snapshot.operationId === null || snapshot.targetRoot === null) {
    throw new Error("snapshot non-idle state requires operationId and targetRoot");
  }
  if (snapshot.phase === "failed" && snapshot.error === null) {
    throw new Error("snapshot failed state requires an error");
  }
  if (snapshot.phase !== "failed" && snapshot.error !== null) {
    throw new Error("snapshot error is only valid in the failed state");
  }
  if (snapshot.phase === "waitingForRestart" && !snapshot.requiresRestart) {
    throw new Error("snapshot waitingForRestart state requires a restart");
  }
  if (snapshot.phase === "waitingForRestart" && !snapshot.resumable) {
    throw new Error("snapshot waitingForRestart state must be resumable");
  }
  if (
    snapshot.phase === "failed" &&
    snapshot.error &&
    snapshot.resumable !== snapshot.error.retryable
  ) {
    throw new Error("snapshot failed resumable state must match error.retryable");
  }
  if (snapshot.phase === "completed") {
    if (snapshot.installedVersion === null) {
      throw new Error("snapshot completed state requires installedVersion");
    }
    if (snapshot.resumable || snapshot.requiresRestart) {
      throw new Error("snapshot completed state cannot be resumable or require restart");
    }
  }
}

function expectRecord(value: unknown, path: string): UnknownRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${path} must be an object`);
  }
  return value as UnknownRecord;
}

function expectExactRecord(
  value: unknown,
  path: string,
  expectedKeys: string[],
): UnknownRecord {
  const record = expectRecord(value, path);
  const actualKeys = Object.keys(record).sort();
  const sortedExpectedKeys = [...expectedKeys].sort();
  if (
    actualKeys.length !== sortedExpectedKeys.length
    || actualKeys.some((key, index) => key !== sortedExpectedKeys[index])
  ) {
    throw new Error(`${path} has unsupported or missing fields`);
  }
  return record;
}

function expectArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`${path} must be an array`);
  return value;
}

function expectString(value: unknown, path: string): string {
  if (typeof value !== "string") throw new Error(`${path} must be a string`);
  return value;
}

function expectSafeNonEmptyString(value: unknown, path: string): string {
  const string = expectString(value, path);
  if (string.trim() === "") throw new Error(`${path} must not be empty`);
  const hasControlCharacter = [...string].some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint < 32 || codePoint === 127;
  });
  if (string.length > 4096 || hasControlCharacter) {
    throw new Error(`${path} contains unsafe control characters or is too long`);
  }
  return string;
}

function expectIdentifier(value: unknown, path: string): string {
  const identifier = expectString(value, path);
  if (!/^[a-z0-9][a-z0-9.-]{0,127}$/u.test(identifier)) {
    throw new Error(`${path} must be a bounded lowercase identifier`);
  }
  return identifier;
}

function expectControllerKey(value: unknown, path: string): string {
  const controllerKey = expectSafeNonEmptyString(value, path);
  if (controllerKey.length > 160 || controllerKey.split("::").length !== 2) {
    throw new Error(`${path} must contain exactly one controller namespace separator`);
  }
  return controllerKey;
}

function expectCanonicalComPort(value: unknown, path: string): string {
  const port = expectString(value, path);
  const match = /^COM([1-9][0-9]{0,2})$/u.exec(port);
  if (!match || Number(match[1]) > 999) {
    throw new Error(`${path} must be a canonical COM port`);
  }
  return port;
}

function expectLowercaseHex(
  value: unknown,
  path: string,
  length: number,
): string {
  const digest = expectString(value, path);
  if (digest.length !== length || !/^[0-9a-f]+$/u.test(digest)) {
    throw new Error(`${path} must be ${length} lowercase hexadecimal characters`);
  }
  return digest;
}

function normalizeRequestedTargetRoot(value: string): string {
  const match = /^([a-z]):\\DroneDream\\?$/iu.exec(value.trim());
  if (!match) {
    throw new Error("targetRoot must be a drive root such as E:\\DroneDream");
  }
  return `${match[1].toUpperCase()}:\\DroneDream`;
}

function expectCanonicalRuntimeTargetRoot(value: unknown, path: string): string {
  const targetRoot = expectSafeNonEmptyString(value, path);
  if (!/^[A-Z]:\\DroneDream$/u.test(targetRoot)) {
    throw new Error(`${path} must be a canonical path such as E:\\DroneDream`);
  }
  return targetRoot;
}

function expectAbsoluteWindowsPath(value: unknown, path: string): string {
  const windowsPath = expectSafeNonEmptyString(value, path);
  const containsUnsafeUnicode = [...windowsPath].some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return (codePoint >= 0x7f && codePoint <= 0x9f) ||
      (codePoint >= 0xd800 && codePoint <= 0xdfff) ||
      codePoint === 0x2028 ||
      codePoint === 0x2029 ||
      /\p{Cf}/u.test(character);
  });
  if (containsUnsafeUnicode || !/^[A-Za-z]:\\[^<>:"\x2f|?*]+$/u.test(windowsPath)) {
    throw new Error(`${path} must be an absolute local Windows path`);
  }
  const segments = windowsPath.slice(3).split("\\");
  if (
    segments.some((segment) =>
      segment === "" ||
      segment === "." ||
      segment === ".." ||
      segment.endsWith(" ") ||
      segment.endsWith(".") ||
      /^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³]|CONIN\$|CONOUT\$)(?:\..*)?$/iu.test(segment)
    )
  ) {
    throw new Error(`${path} contains an unsafe Windows path segment`);
  }
  return `${windowsPath[0].toUpperCase()}${windowsPath.slice(1)}`;
}

function expectNullableString(value: unknown, path: string): string | null {
  if (value == null) return null;
  return expectString(value, path);
}

function expectNullableSafeNonEmptyString(
  value: unknown,
  path: string,
): string | null {
  if (value == null) return null;
  return expectSafeNonEmptyString(value, path);
}

function parseNullableTimestamp(value: unknown, path: string): string | null {
  if (value == null) return null;
  const timestamp = expectSafeNonEmptyString(value, path);
  if (!/^\d{4}-\d{2}-\d{2}T/u.test(timestamp) || Number.isNaN(Date.parse(timestamp))) {
    throw new Error(`${path} must be an ISO 8601 timestamp`);
  }
  return timestamp;
}

function expectIsoTimestamp(value: unknown, path: string): string {
  const timestamp = parseNullableTimestamp(value, path);
  if (timestamp === null) throw new Error(`${path} must not be null`);
  return timestamp;
}

function expectBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be a boolean`);
  return value;
}

function expectLiteral<const T extends string | number | boolean>(
  value: unknown,
  expected: T,
  path: string,
): T {
  if (value !== expected) throw new Error(`${path} must equal ${String(expected)}`);
  return expected;
}

function expectSha256Id(value: unknown, path: string): string {
  const identity = expectString(value, path);
  if (!/^sha256:[0-9a-f]{64}$/u.test(identity)) {
    throw new Error(`${path} must be a SHA-256 identity`);
  }
  return identity;
}

function expectFiniteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${path} must be a finite number`);
  }
  return value;
}

function expectPositiveInteger(value: unknown, path: string): number {
  const number = expectNonNegativeInteger(value, path);
  if (number < 1) throw new Error(`${path} must be positive`);
  return number;
}

function expectNonNegativeNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${path} must be a safe non-negative integer`);
  }
  return value;
}

function expectNonNegativeInteger(value: unknown, path: string): number {
  const number = expectNonNegativeNumber(value, path);
  if (!Number.isInteger(number)) throw new Error(`${path} must be an integer`);
  return number;
}

function parseStringArray(value: unknown, path: string): string[] {
  return expectArray(value, path).map((item, index) =>
    expectString(item, `${path}[${index}]`),
  );
}

function parseSafeNonEmptyStringArray(value: unknown, path: string): string[] {
  return expectArray(value, path).map((item, index) =>
    expectSafeNonEmptyString(item, `${path}[${index}]`),
  );
}

function parseIdentifierArray(value: unknown, path: string): string[] {
  const identifiers = expectArray(value, path).map((item, index) =>
    expectIdentifier(item, `${path}[${index}]`),
  );
  assertUnique(identifiers, path);
  return identifiers;
}

function assertUnique(values: string[], path: string): void {
  if (new Set(values).size !== values.length) {
    throw new Error(`${path} must be unique`);
  }
}

function contractErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
