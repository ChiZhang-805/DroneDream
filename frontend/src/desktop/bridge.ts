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

export function probeSystemPrerequisites(): Promise<SystemPrerequisiteReport> {
  return invokeDesktop("probe_system_prerequisites", parsePrerequisiteReport);
}

export function probeRuntimeStatus(): Promise<RuntimeStatusReport> {
  return invokeDesktop("probe_runtime_status", parseRuntimeStatus);
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

function expectBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${path} must be a boolean`);
  return value;
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

function assertUnique(values: string[], path: string): void {
  if (new Set(values).size !== values.length) {
    throw new Error(`${path} must be unique`);
  }
}

function contractErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
