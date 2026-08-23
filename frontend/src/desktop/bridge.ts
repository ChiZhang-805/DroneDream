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

export type ComponentUpdateId = "capability-pack" | "asset-pack";
export type ComponentUpdateUrgency = "required" | "recommended" | "optional";
export type ComponentUpdateInstallMode = "automatic" | "user-confirmed";

export interface ComponentUpdateDependency {
  componentId: ComponentUpdateId;
  minimumReleaseSequence: number;
}

export interface ComponentUpdateCandidate {
  componentId: ComponentUpdateId;
  version: string;
  releaseSequence: number;
  urgency: ComponentUpdateUrgency;
  installMode: ComponentUpdateInstallMode;
  dependencies: ComponentUpdateDependency[];
  packId: string;
  installedVersion: string | null;
  installedReleaseSequence: number;
  available: boolean;
}

export interface ComponentUpdateReport {
  catalogSequence: number;
  generatedAt: string;
  expiresAt: string;
  candidates: ComponentUpdateCandidate[];
}

export interface ComponentInstallResult {
  componentId: ComponentUpdateId;
  packId: string;
  version: string;
  releaseSequence: number;
  activated: boolean;
}

export type HardwareDomainEdition = "lab" | "field" | "autonomy";

export interface FieldTuningStatus {
  schemaVersion: 1;
  kind: "dronedream-field-tuning-status";
  editionId: HardwareDomainEdition;
  executionDomain: "real-hardware";
  runtimeProfile: "unified-sim-lab" | "field-lightweight" | "autonomy-full";
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

export type FieldAdapterCapability =
  | "unavailable"
  | "read-only"
  | "quorum-required"
  | "vendor-controlled";

export interface FieldAdapterCapabilities {
  deviceDiscovery: FieldAdapterCapability;
  telemetryRead: FieldAdapterCapability;
  parameterRead: FieldAdapterCapability;
  parameterWrite: FieldAdapterCapability;
  arm: FieldAdapterCapability;
  flight: FieldAdapterCapability;
  autonomousTuning: FieldAdapterCapability;
}

export interface FieldAdapterCatalogEntry {
  adapterId: string;
  version: string;
  displayName: { en: string; "zh-CN": string };
  vendor: string;
  protocolFamily: string;
  implementationStatus:
    | "available"
    | "vendor-access-required"
    | "platform-bridge-required"
    | "planned";
  deliveryMode: "embedded-managed" | "vendor-managed" | "unavailable";
  installable: boolean;
  installed: boolean;
  installedPackageSha256: string | null;
  supportedTransports: string[];
  supportedPlatforms: string[];
  packageSha256: string | null;
  capabilities: FieldAdapterCapabilities;
  safety: {
    installationGrantsAuthority: false;
    discoveryGrantsAuthority: false;
    requiresValidatedVehiclePackForWrites: true;
    requiresNativeBackendRuntimeOperatorQuorum: true;
  };
}

export interface FieldAdapterCatalogReport {
  schemaVersion: 1;
  kind: "dronedream-field-adapter-catalog-report";
  catalogVersion: string;
  editionId: HardwareDomainEdition;
  source: "source-bound-embedded-catalog";
  catalogSha256: string;
  hardwareAuthority: false;
  executableExtensionLoading: false;
  entries: FieldAdapterCatalogEntry[];
}

export interface FieldAdapterInstallRequest {
  adapterId: string;
  expectedPackageSha256: string;
}

export interface FieldAdapterInstallReceipt {
  schemaVersion: 1;
  kind: "dronedream-field-adapter-install-receipt";
  editionId: HardwareDomainEdition;
  adapterId: string;
  packageSha256: string;
  state: "installed" | "already-installed";
  executableCodeInstalled: false;
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
  hardwareAuthority: false;
}

export interface FieldAdapterFrameInspectionRequest {
  adapterId: string;
  frameBase64: string;
}

export interface FieldAdapterFrameInspection {
  schemaVersion: 1;
  kind: "dronedream-field-adapter-frame-inspection";
  editionId: HardwareDomainEdition;
  adapterId: string;
  protocolVersion: 1 | 2;
  systemId: number;
  componentId: number;
  sequence: number;
  messageId: number;
  messageName: string;
  frameSha256: string;
  frameBytes: number;
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
  hardwareAuthority: false;
}

export interface FieldProtocolFrameInspectionRequest {
  adapterId: string;
  frameBase64: string;
}

export interface FieldProtocolFrameInspection {
  schemaVersion: 1;
  kind: "dronedream-field-protocol-frame-inspection";
  editionId: HardwareDomainEdition;
  adapterId: string;
  protocolFamily: string;
  classification: string;
  fields: Readonly<Record<string, string | number | boolean>>;
  frameSha256: string;
  frameBytes: number;
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
  hardwareAuthority: false;
}

export interface FieldMavlinkTelemetryProbeRequest {
  adapterId: string;
  expectedPackageSha256: string;
  observationId: string;
  portName: string;
  baudRate: 57600 | 115200 | 230400 | 460800 | 921600;
  readDeadlineMs: number;
  operatorConfirmedReadOnly: true;
}

export interface FieldMavlinkTelemetryProbeReceipt {
  schemaVersion: 1;
  kind: "dronedream-field-mavlink-telemetry-probe-receipt";
  editionId: HardwareDomainEdition;
  adapterId: string;
  observationId: string;
  portName: string;
  baudRate: number;
  protocolVersion: 1 | 2;
  systemId: number;
  componentId: number;
  sequence: number;
  messageId: number;
  messageName: string;
  frameSha256: string;
  frameBytes: number;
  deviceOpenAttempts: 1;
  telemetryReadAttempts: 1;
  parameterReadAttempts: 0;
  hardwareWriteAttempts: 0;
  armAttempts: 0;
  flightAttempts: 0;
  hardwareAuthority: false;
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
  editionId: HardwareDomainEdition;
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
  editionId: HardwareDomainEdition;
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
  deviceObservationId: string | null;
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  adapterId: string | null;
  observationSha256: string | null;
  snapshotSha256: string | null;
  objective: string;
  maxIterations: number;
}

export interface FieldHardwareTuningPlan {
  schemaVersion: 1;
  kind: "dronedream-field-hardware-tuning-plan";
  jobId: string;
  editionId: HardwareDomainEdition;
  executionDomain: "real-hardware";
  sourceCommit: string;
  requestSha256: string;
  snapshotSha256: string | null;
  observationSha256: string | null;
  budget: {
    maxIterations: number;
    hardwareTrialBudget: 0;
    parameterWriteBudget: 0;
    providerRequests: 0;
  };
  phases: string[];
  canExecute: false;
  hardwareAuthority: false;
  hardwareWriteAttempts: 0;
  requiredEvidence: string[];
  blockers: string[];
  planSha256: string;
}

export interface FieldHarnessParameterBound {
  min: number;
  max: number;
  maxStep: number;
}

export interface FieldHarnessMetrics {
  trackingError: number;
  overshootPercent: number;
  controlEffort: number;
  constraintViolations: number;
  emergencyInterventions: number;
}

export interface FieldHarnessTrialInput {
  trialId: string;
  telemetrySha256: string;
  parameters: Record<string, number>;
  metrics: FieldHarnessMetrics;
  independentHoldout: boolean;
}

export interface FieldHarnessJobRequest {
  jobName: string;
  objective: string;
  targetScore: number;
  maxIterations: number;
  deviceObservationId: string;
  observationSha256: string;
  snapshotSha256: string;
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  adapterId: string;
  parameterBounds: Record<string, FieldHarnessParameterBound>;
  trials: FieldHarnessTrialInput[];
}

export interface FieldHarnessTrialReceipt extends FieldHarnessTrialInput {
  candidateSha256: string;
  score: number;
  accepted: boolean;
  failureClass:
    | "none"
    | "objective-miss"
    | "constraint-violation"
    | "emergency-intervention";
}

export interface FieldHarnessJobReceipt {
  schemaVersion: 1;
  kind: "dronedream-field-harness-job-receipt";
  jobId: string;
  createdAt: string;
  editionId: HardwareDomainEdition;
  executionDomain: "real-device-recorded-evidence";
  executionMode: "offline-evidence-replay-no-device-io";
  sourceCommit: string;
  enginePackId: string;
  requestSha256: string;
  jobName: string;
  objective: string;
  targetScore: number;
  deviceObservationId: string;
  observationSha256: string;
  snapshotSha256: string;
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  adapterId: string;
  budget: {
    maxIterations: number;
    usedTrainingTrials: number;
    usedHoldoutTrials: 1;
    remainingIterations: number;
  };
  trials: FieldHarnessTrialReceipt[];
  selectedCandidateSha256: string;
  proposedParameters: Record<string, number>;
  proposedCandidateSha256: string;
  holdoutTrialId: string;
  qualification: {
    status: "recorded-evidence-passed" | "recorded-evidence-rejected";
    recordedEvidencePassed: boolean;
    hardwareValid: false;
    reason: string;
  };
  blockers: string[];
  providerRequests: 0;
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
  armAttempts: 0;
  flightAttempts: 0;
  hardwareAuthority: false;
  receiptSha256: string;
}

export interface FieldHarnessJobSummary {
  jobId: string;
  createdAt: string;
  jobName: string;
  objective: string;
  qualificationStatus: "recorded-evidence-passed" | "recorded-evidence-rejected";
  recordedEvidencePassed: boolean;
  hardwareValid: false;
  receiptSha256: string;
}

export interface FieldParameterSnapshotRequest {
  deviceObservationId: string;
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  adapterId: string;
  observationSha256: string;
  parameters: Record<string, number>;
}

export interface FieldParameterSnapshot {
  schemaVersion: 1;
  kind: "dronedream-field-parameter-snapshot";
  editionId: HardwareDomainEdition;
  executionDomain: "real-hardware";
  evidenceSource: "operator-imported-read-only";
  sourceCommit: string;
  deviceObservationId: string;
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  adapterId: string;
  observationSha256: string;
  parameterCount: number;
  parameters: Record<string, number>;
  parameterSetSha256: string;
  snapshotSha256: string;
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
  hardwareAuthority: false;
}

export interface FieldParameterSnapshotSummary {
  schemaVersion: 1;
  kind: "dronedream-field-parameter-snapshot-summary";
  editionId: HardwareDomainEdition;
  sourceCommit: string;
  deviceObservationId: string;
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  adapterId: string;
  observationSha256: string;
  parameterCount: number;
  parameterSetSha256: string;
  snapshotSha256: string;
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
  hardwareAuthority: false;
}

export interface FieldParameterDiffRequest {
  snapshotSha256: string;
  currentParameters: Record<string, number>;
}

export interface FieldParameterChange {
  name: string;
  before: number | null;
  after: number | null;
  delta: number | null;
}

export interface FieldParameterDiffReceipt {
  schemaVersion: 1;
  kind: "dronedream-field-parameter-diff";
  editionId: HardwareDomainEdition;
  snapshotSha256: string;
  currentParameterSetSha256: string;
  changedCount: number;
  changes: FieldParameterChange[];
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
  hardwareAuthority: false;
  receiptSha256: string;
}

export interface FieldRollbackPlan {
  schemaVersion: 1;
  kind: "dronedream-field-rollback-plan";
  editionId: HardwareDomainEdition;
  snapshotSha256: string;
  planSha256: string;
  changes: FieldParameterChange[];
  canExecute: false;
  hardwareAuthority: false;
  hardwareWriteAttempts: 0;
  requiredEvidence: string[];
  blockers: string[];
}

export interface FieldPreflightRequest {
  vehiclePackId: string;
  controllerId: string;
  firmwareVersion: string;
  deviceObservationId: string | null;
  observationSha256: string | null;
  snapshotSha256: string | null;
  zoneName: string;
  zoneRadiusM: number;
  maxAltitudeM: number;
  operatorConfirmed: boolean;
}

export interface FieldPreflightPlan {
  schemaVersion: 1;
  kind: "dronedream-field-preflight-plan";
  editionId: HardwareDomainEdition;
  executionDomain: "real-hardware";
  sourceCommit: string;
  requestSha256: string;
  planSha256: string;
  validatedPackCount: number;
  zone: {
    name: string;
    radiusM: number;
    maxAltitudeM: number;
    evidenceState: "operator-declared-only";
  };
  quorum: Record<string, string>;
  actionDecisions: Record<string, "deny">;
  requiredEvidence: string[];
  blockers: string[];
  canExecute: false;
  hardwareAuthority: false;
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
}

export interface DesktopApiRequest {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  body?: string | null;
  bodyBase64?: string | null;
  contentType?: "application/json" | "application/octet-stream" | null;
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
  editionId: "universal" | "sim" | "lab" | "field" | "autonomy";
  authClientId: string;
  accessToken: string;
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
  | "backingUp"
  | "importing"
  | "starting"
  | "healthChecking"
  | "restoring"
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

export interface RuntimeUpgradeRequest {
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
  "backingUp",
  "importing",
  "starting",
  "healthChecking",
  "restoring",
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

export interface LabCalibrationMetricsRequest {
  trackingRmseM: number;
  maxErrorM: number;
  energyWh: number;
  overshootCount: number;
}

export interface LabCalibrationCycleRequest {
  schemaVersion: 1;
  jobId: string;
  cycleOrdinal: number;
  commonCoreCommit: string;
  editionManifestSha256: string;
  vehiclePackId: string;
  controllerIdentity: string;
  firmwareIdentity: string;
  simulationReceiptSha256: string;
  realObservationReceiptSha256: string;
  parameterCandidateSha256: string;
  objectiveContractSha256: string;
  constraintContractSha256: string;
  holdoutContractSha256: string;
  metricNormalizationReceiptSha256: string;
  objective: string;
  tolerancePercent: number;
  cycleBudget: number;
  simulation: LabCalibrationMetricsRequest;
  realObservation: LabCalibrationMetricsRequest;
  independentHoldoutPassed: boolean;
}

export interface LabCalibrationCycleReceipt {
  kind: "dronedream-lab-sim-real-calibration-receipt";
  editionId: "lab";
  productSource: string;
  requestSha256: string;
  objectiveContractSha256: string;
  constraintContractSha256: string;
  holdoutContractSha256: string;
  metricNormalizationReceiptSha256: string;
  aggregateGapPercent: number;
  gapWithinTolerance: boolean;
  nextAction:
    | "revise-model-and-resimulate"
    | "run-independent-holdout"
    | "await-validated-pack-and-safety-quorum";
  qualificationDecision: "deny";
  trusted: false;
  blockers: string[];
  validatedVehiclePackCount: 0;
  providerRequests: 0;
  deviceOpenAttempts: 0;
  hardwareWriteAttempts: 0;
  armAttempts: 0;
  flightAttempts: 0;
  hardwareAuthority: false;
  receiptSha256: string;
  [key: string]: unknown;
}

function parseLabCalibrationCycleReceipt(value: unknown): LabCalibrationCycleReceipt {
  const receipt = expectRecord(value, "lab calibration receipt");
  const nextAction = expectString(receipt.nextAction, "lab calibration receipt.nextAction");
  if (![
    "revise-model-and-resimulate",
    "run-independent-holdout",
    "await-validated-pack-and-safety-quorum",
  ].includes(nextAction)) {
    throw new Error("lab calibration receipt.nextAction is unsupported");
  }
  const parsed: LabCalibrationCycleReceipt = {
    ...receipt,
    kind: expectLiteral(
      receipt.kind,
      "dronedream-lab-sim-real-calibration-receipt",
      "lab calibration receipt.kind",
    ),
    editionId: expectLiteral(receipt.editionId, "lab", "lab calibration receipt.editionId"),
    productSource: expectString(receipt.productSource, "lab calibration receipt.productSource"),
    requestSha256: expectString(receipt.requestSha256, "lab calibration receipt.requestSha256"),
    objectiveContractSha256: expectString(receipt.objectiveContractSha256, "lab calibration receipt.objectiveContractSha256"),
    constraintContractSha256: expectString(receipt.constraintContractSha256, "lab calibration receipt.constraintContractSha256"),
    holdoutContractSha256: expectString(receipt.holdoutContractSha256, "lab calibration receipt.holdoutContractSha256"),
    metricNormalizationReceiptSha256: expectString(receipt.metricNormalizationReceiptSha256, "lab calibration receipt.metricNormalizationReceiptSha256"),
    aggregateGapPercent: expectFiniteNumber(
      receipt.aggregateGapPercent,
      "lab calibration receipt.aggregateGapPercent",
    ),
    gapWithinTolerance: expectBoolean(
      receipt.gapWithinTolerance,
      "lab calibration receipt.gapWithinTolerance",
    ),
    nextAction: nextAction as LabCalibrationCycleReceipt["nextAction"],
    qualificationDecision: expectLiteral(
      receipt.qualificationDecision,
      "deny",
      "lab calibration receipt.qualificationDecision",
    ),
    trusted: expectLiteral(receipt.trusted, false, "lab calibration receipt.trusted"),
    blockers: parseStringArray(receipt.blockers, "lab calibration receipt.blockers"),
    validatedVehiclePackCount: expectLiteral(
      receipt.validatedVehiclePackCount,
      0,
      "lab calibration receipt.validatedVehiclePackCount",
    ),
    providerRequests: expectLiteral(receipt.providerRequests, 0, "lab calibration receipt.providerRequests"),
    deviceOpenAttempts: expectLiteral(receipt.deviceOpenAttempts, 0, "lab calibration receipt.deviceOpenAttempts"),
    hardwareWriteAttempts: expectLiteral(receipt.hardwareWriteAttempts, 0, "lab calibration receipt.hardwareWriteAttempts"),
    armAttempts: expectLiteral(receipt.armAttempts, 0, "lab calibration receipt.armAttempts"),
    flightAttempts: expectLiteral(receipt.flightAttempts, 0, "lab calibration receipt.flightAttempts"),
    hardwareAuthority: expectLiteral(receipt.hardwareAuthority, false, "lab calibration receipt.hardwareAuthority"),
    receiptSha256: expectString(receipt.receiptSha256, "lab calibration receipt.receiptSha256"),
  };
  if (!/^[a-f0-9]{40}$/.test(parsed.productSource) || ![
    parsed.requestSha256,
    parsed.objectiveContractSha256,
    parsed.constraintContractSha256,
    parsed.holdoutContractSha256,
    parsed.metricNormalizationReceiptSha256,
    parsed.receiptSha256,
  ].every((identity) => /^[a-f0-9]{64}$/.test(identity))) {
    throw new Error("lab calibration receipt source or hash is invalid");
  }
  return parsed;
}

export function evaluateLabCalibrationCycle(
  request: LabCalibrationCycleRequest,
): Promise<LabCalibrationCycleReceipt> {
  return invokeDesktop(
    "evaluate_lab_calibration_cycle",
    parseLabCalibrationCycleReceipt,
    { request },
  );
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

export function getFieldAdapterCatalog(): Promise<FieldAdapterCatalogReport> {
  return invokeDesktop("get_field_adapter_catalog", parseFieldAdapterCatalog);
}

export function installFieldAdapter(
  request: FieldAdapterInstallRequest,
): Promise<FieldAdapterInstallReceipt> {
  if (
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(request.adapterId)
    || !/^[a-f0-9]{64}$/.test(request.expectedPackageSha256)
  ) {
    return Promise.reject(new Error("Field adapter install request is invalid."));
  }
  return invokeDesktop("install_field_adapter", parseFieldAdapterInstallReceipt, { request });
}

export function inspectFieldAdapterFrame(
  request: FieldAdapterFrameInspectionRequest,
): Promise<FieldAdapterFrameInspection> {
  if (
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(request.adapterId)
    || request.frameBase64.length === 0
    || request.frameBase64.length > 512
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(request.frameBase64)
  ) {
    return Promise.reject(new Error("Field adapter frame inspection request is invalid."));
  }
  return invokeDesktop("inspect_field_adapter_frame", parseFieldAdapterFrameInspection, {
    request,
  });
}

export function inspectFieldProtocolFrame(
  request: FieldProtocolFrameInspectionRequest,
): Promise<FieldProtocolFrameInspection> {
  if (
    !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(request.adapterId)
    || request.frameBase64.length === 0
    || request.frameBase64.length > 512
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(request.frameBase64)
  ) {
    return Promise.reject(new Error("Field protocol frame inspection request is invalid."));
  }
  return invokeDesktop("inspect_field_protocol_frame", parseFieldProtocolFrameInspection, {
    request,
  });
}

export function probeFieldMavlinkTelemetry(
  request: FieldMavlinkTelemetryProbeRequest,
): Promise<FieldMavlinkTelemetryProbeReceipt> {
  if (
    !/^(?:mavlink-common-v2|mavlink-px4-v2|mavlink-ardupilotmega-v2)$/.test(request.adapterId)
    || !/^[a-f0-9]{64}$/.test(request.expectedPackageSha256)
    || !/^[a-f0-9]{64}$/.test(request.observationId)
    || !/^COM(?:[1-9][0-9]{0,2})$/.test(request.portName)
    || ![57_600, 115_200, 230_400, 460_800, 921_600].includes(request.baudRate)
    || !Number.isSafeInteger(request.readDeadlineMs)
    || request.readDeadlineMs < 250
    || request.readDeadlineMs > 5_000
    || request.operatorConfirmedReadOnly !== true
  ) {
    return Promise.reject(new Error("Field MAVLink telemetry probe request is invalid."));
  }
  return invokeDesktop(
    "probe_field_mavlink_telemetry",
    parseFieldMavlinkTelemetryProbeReceipt,
    { request },
  );
}

export function discoverFieldDevices(): Promise<FieldDeviceDiscoveryReport> {
  return invokeDesktop("discover_field_devices", parseFieldDeviceDiscoveryReport);
}

export function createFieldParameterSnapshot(
  request: FieldParameterSnapshotRequest,
): Promise<FieldParameterSnapshot> {
  validateFieldSnapshotRequest(request);
  return invokeDesktop("create_field_parameter_snapshot", parseFieldParameterSnapshot, {
    request,
  });
}

export function listFieldParameterSnapshots(): Promise<FieldParameterSnapshotSummary[]> {
  return invokeDesktop("list_field_parameter_snapshots", parseFieldParameterSnapshotSummaries);
}

export function loadFieldParameterSnapshot(
  snapshotSha256: string,
): Promise<FieldParameterSnapshot> {
  if (!/^[a-f0-9]{64}$/.test(snapshotSha256)) {
    return Promise.reject(new Error("Field parameter snapshot hash is invalid."));
  }
  return invokeDesktop("load_field_parameter_snapshot", parseFieldParameterSnapshot, {
    request: { snapshotSha256 },
  });
}

export function compareFieldParameterSnapshot(
  request: FieldParameterDiffRequest,
): Promise<FieldParameterDiffReceipt> {
  validateFieldDiffRequest(request);
  return invokeDesktop("compare_field_parameter_snapshot", parseFieldParameterDiffReceipt, {
    request,
  });
}

export function prepareFieldParameterRollback(
  request: FieldParameterDiffRequest,
): Promise<FieldRollbackPlan> {
  validateFieldDiffRequest(request);
  return invokeDesktop("prepare_field_parameter_rollback", parseFieldRollbackPlan, {
    request,
  });
}

export function prepareFieldPreflight(
  request: FieldPreflightRequest,
): Promise<FieldPreflightPlan> {
  for (const value of [
    request.vehiclePackId,
    request.controllerId,
    request.firmwareVersion,
    request.zoneName,
  ]) {
    if (!/^[A-Za-z0-9][-A-Za-z0-9 .:_/+]{0,159}$/.test(value) || value.trim() !== value) {
      return Promise.reject(new Error("Field preflight identity is invalid."));
    }
  }
  if (
    !Number.isSafeInteger(request.zoneRadiusM)
    || request.zoneRadiusM < 1
    || request.zoneRadiusM > 10_000
    || !Number.isSafeInteger(request.maxAltitudeM)
    || request.maxAltitudeM < 1
    || request.maxAltitudeM > 1_000
    || (request.deviceObservationId !== null
      && (!/^[A-Za-z0-9][-A-Za-z0-9 .:_/+]{0,159}$/.test(request.deviceObservationId)
        || request.deviceObservationId.trim() !== request.deviceObservationId))
    || request.observationSha256 !== null && !/^[a-f0-9]{64}$/.test(request.observationSha256)
    || request.snapshotSha256 !== null && !/^[a-f0-9]{64}$/.test(request.snapshotSha256)
  ) {
    return Promise.reject(new Error("Field preflight request is outside its bound."));
  }
  return invokeDesktop("prepare_field_preflight", parseFieldPreflightPlan, { request });
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
  for (const value of [
    request.vehiclePackId,
    request.controllerId,
    request.firmwareVersion,
    request.objective,
  ]) {
    if (value.trim() === "" || value.length > 160) {
      return Promise.reject(new Error("Field hardware tuning request is invalid."));
    }
  }
  for (const value of [request.deviceObservationId, request.adapterId]) {
    if (value !== null && (value.trim() === "" || value.length > 160)) {
      return Promise.reject(new Error("Field hardware tuning evidence identity is invalid."));
    }
  }
  for (const value of [request.observationSha256, request.snapshotSha256]) {
    if (value !== null && !/^[a-f0-9]{64}$/.test(value)) {
      return Promise.reject(new Error("Field hardware tuning evidence hash is invalid."));
    }
  }
  if (!Number.isInteger(request.maxIterations) || request.maxIterations < 1 || request.maxIterations > 32) {
    return Promise.reject(new Error("Field hardware tuning iteration budget is invalid."));
  }
  return invokeDesktop("prepare_field_hardware_tuning", parseFieldHardwareTuningPlan, {
    request,
  });
}

export function runFieldHarnessJob(
  request: FieldHarnessJobRequest,
): Promise<FieldHarnessJobReceipt> {
  validateFieldHarnessRequest(request);
  return invokeDesktop("run_field_harness_job", parseFieldHarnessJobReceipt, { request });
}

export function listFieldHarnessJobs(): Promise<FieldHarnessJobSummary[]> {
  return invokeDesktop("list_field_harness_jobs", parseFieldHarnessJobSummaries);
}

export function loadFieldHarnessJob(jobId: string): Promise<FieldHarnessJobReceipt> {
  if (!/^field-harness-[a-f0-9]{16}-[a-f0-9]{8}$/.test(jobId)) {
    return Promise.reject(new Error("Field Harness job id is invalid."));
  }
  return invokeDesktop("load_field_harness_job", parseFieldHarnessJobReceipt, {
    request: { jobId },
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

export function checkComponentUpdates(
  catalogUrl?: string,
): Promise<ComponentUpdateReport> {
  return invokeDesktop(
    "check_component_updates",
    parseComponentUpdateReport,
    catalogUrl ? { catalogUrl } : undefined,
  );
}

export function installComponentUpdate(
  componentId: ComponentUpdateId,
  catalogUrl?: string,
): Promise<ComponentInstallResult> {
  return invokeDesktop(
    "install_component_update",
    parseComponentInstallResult,
    { componentId, ...(catalogUrl ? { catalogUrl } : {}) },
  );
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

export function startRuntimeUpgrade(
  request: RuntimeUpgradeRequest = {},
): Promise<RuntimeInstallSnapshot> {
  const releaseManifestUrl = request.releaseManifestUrl == null
    ? null
    : normalizeReleaseManifestUrl(request.releaseManifestUrl);
  return invokeDesktop(
    "start_runtime_upgrade",
    parseRuntimeInstallSnapshot,
    { request: { releaseManifestUrl } },
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
    "attemptIdHash",
    "stateHash",
    "subjectHash",
    "issuedAt",
    "completedAt",
  ]);
  if (record.protocolVersion !== "desktop-browser-auth-pkce-v1") {
    throw new Error("response.protocolVersion is unsupported");
  }
  if (!(["universal", "sim", "lab", "field", "autonomy"] as unknown[]).includes(record.editionId)) {
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

function parseComponentUpdateId(value: unknown, path: string): ComponentUpdateId {
  const componentId = expectString(value, path);
  if (componentId !== "capability-pack" && componentId !== "asset-pack") {
    throw new Error(`${path} must be a supported component pack`);
  }
  return componentId;
}

function parseComponentUpdateUrgency(
  value: unknown,
  path: string,
): ComponentUpdateUrgency {
  const urgency = expectString(value, path);
  if (urgency !== "required" && urgency !== "recommended" && urgency !== "optional") {
    throw new Error(`${path} must be required, recommended, or optional`);
  }
  return urgency;
}

function parseComponentUpdateInstallMode(
  value: unknown,
  path: string,
): ComponentUpdateInstallMode {
  const installMode = expectString(value, path);
  if (installMode !== "automatic" && installMode !== "user-confirmed") {
    throw new Error(`${path} must be automatic or user-confirmed`);
  }
  return installMode;
}

function parseComponentVersion(value: unknown, path: string): string {
  const version = expectString(value, path);
  if (!/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/u.test(version)) {
    throw new Error(`${path} must be semantic versioning`);
  }
  return version;
}

function parseComponentUpdateCandidate(
  value: unknown,
  index: number,
): ComponentUpdateCandidate {
  const path = `componentUpdate.candidates[${index}]`;
  const record = expectRecord(value, path);
  const dependencies = expectArray(
    record.dependencies,
    `${path}.dependencies`,
  ).map((dependency, dependencyIndex) => {
    const dependencyPath = `${path}.dependencies[${dependencyIndex}]`;
    const dependencyRecord = expectRecord(dependency, dependencyPath);
    return {
      componentId: parseComponentUpdateId(
        dependencyRecord.componentId,
        `${dependencyPath}.componentId`,
      ),
      minimumReleaseSequence: expectPositiveInteger(
        dependencyRecord.minimumReleaseSequence,
        `${dependencyPath}.minimumReleaseSequence`,
      ),
    };
  });
  if (dependencies.length > 1) {
    throw new Error(`${path}.dependencies exceeds the signed catalog limit`);
  }
  const candidate: ComponentUpdateCandidate = {
    componentId: parseComponentUpdateId(record.componentId, `${path}.componentId`),
    version: parseComponentVersion(record.version, `${path}.version`),
    releaseSequence: expectPositiveInteger(
      record.releaseSequence,
      `${path}.releaseSequence`,
    ),
    urgency: parseComponentUpdateUrgency(record.urgency, `${path}.urgency`),
    installMode: parseComponentUpdateInstallMode(
      record.installMode,
      `${path}.installMode`,
    ),
    dependencies,
    packId: expectSha256Id(record.packId, `${path}.packId`),
    installedVersion: record.installedVersion == null
      ? null
      : parseComponentVersion(record.installedVersion, `${path}.installedVersion`),
    installedReleaseSequence: expectNonNegativeInteger(
      record.installedReleaseSequence,
      `${path}.installedReleaseSequence`,
    ),
    available: expectBoolean(record.available, `${path}.available`),
  };
  if (candidate.dependencies.some((dependency) => (
    dependency.componentId === candidate.componentId
  ))) {
    throw new Error(`${path}.dependencies may not reference the candidate itself`);
  }
  if (candidate.componentId === "asset-pack" && candidate.installMode === "automatic") {
    throw new Error(`${path}.installMode may not automatically install assets`);
  }
  return candidate;
}

function parseComponentUpdateReport(value: unknown): ComponentUpdateReport {
  const record = expectRecord(value, "componentUpdate");
  const candidates = expectArray(
    record.candidates,
    "componentUpdate.candidates",
  ).map(parseComponentUpdateCandidate);
  if (candidates.length > 2) {
    throw new Error("componentUpdate.candidates exceeds the signed catalog limit");
  }
  assertUnique(
    candidates.map((candidate) => candidate.componentId),
    "componentUpdate.candidates component ids",
  );
  for (const candidate of candidates) {
    for (const dependency of candidate.dependencies) {
      const dependencyCandidate = candidates.find((entry) => (
        entry.componentId === dependency.componentId
      ));
      if (dependencyCandidate?.dependencies.some((nested) => (
        nested.componentId === candidate.componentId
      ))) {
        throw new Error("componentUpdate dependency cycle was rejected");
      }
    }
  }
  const report = {
    catalogSequence: expectPositiveInteger(
      record.catalogSequence,
      "componentUpdate.catalogSequence",
    ),
    generatedAt: expectIsoTimestamp(record.generatedAt, "componentUpdate.generatedAt"),
    expiresAt: expectIsoTimestamp(record.expiresAt, "componentUpdate.expiresAt"),
    candidates,
  };
  if (Date.parse(report.expiresAt) <= Date.parse(report.generatedAt)) {
    throw new Error("componentUpdate expiry must follow generation time");
  }
  return report;
}

function parseComponentInstallResult(value: unknown): ComponentInstallResult {
  const record = expectRecord(value, "componentInstall");
  return {
    componentId: parseComponentUpdateId(
      record.componentId,
      "componentInstall.componentId",
    ),
    packId: expectSha256Id(record.packId, "componentInstall.packId"),
    version: parseComponentVersion(record.version, "componentInstall.version"),
    releaseSequence: expectPositiveInteger(
      record.releaseSequence,
      "componentInstall.releaseSequence",
    ),
    activated: expectBoolean(record.activated, "componentInstall.activated"),
  };
}

function parseFieldTuningStatus(value: unknown): FieldTuningStatus {
  const record = expectRecord(value, "fieldTuningStatus");
  const editionId = expectHardwareDomainEdition(
    record.editionId,
    "fieldTuningStatus.editionId",
  );
  const expectedRuntimeProfile = editionId === "lab"
    ? "unified-sim-lab"
    : editionId === "autonomy"
      ? "autonomy-full"
      : "field-lightweight";
  const status: FieldTuningStatus = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, "fieldTuningStatus.schemaVersion"),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-tuning-status",
      "fieldTuningStatus.kind",
    ),
    editionId,
    executionDomain: expectLiteral(
      record.executionDomain,
      "real-hardware",
      "fieldTuningStatus.executionDomain",
    ),
    runtimeProfile: expectLiteral(
      record.runtimeProfile,
      expectedRuntimeProfile,
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

function parseFieldAdapterCapability(value: unknown, path: string): FieldAdapterCapability {
  if (
    value !== "unavailable"
    && value !== "read-only"
    && value !== "quorum-required"
    && value !== "vendor-controlled"
  ) {
    throw new Error(`${path} is unsupported`);
  }
  return value;
}

function parseFieldAdapterCapabilities(value: unknown, path: string): FieldAdapterCapabilities {
  const record = expectExactRecord(value, path, [
    "deviceDiscovery",
    "telemetryRead",
    "parameterRead",
    "parameterWrite",
    "arm",
    "flight",
    "autonomousTuning",
  ]);
  return {
    deviceDiscovery: parseFieldAdapterCapability(record.deviceDiscovery, `${path}.deviceDiscovery`),
    telemetryRead: parseFieldAdapterCapability(record.telemetryRead, `${path}.telemetryRead`),
    parameterRead: parseFieldAdapterCapability(record.parameterRead, `${path}.parameterRead`),
    parameterWrite: parseFieldAdapterCapability(record.parameterWrite, `${path}.parameterWrite`),
    arm: parseFieldAdapterCapability(record.arm, `${path}.arm`),
    flight: parseFieldAdapterCapability(record.flight, `${path}.flight`),
    autonomousTuning: parseFieldAdapterCapability(
      record.autonomousTuning,
      `${path}.autonomousTuning`,
    ),
  };
}

function parseFieldAdapterEntry(value: unknown, index: number): FieldAdapterCatalogEntry {
  const path = `fieldAdapterCatalog.entries[${index}]`;
  const record = expectExactRecord(value, path, [
    "adapterId",
    "version",
    "displayName",
    "vendor",
    "protocolFamily",
    "implementationStatus",
    "deliveryMode",
    "installable",
    "installed",
    "installedPackageSha256",
    "supportedTransports",
    "supportedPlatforms",
    "packageSha256",
    "capabilities",
    "safety",
  ]);
  const displayName = expectExactRecord(record.displayName, `${path}.displayName`, ["en", "zh-CN"]);
  const safety = expectExactRecord(record.safety, `${path}.safety`, [
    "installationGrantsAuthority",
    "discoveryGrantsAuthority",
    "requiresValidatedVehiclePackForWrites",
    "requiresNativeBackendRuntimeOperatorQuorum",
  ]);
  const implementationStatus = expectString(
    record.implementationStatus,
    `${path}.implementationStatus`,
  );
  if (![
    "available",
    "vendor-access-required",
    "platform-bridge-required",
    "planned",
  ].includes(implementationStatus)) {
    throw new Error(`${path}.implementationStatus is unsupported`);
  }
  const deliveryMode = expectString(record.deliveryMode, `${path}.deliveryMode`);
  if (!["embedded-managed", "vendor-managed", "unavailable"].includes(deliveryMode)) {
    throw new Error(`${path}.deliveryMode is unsupported`);
  }
  const packageSha256 = record.packageSha256 == null
    ? null
    : expectLowercaseHex(record.packageSha256, `${path}.packageSha256`, 64);
  const installedPackageSha256 = record.installedPackageSha256 == null
    ? null
    : expectLowercaseHex(
      record.installedPackageSha256,
      `${path}.installedPackageSha256`,
      64,
    );
  const entry: FieldAdapterCatalogEntry = {
    adapterId: expectIdentifier(record.adapterId, `${path}.adapterId`),
    version: expectSafeNonEmptyString(record.version, `${path}.version`),
    displayName: {
      en: expectSafeNonEmptyString(displayName.en, `${path}.displayName.en`),
      "zh-CN": expectSafeNonEmptyString(displayName["zh-CN"], `${path}.displayName.zh-CN`),
    },
    vendor: expectSafeNonEmptyString(record.vendor, `${path}.vendor`),
    protocolFamily: expectSafeNonEmptyString(record.protocolFamily, `${path}.protocolFamily`),
    implementationStatus: implementationStatus as FieldAdapterCatalogEntry["implementationStatus"],
    deliveryMode: deliveryMode as FieldAdapterCatalogEntry["deliveryMode"],
    installable: expectBoolean(record.installable, `${path}.installable`),
    installed: expectBoolean(record.installed, `${path}.installed`),
    installedPackageSha256,
    supportedTransports: parseSafeNonEmptyStringArray(
      record.supportedTransports,
      `${path}.supportedTransports`,
    ),
    supportedPlatforms: parseSafeNonEmptyStringArray(
      record.supportedPlatforms,
      `${path}.supportedPlatforms`,
    ),
    packageSha256,
    capabilities: parseFieldAdapterCapabilities(record.capabilities, `${path}.capabilities`),
    safety: {
      installationGrantsAuthority: expectLiteral(
        safety.installationGrantsAuthority,
        false,
        `${path}.safety.installationGrantsAuthority`,
      ),
      discoveryGrantsAuthority: expectLiteral(
        safety.discoveryGrantsAuthority,
        false,
        `${path}.safety.discoveryGrantsAuthority`,
      ),
      requiresValidatedVehiclePackForWrites: expectLiteral(
        safety.requiresValidatedVehiclePackForWrites,
        true,
        `${path}.safety.requiresValidatedVehiclePackForWrites`,
      ),
      requiresNativeBackendRuntimeOperatorQuorum: expectLiteral(
        safety.requiresNativeBackendRuntimeOperatorQuorum,
        true,
        `${path}.safety.requiresNativeBackendRuntimeOperatorQuorum`,
      ),
    },
  };
  if (
    entry.installed !== (
      entry.packageSha256 !== null
      && entry.installedPackageSha256 === entry.packageSha256
    )
    || entry.installable !== (
      entry.deliveryMode === "embedded-managed"
      && entry.implementationStatus === "available"
      && entry.packageSha256 !== null
    )
  ) {
    throw new Error(`${path} has inconsistent install state`);
  }
  return entry;
}

function parseFieldAdapterCatalog(value: unknown): FieldAdapterCatalogReport {
  const record = expectExactRecord(value, "fieldAdapterCatalog", [
    "schemaVersion",
    "kind",
    "catalogVersion",
    "editionId",
    "source",
    "catalogSha256",
    "hardwareAuthority",
    "executableExtensionLoading",
    "entries",
  ]);
  const entries = expectArray(record.entries, "fieldAdapterCatalog.entries")
    .map(parseFieldAdapterEntry);
  if (entries.length === 0 || new Set(entries.map((entry) => entry.adapterId)).size !== entries.length) {
    throw new Error("Field adapter catalog must contain unique entries");
  }
  return {
    schemaVersion: expectLiteral(record.schemaVersion, 1, "fieldAdapterCatalog.schemaVersion"),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-adapter-catalog-report",
      "fieldAdapterCatalog.kind",
    ),
    catalogVersion: expectSafeNonEmptyString(
      record.catalogVersion,
      "fieldAdapterCatalog.catalogVersion",
    ),
    editionId: expectHardwareDomainEdition(record.editionId, "fieldAdapterCatalog.editionId"),
    source: expectLiteral(
      record.source,
      "source-bound-embedded-catalog",
      "fieldAdapterCatalog.source",
    ),
    catalogSha256: expectLowercaseHex(
      record.catalogSha256,
      "fieldAdapterCatalog.catalogSha256",
      64,
    ),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldAdapterCatalog.hardwareAuthority",
    ),
    executableExtensionLoading: expectLiteral(
      record.executableExtensionLoading,
      false,
      "fieldAdapterCatalog.executableExtensionLoading",
    ),
    entries,
  };
}

function parseFieldAdapterInstallReceipt(value: unknown): FieldAdapterInstallReceipt {
  const record = expectExactRecord(value, "fieldAdapterInstallReceipt", [
    "schemaVersion",
    "kind",
    "editionId",
    "adapterId",
    "packageSha256",
    "state",
    "executableCodeInstalled",
    "deviceOpenAttempts",
    "hardwareWriteAttempts",
    "hardwareAuthority",
  ]);
  const state = expectString(record.state, "fieldAdapterInstallReceipt.state");
  if (state !== "installed" && state !== "already-installed") {
    throw new Error("fieldAdapterInstallReceipt.state is unsupported");
  }
  return {
    schemaVersion: expectLiteral(record.schemaVersion, 1, "fieldAdapterInstallReceipt.schemaVersion"),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-adapter-install-receipt",
      "fieldAdapterInstallReceipt.kind",
    ),
    editionId: expectHardwareDomainEdition(record.editionId, "fieldAdapterInstallReceipt.editionId"),
    adapterId: expectIdentifier(record.adapterId, "fieldAdapterInstallReceipt.adapterId"),
    packageSha256: expectLowercaseHex(
      record.packageSha256,
      "fieldAdapterInstallReceipt.packageSha256",
      64,
    ),
    state,
    executableCodeInstalled: expectLiteral(
      record.executableCodeInstalled,
      false,
      "fieldAdapterInstallReceipt.executableCodeInstalled",
    ),
    deviceOpenAttempts: expectLiteral(
      record.deviceOpenAttempts,
      0,
      "fieldAdapterInstallReceipt.deviceOpenAttempts",
    ),
    hardwareWriteAttempts: expectLiteral(
      record.hardwareWriteAttempts,
      0,
      "fieldAdapterInstallReceipt.hardwareWriteAttempts",
    ),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldAdapterInstallReceipt.hardwareAuthority",
    ),
  };
}

function parseFieldAdapterFrameInspection(value: unknown): FieldAdapterFrameInspection {
  const record = expectExactRecord(value, "fieldAdapterFrameInspection", [
    "schemaVersion",
    "kind",
    "editionId",
    "adapterId",
    "protocolVersion",
    "systemId",
    "componentId",
    "sequence",
    "messageId",
    "messageName",
    "frameSha256",
    "frameBytes",
    "deviceOpenAttempts",
    "hardwareWriteAttempts",
    "hardwareAuthority",
  ]);
  const protocolVersion = expectBoundedNonNegativeInteger(
    record.protocolVersion,
    "fieldAdapterFrameInspection.protocolVersion",
    2,
  );
  if (protocolVersion !== 1 && protocolVersion !== 2) {
    throw new Error("fieldAdapterFrameInspection.protocolVersion is unsupported");
  }
  const frameBytes = expectBoundedNonNegativeInteger(
    record.frameBytes,
    "fieldAdapterFrameInspection.frameBytes",
    280,
  );
  if (frameBytes === 0) throw new Error("fieldAdapterFrameInspection.frameBytes is out of range");
  const messageName = expectSafeNonEmptyString(
    record.messageName,
    "fieldAdapterFrameInspection.messageName",
  );
  if (!/^[A-Z][A-Z0-9_]{0,127}$/.test(messageName)) {
    throw new Error("fieldAdapterFrameInspection.messageName is malformed");
  }
  return {
    schemaVersion: expectLiteral(
      record.schemaVersion,
      1,
      "fieldAdapterFrameInspection.schemaVersion",
    ),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-adapter-frame-inspection",
      "fieldAdapterFrameInspection.kind",
    ),
    editionId: expectHardwareDomainEdition(record.editionId, "fieldAdapterFrameInspection.editionId"),
    adapterId: expectIdentifier(record.adapterId, "fieldAdapterFrameInspection.adapterId"),
    protocolVersion,
    systemId: expectBoundedNonNegativeInteger(
      record.systemId,
      "fieldAdapterFrameInspection.systemId",
      255,
    ),
    componentId: expectBoundedNonNegativeInteger(
      record.componentId,
      "fieldAdapterFrameInspection.componentId",
      255,
    ),
    sequence: expectBoundedNonNegativeInteger(
      record.sequence,
      "fieldAdapterFrameInspection.sequence",
      255,
    ),
    messageId: expectBoundedNonNegativeInteger(
      record.messageId,
      "fieldAdapterFrameInspection.messageId",
      16_777_215,
    ),
    messageName,
    frameSha256: expectLowercaseHex(
      record.frameSha256,
      "fieldAdapterFrameInspection.frameSha256",
      64,
    ),
    frameBytes,
    deviceOpenAttempts: expectLiteral(
      record.deviceOpenAttempts,
      0,
      "fieldAdapterFrameInspection.deviceOpenAttempts",
    ),
    hardwareWriteAttempts: expectLiteral(
      record.hardwareWriteAttempts,
      0,
      "fieldAdapterFrameInspection.hardwareWriteAttempts",
    ),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldAdapterFrameInspection.hardwareAuthority",
    ),
  };
}

function parseFieldProtocolFrameInspection(
  value: unknown,
): FieldProtocolFrameInspection {
  const record = expectExactRecord(value, "fieldProtocolFrameInspection", [
    "schemaVersion",
    "kind",
    "editionId",
    "adapterId",
    "protocolFamily",
    "classification",
    "fields",
    "frameSha256",
    "frameBytes",
    "deviceOpenAttempts",
    "hardwareWriteAttempts",
    "hardwareAuthority",
  ]);
  const rawFields = expectRecord(
    record.fields,
    "fieldProtocolFrameInspection.fields",
  );
  const fieldEntries = Object.entries(rawFields);
  if (fieldEntries.length === 0 || fieldEntries.length > 16) {
    throw new Error("fieldProtocolFrameInspection.fields is outside its bounded shape");
  }
  const fields: Record<string, string | number | boolean> = {};
  for (const [key, raw] of fieldEntries) {
    if (!/^[a-z][A-Za-z0-9]{0,31}$/.test(key)) {
      throw new Error("fieldProtocolFrameInspection.fields contains an invalid key");
    }
    if (typeof raw === "string") {
      const parsed = expectSafeNonEmptyString(
        raw,
        `fieldProtocolFrameInspection.fields.${key}`,
      );
      if (parsed.length > 160) {
        throw new Error(`fieldProtocolFrameInspection.fields.${key} is too long`);
      }
      fields[key] = parsed;
    } else if (typeof raw === "number") {
      if (!Number.isSafeInteger(raw) || raw < 0 || raw > 0xffff_ffff) {
        throw new Error(`fieldProtocolFrameInspection.fields.${key} is out of range`);
      }
      fields[key] = raw;
    } else if (typeof raw === "boolean") {
      fields[key] = raw;
    } else {
      throw new Error(`fieldProtocolFrameInspection.fields.${key} is not scalar`);
    }
  }
  const protocolFamily = expectSafeNonEmptyString(
    record.protocolFamily,
    "fieldProtocolFrameInspection.protocolFamily",
  );
  const classification = expectSafeNonEmptyString(
    record.classification,
    "fieldProtocolFrameInspection.classification",
  );
  if (protocolFamily.length > 80 || classification.length > 160) {
    throw new Error("fieldProtocolFrameInspection classification is too long");
  }
  const frameBytes = expectBoundedNonNegativeInteger(
    record.frameBytes,
    "fieldProtocolFrameInspection.frameBytes",
    280,
  );
  if (frameBytes === 0) {
    throw new Error("fieldProtocolFrameInspection.frameBytes is out of range");
  }
  return {
    schemaVersion: expectLiteral(
      record.schemaVersion,
      1,
      "fieldProtocolFrameInspection.schemaVersion",
    ),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-protocol-frame-inspection",
      "fieldProtocolFrameInspection.kind",
    ),
    editionId: expectHardwareDomainEdition(
      record.editionId,
      "fieldProtocolFrameInspection.editionId",
    ),
    adapterId: expectIdentifier(
      record.adapterId,
      "fieldProtocolFrameInspection.adapterId",
    ),
    protocolFamily,
    classification,
    fields,
    frameSha256: expectLowercaseHex(
      record.frameSha256,
      "fieldProtocolFrameInspection.frameSha256",
      64,
    ),
    frameBytes,
    deviceOpenAttempts: expectLiteral(
      record.deviceOpenAttempts,
      0,
      "fieldProtocolFrameInspection.deviceOpenAttempts",
    ),
    hardwareWriteAttempts: expectLiteral(
      record.hardwareWriteAttempts,
      0,
      "fieldProtocolFrameInspection.hardwareWriteAttempts",
    ),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldProtocolFrameInspection.hardwareAuthority",
    ),
  };
}

function parseFieldMavlinkTelemetryProbeReceipt(
  value: unknown,
): FieldMavlinkTelemetryProbeReceipt {
  const record = expectExactRecord(value, "fieldMavlinkTelemetryProbeReceipt", [
    "schemaVersion",
    "kind",
    "editionId",
    "adapterId",
    "observationId",
    "portName",
    "baudRate",
    "protocolVersion",
    "systemId",
    "componentId",
    "sequence",
    "messageId",
    "messageName",
    "frameSha256",
    "frameBytes",
    "deviceOpenAttempts",
    "telemetryReadAttempts",
    "parameterReadAttempts",
    "hardwareWriteAttempts",
    "armAttempts",
    "flightAttempts",
    "hardwareAuthority",
  ]);
  const protocolVersion = expectBoundedNonNegativeInteger(
    record.protocolVersion,
    "fieldMavlinkTelemetryProbeReceipt.protocolVersion",
    2,
  );
  if (protocolVersion !== 1 && protocolVersion !== 2) {
    throw new Error("fieldMavlinkTelemetryProbeReceipt.protocolVersion is unsupported");
  }
  const portName = expectSafeNonEmptyString(
    record.portName,
    "fieldMavlinkTelemetryProbeReceipt.portName",
  );
  if (!/^COM(?:[1-9][0-9]{0,2})$/.test(portName)) {
    throw new Error("fieldMavlinkTelemetryProbeReceipt.portName is malformed");
  }
  const baudRate = expectBoundedNonNegativeInteger(
    record.baudRate,
    "fieldMavlinkTelemetryProbeReceipt.baudRate",
    921_600,
  );
  if (![57_600, 115_200, 230_400, 460_800, 921_600].includes(baudRate)) {
    throw new Error("fieldMavlinkTelemetryProbeReceipt.baudRate is unsupported");
  }
  const frameBytes = expectBoundedNonNegativeInteger(
    record.frameBytes,
    "fieldMavlinkTelemetryProbeReceipt.frameBytes",
    280,
  );
  if (frameBytes === 0) {
    throw new Error("fieldMavlinkTelemetryProbeReceipt.frameBytes is out of range");
  }
  const messageName = expectSafeNonEmptyString(
    record.messageName,
    "fieldMavlinkTelemetryProbeReceipt.messageName",
  );
  if (!/^[A-Z][A-Z0-9_]{0,127}$/.test(messageName)) {
    throw new Error("fieldMavlinkTelemetryProbeReceipt.messageName is malformed");
  }
  return {
    schemaVersion: expectLiteral(
      record.schemaVersion,
      1,
      "fieldMavlinkTelemetryProbeReceipt.schemaVersion",
    ),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-mavlink-telemetry-probe-receipt",
      "fieldMavlinkTelemetryProbeReceipt.kind",
    ),
    editionId: expectHardwareDomainEdition(
      record.editionId,
      "fieldMavlinkTelemetryProbeReceipt.editionId",
    ),
    adapterId: expectIdentifier(
      record.adapterId,
      "fieldMavlinkTelemetryProbeReceipt.adapterId",
    ),
    observationId: expectLowercaseHex(
      record.observationId,
      "fieldMavlinkTelemetryProbeReceipt.observationId",
      64,
    ),
    portName,
    baudRate,
    protocolVersion,
    systemId: expectBoundedNonNegativeInteger(
      record.systemId,
      "fieldMavlinkTelemetryProbeReceipt.systemId",
      255,
    ),
    componentId: expectBoundedNonNegativeInteger(
      record.componentId,
      "fieldMavlinkTelemetryProbeReceipt.componentId",
      255,
    ),
    sequence: expectBoundedNonNegativeInteger(
      record.sequence,
      "fieldMavlinkTelemetryProbeReceipt.sequence",
      255,
    ),
    messageId: expectBoundedNonNegativeInteger(
      record.messageId,
      "fieldMavlinkTelemetryProbeReceipt.messageId",
      16_777_215,
    ),
    messageName,
    frameSha256: expectLowercaseHex(
      record.frameSha256,
      "fieldMavlinkTelemetryProbeReceipt.frameSha256",
      64,
    ),
    frameBytes,
    deviceOpenAttempts: expectLiteral(
      record.deviceOpenAttempts,
      1,
      "fieldMavlinkTelemetryProbeReceipt.deviceOpenAttempts",
    ),
    telemetryReadAttempts: expectLiteral(
      record.telemetryReadAttempts,
      1,
      "fieldMavlinkTelemetryProbeReceipt.telemetryReadAttempts",
    ),
    parameterReadAttempts: expectLiteral(
      record.parameterReadAttempts,
      0,
      "fieldMavlinkTelemetryProbeReceipt.parameterReadAttempts",
    ),
    hardwareWriteAttempts: expectLiteral(
      record.hardwareWriteAttempts,
      0,
      "fieldMavlinkTelemetryProbeReceipt.hardwareWriteAttempts",
    ),
    armAttempts: expectLiteral(
      record.armAttempts,
      0,
      "fieldMavlinkTelemetryProbeReceipt.armAttempts",
    ),
    flightAttempts: expectLiteral(
      record.flightAttempts,
      0,
      "fieldMavlinkTelemetryProbeReceipt.flightAttempts",
    ),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldMavlinkTelemetryProbeReceipt.hardwareAuthority",
    ),
  };
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
    editionId: expectHardwareDomainEdition(record.editionId, "fieldDeviceDiscovery.editionId"),
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
    editionId: expectHardwareDomainEdition(record.editionId, "fieldTuningReceipt.editionId"),
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

function validateFieldHarnessRequest(request: FieldHarnessJobRequest): void {
  const identities = [
    request.jobName,
    request.objective,
    request.deviceObservationId,
    request.vehiclePackId,
    request.controllerId,
    request.firmwareVersion,
    request.adapterId,
  ];
  if (
    identities.some((value) => value.trim() !== value || value.length === 0 || value.length > 240)
    || !/^[a-f0-9]{64}$/.test(request.observationSha256)
    || !/^[a-f0-9]{64}$/.test(request.snapshotSha256)
    || !Number.isFinite(request.targetScore)
    || request.targetScore < 0.01
    || request.targetScore > 1
    || !Number.isInteger(request.maxIterations)
    || request.maxIterations < 2
    || request.maxIterations > 32
    || request.trials.length < 3
    || request.trials.length > 32
  ) {
    throw new Error("Field Harness request is outside its bounded contract.");
  }
  const names = Object.keys(request.parameterBounds).sort();
  if (names.length === 0 || names.length > 64) {
    throw new Error("Field Harness parameter bounds are empty or oversized.");
  }
  for (const name of names) {
    const bound = request.parameterBounds[name];
    if (
      !/^[A-Za-z0-9_.:-]{1,80}$/.test(name)
      || !Number.isFinite(bound.min)
      || !Number.isFinite(bound.max)
      || !Number.isFinite(bound.maxStep)
      || bound.min >= bound.max
      || bound.maxStep <= 0
      || bound.maxStep > bound.max - bound.min
    ) {
      throw new Error(`Field Harness parameter bound ${name} is invalid.`);
    }
  }
  for (const trial of request.trials) {
    const trialNames = Object.keys(trial.parameters).sort();
    if (
      trial.trialId.trim() !== trial.trialId
      || trial.trialId.length === 0
      || trial.trialId.length > 80
      || !/^[a-f0-9]{64}$/.test(trial.telemetrySha256)
      || trialNames.join("\n") !== names.join("\n")
    ) {
      throw new Error("Field Harness trial identity or parameter set is invalid.");
    }
    for (const name of names) {
      const parameter = trial.parameters[name];
      const bound = request.parameterBounds[name];
      if (!Number.isFinite(parameter) || parameter < bound.min || parameter > bound.max) {
        throw new Error(`Field Harness trial parameter ${name} is outside its bound.`);
      }
    }
    const metrics = trial.metrics;
    if (
      ![metrics.trackingError, metrics.overshootPercent, metrics.controlEffort]
        .every((metric) => Number.isFinite(metric) && metric >= 0 && metric <= 1_000)
      || !Number.isSafeInteger(metrics.constraintViolations)
      || metrics.constraintViolations < 0
      || !Number.isSafeInteger(metrics.emergencyInterventions)
      || metrics.emergencyInterventions < 0
    ) {
      throw new Error("Field Harness trial metrics are invalid.");
    }
  }
  if (
    request.trials.filter((trial) => trial.independentHoldout).length !== 1
    || request.trials.at(-1)?.independentHoldout !== true
  ) {
    throw new Error("Field Harness requires one final independent holdout trial.");
  }
}

function parseFieldHarnessMetrics(value: unknown, path: string): FieldHarnessMetrics {
  const record = expectRecord(value, path);
  return {
    trackingError: expectFiniteNumber(record.trackingError, `${path}.trackingError`),
    overshootPercent: expectFiniteNumber(record.overshootPercent, `${path}.overshootPercent`),
    controlEffort: expectFiniteNumber(record.controlEffort, `${path}.controlEffort`),
    constraintViolations: expectNonNegativeInteger(
      record.constraintViolations,
      `${path}.constraintViolations`,
    ),
    emergencyInterventions: expectNonNegativeInteger(
      record.emergencyInterventions,
      `${path}.emergencyInterventions`,
    ),
  };
}

function parseFieldHarnessTrial(value: unknown, index: number): FieldHarnessTrialReceipt {
  const path = `fieldHarnessJob.trials[${index}]`;
  const record = expectRecord(value, path);
  const failureClass = expectString(record.failureClass, `${path}.failureClass`);
  if (![
    "none",
    "objective-miss",
    "constraint-violation",
    "emergency-intervention",
  ].includes(failureClass)) {
    throw new Error(`${path}.failureClass is unsupported`);
  }
  return {
    trialId: expectSafeNonEmptyString(record.trialId, `${path}.trialId`),
    telemetrySha256: expectLowercaseHex(record.telemetrySha256, `${path}.telemetrySha256`, 64),
    candidateSha256: expectLowercaseHex(record.candidateSha256, `${path}.candidateSha256`, 64),
    parameters: parseFieldParameterMap(record.parameters, `${path}.parameters`),
    metrics: parseFieldHarnessMetrics(record.metrics, `${path}.metrics`),
    score: expectFiniteNumber(record.score, `${path}.score`),
    accepted: expectBoolean(record.accepted, `${path}.accepted`),
    failureClass: failureClass as FieldHarnessTrialReceipt["failureClass"],
    independentHoldout: expectBoolean(record.independentHoldout, `${path}.independentHoldout`),
  };
}

function parseFieldHarnessJobReceipt(value: unknown): FieldHarnessJobReceipt {
  const path = "fieldHarnessJob";
  const record = expectRecord(value, path);
  const budget = expectRecord(record.budget, `${path}.budget`);
  const qualification = expectRecord(record.qualification, `${path}.qualification`);
  const status = expectString(qualification.status, `${path}.qualification.status`);
  if (status !== "recorded-evidence-passed" && status !== "recorded-evidence-rejected") {
    throw new Error(`${path}.qualification.status is unsupported`);
  }
  const receipt: FieldHarnessJobReceipt = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, `${path}.schemaVersion`),
    kind: expectLiteral(record.kind, "dronedream-field-harness-job-receipt", `${path}.kind`),
    jobId: expectSafeNonEmptyString(record.jobId, `${path}.jobId`),
    createdAt: expectSafeNonEmptyString(record.createdAt, `${path}.createdAt`),
    editionId: expectHardwareDomainEdition(record.editionId, `${path}.editionId`),
    executionDomain: expectLiteral(
      record.executionDomain,
      "real-device-recorded-evidence",
      `${path}.executionDomain`,
    ),
    executionMode: expectLiteral(
      record.executionMode,
      "offline-evidence-replay-no-device-io",
      `${path}.executionMode`,
    ),
    sourceCommit: expectLowercaseHex(record.sourceCommit, `${path}.sourceCommit`, 40),
    enginePackId: expectSha256Id(record.enginePackId, `${path}.enginePackId`),
    requestSha256: expectLowercaseHex(record.requestSha256, `${path}.requestSha256`, 64),
    jobName: expectSafeNonEmptyString(record.jobName, `${path}.jobName`),
    objective: expectSafeNonEmptyString(record.objective, `${path}.objective`),
    targetScore: expectFiniteNumber(record.targetScore, `${path}.targetScore`),
    deviceObservationId: expectSafeNonEmptyString(
      record.deviceObservationId,
      `${path}.deviceObservationId`,
    ),
    observationSha256: expectLowercaseHex(
      record.observationSha256,
      `${path}.observationSha256`,
      64,
    ),
    snapshotSha256: expectLowercaseHex(record.snapshotSha256, `${path}.snapshotSha256`, 64),
    vehiclePackId: expectSafeNonEmptyString(record.vehiclePackId, `${path}.vehiclePackId`),
    controllerId: expectSafeNonEmptyString(record.controllerId, `${path}.controllerId`),
    firmwareVersion: expectSafeNonEmptyString(record.firmwareVersion, `${path}.firmwareVersion`),
    adapterId: expectSafeNonEmptyString(record.adapterId, `${path}.adapterId`),
    budget: {
      maxIterations: expectPositiveInteger(budget.maxIterations, `${path}.budget.maxIterations`),
      usedTrainingTrials: expectPositiveInteger(
        budget.usedTrainingTrials,
        `${path}.budget.usedTrainingTrials`,
      ),
      usedHoldoutTrials: expectLiteral(
        budget.usedHoldoutTrials,
        1,
        `${path}.budget.usedHoldoutTrials`,
      ),
      remainingIterations: expectNonNegativeInteger(
        budget.remainingIterations,
        `${path}.budget.remainingIterations`,
      ),
    },
    trials: expectArray(record.trials, `${path}.trials`).map(parseFieldHarnessTrial),
    selectedCandidateSha256: expectLowercaseHex(
      record.selectedCandidateSha256,
      `${path}.selectedCandidateSha256`,
      64,
    ),
    proposedParameters: parseFieldParameterMap(
      record.proposedParameters,
      `${path}.proposedParameters`,
    ),
    proposedCandidateSha256: expectLowercaseHex(
      record.proposedCandidateSha256,
      `${path}.proposedCandidateSha256`,
      64,
    ),
    holdoutTrialId: expectSafeNonEmptyString(record.holdoutTrialId, `${path}.holdoutTrialId`),
    qualification: {
      status,
      recordedEvidencePassed: expectBoolean(
        qualification.recordedEvidencePassed,
        `${path}.qualification.recordedEvidencePassed`,
      ),
      hardwareValid: expectLiteral(
        qualification.hardwareValid,
        false,
        `${path}.qualification.hardwareValid`,
      ),
      reason: expectSafeNonEmptyString(qualification.reason, `${path}.qualification.reason`),
    },
    blockers: parseSafeNonEmptyStringArray(record.blockers, `${path}.blockers`),
    providerRequests: expectLiteral(record.providerRequests, 0, `${path}.providerRequests`),
    deviceOpenAttempts: expectLiteral(record.deviceOpenAttempts, 0, `${path}.deviceOpenAttempts`),
    hardwareWriteAttempts: expectLiteral(
      record.hardwareWriteAttempts,
      0,
      `${path}.hardwareWriteAttempts`,
    ),
    armAttempts: expectLiteral(record.armAttempts, 0, `${path}.armAttempts`),
    flightAttempts: expectLiteral(record.flightAttempts, 0, `${path}.flightAttempts`),
    hardwareAuthority: expectLiteral(record.hardwareAuthority, false, `${path}.hardwareAuthority`),
    receiptSha256: expectLowercaseHex(record.receiptSha256, `${path}.receiptSha256`, 64),
  };
  if (
    receipt.trials.filter((trial) => trial.independentHoldout).length !== 1
    || !receipt.trials.some(
      (trial) => trial.candidateSha256 === receipt.selectedCandidateSha256,
    )
  ) {
    throw new Error("Field Harness receipt violates holdout or selection semantics");
  }
  return receipt;
}

function parseFieldHarnessJobSummaries(value: unknown): FieldHarnessJobSummary[] {
  const records = expectArray(value, "fieldHarnessJobSummaries");
  if (records.length > 1_000) throw new Error("Field Harness job history is oversized");
  return records.map((value, index) => {
    const path = `fieldHarnessJobSummaries[${index}]`;
    const record = expectRecord(value, path);
    const status = expectString(record.qualificationStatus, `${path}.qualificationStatus`);
    if (status !== "recorded-evidence-passed" && status !== "recorded-evidence-rejected") {
      throw new Error(`${path}.qualificationStatus is unsupported`);
    }
    return {
      jobId: expectSafeNonEmptyString(record.jobId, `${path}.jobId`),
      createdAt: expectSafeNonEmptyString(record.createdAt, `${path}.createdAt`),
      jobName: expectSafeNonEmptyString(record.jobName, `${path}.jobName`),
      objective: expectSafeNonEmptyString(record.objective, `${path}.objective`),
      qualificationStatus: status,
      recordedEvidencePassed: expectBoolean(
        record.recordedEvidencePassed,
        `${path}.recordedEvidencePassed`,
      ),
      hardwareValid: expectLiteral(record.hardwareValid, false, `${path}.hardwareValid`),
      receiptSha256: expectLowercaseHex(record.receiptSha256, `${path}.receiptSha256`, 64),
    };
  });
}

function parseFieldParameterMap(value: unknown, path: string): Record<string, number> {
  const record = expectRecord(value, path);
  const entries = Object.entries(record);
  if (entries.length === 0 || entries.length > 256) {
    throw new Error(`${path} must contain 1 to 256 parameters`);
  }
  return Object.fromEntries(entries.map(([name, raw]) => {
    if (!/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(name)) {
      throw new Error(`${path} contains an invalid parameter name`);
    }
    const parsed = expectFiniteNumber(raw, `${path}.${name}`);
    if (Math.abs(parsed) > 1_000_000_000) {
      throw new Error(`${path}.${name} is outside its numeric bound`);
    }
    return [name, parsed];
  }));
}

function validateFieldParameterMap(parameters: Record<string, number>, path: string): void {
  parseFieldParameterMap(parameters, path);
}

function validateFieldSnapshotRequest(request: FieldParameterSnapshotRequest): void {
  for (const value of [
    request.deviceObservationId,
    request.vehiclePackId,
    request.controllerId,
    request.firmwareVersion,
  ]) {
    if (!/^[A-Za-z0-9][-A-Za-z0-9 .:_/+]{0,159}$/.test(value) || value.trim() !== value) {
      throw new Error("Field parameter snapshot identity is invalid.");
    }
  }
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(request.adapterId) || request.adapterId.length > 64) {
    throw new Error("Field parameter snapshot adapter ID is invalid.");
  }
  if (!/^[a-f0-9]{64}$/.test(request.observationSha256)) {
    throw new Error("Field parameter snapshot observation hash is invalid.");
  }
  validateFieldParameterMap(request.parameters, "fieldParameterSnapshotRequest.parameters");
}

function validateFieldDiffRequest(request: FieldParameterDiffRequest): void {
  if (!/^[a-f0-9]{64}$/.test(request.snapshotSha256)) {
    throw new Error("Field parameter snapshot hash is invalid.");
  }
  validateFieldParameterMap(request.currentParameters, "fieldParameterDiffRequest.currentParameters");
}

function parseFieldParameterChange(value: unknown, index: number): FieldParameterChange {
  const path = `fieldParameterChanges[${index}]`;
  const record = expectExactRecord(value, path, ["name", "before", "after", "delta"]);
  const nullableNumber = (raw: unknown, field: string): number | null => {
    if (raw === null) return null;
    const parsed = expectFiniteNumber(raw, `${path}.${field}`);
    if (Math.abs(parsed) > 2_000_000_000) {
      throw new Error(`${path}.${field} is outside its numeric bound`);
    }
    return parsed;
  };
  const name = expectSafeNonEmptyString(record.name, `${path}.name`);
  if (!/^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(name)) {
    throw new Error(`${path}.name is invalid`);
  }
  const change = {
    name,
    before: nullableNumber(record.before, "before"),
    after: nullableNumber(record.after, "after"),
    delta: nullableNumber(record.delta, "delta"),
  };
  if (change.before === null && change.after === null) {
    throw new Error(`${path} has no value on either side`);
  }
  if ((change.before === null || change.after === null) !== (change.delta === null)) {
    throw new Error(`${path}.delta does not match added or removed semantics`);
  }
  if (
    change.before !== null
    && change.after !== null
    && change.delta !== null
    && Math.abs(change.delta - (change.after - change.before))
      > Number.EPSILON * Math.max(1, Math.abs(change.delta)) * 4
  ) {
    throw new Error(`${path}.delta does not match its values`);
  }
  return change;
}

function parseFieldParameterChanges(value: unknown, path: string): FieldParameterChange[] {
  const raw = expectArray(value, path);
  if (raw.length > 256) throw new Error(`${path} exceeds its bounded length`);
  const changes = raw.map(parseFieldParameterChange);
  if (new Set(changes.map((change) => change.name)).size !== changes.length) {
    throw new Error(`${path} contains duplicate parameter names`);
  }
  return changes;
}

function parseFieldRecoveryIdentity(value: unknown, path: string): string {
  const parsed = expectSafeNonEmptyString(value, path);
  if (!/^[A-Za-z0-9][-A-Za-z0-9 .:_/+]{0,159}$/.test(parsed) || parsed.trim() !== parsed) {
    throw new Error(`${path} is invalid`);
  }
  return parsed;
}

function parseFieldParameterSnapshot(value: unknown): FieldParameterSnapshot {
  const path = "fieldParameterSnapshot";
  const record = expectExactRecord(value, path, [
    "schemaVersion", "kind", "editionId", "executionDomain", "evidenceSource",
    "sourceCommit", "deviceObservationId", "vehiclePackId", "controllerId",
    "firmwareVersion", "adapterId", "observationSha256", "parameterCount",
    "parameters", "parameterSetSha256", "snapshotSha256", "deviceOpenAttempts",
    "hardwareWriteAttempts", "hardwareAuthority",
  ]);
  const parameters = parseFieldParameterMap(record.parameters, `${path}.parameters`);
  const parameterCount = expectBoundedNonNegativeInteger(
    record.parameterCount,
    `${path}.parameterCount`,
    256,
  );
  if (parameterCount !== Object.keys(parameters).length || parameterCount === 0) {
    throw new Error(`${path}.parameterCount does not match the parameter set`);
  }
  return {
    schemaVersion: expectLiteral(record.schemaVersion, 1, `${path}.schemaVersion`),
    kind: expectLiteral(record.kind, "dronedream-field-parameter-snapshot", `${path}.kind`),
    editionId: expectHardwareDomainEdition(record.editionId, `${path}.editionId`),
    executionDomain: expectLiteral(record.executionDomain, "real-hardware", `${path}.executionDomain`),
    evidenceSource: expectLiteral(
      record.evidenceSource,
      "operator-imported-read-only",
      `${path}.evidenceSource`,
    ),
    sourceCommit: expectLowercaseHex(record.sourceCommit, `${path}.sourceCommit`, 40),
    deviceObservationId: parseFieldRecoveryIdentity(record.deviceObservationId, `${path}.deviceObservationId`),
    vehiclePackId: parseFieldRecoveryIdentity(record.vehiclePackId, `${path}.vehiclePackId`),
    controllerId: parseFieldRecoveryIdentity(record.controllerId, `${path}.controllerId`),
    firmwareVersion: parseFieldRecoveryIdentity(record.firmwareVersion, `${path}.firmwareVersion`),
    adapterId: expectIdentifier(record.adapterId, `${path}.adapterId`),
    observationSha256: expectLowercaseHex(record.observationSha256, `${path}.observationSha256`, 64),
    parameterCount,
    parameters,
    parameterSetSha256: expectLowercaseHex(record.parameterSetSha256, `${path}.parameterSetSha256`, 64),
    snapshotSha256: expectLowercaseHex(record.snapshotSha256, `${path}.snapshotSha256`, 64),
    deviceOpenAttempts: expectLiteral(record.deviceOpenAttempts, 0, `${path}.deviceOpenAttempts`),
    hardwareWriteAttempts: expectLiteral(record.hardwareWriteAttempts, 0, `${path}.hardwareWriteAttempts`),
    hardwareAuthority: expectLiteral(record.hardwareAuthority, false, `${path}.hardwareAuthority`),
  };
}

function parseFieldParameterSnapshotSummary(
  value: unknown,
  index: number,
): FieldParameterSnapshotSummary {
  const path = `fieldParameterSnapshotSummaries[${index}]`;
  const record = expectExactRecord(value, path, [
    "schemaVersion", "kind", "editionId", "sourceCommit", "deviceObservationId",
    "vehiclePackId", "controllerId", "firmwareVersion", "adapterId",
    "observationSha256", "parameterCount", "parameterSetSha256", "snapshotSha256",
    "deviceOpenAttempts", "hardwareWriteAttempts", "hardwareAuthority",
  ]);
  const parameterCount = expectBoundedNonNegativeInteger(
    record.parameterCount,
    `${path}.parameterCount`,
    256,
  );
  if (parameterCount === 0) {
    throw new Error(`${path}.parameterCount must be positive`);
  }
  return {
    schemaVersion: expectLiteral(record.schemaVersion, 1, `${path}.schemaVersion`),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-parameter-snapshot-summary",
      `${path}.kind`,
    ),
    editionId: expectHardwareDomainEdition(record.editionId, `${path}.editionId`),
    sourceCommit: expectLowercaseHex(record.sourceCommit, `${path}.sourceCommit`, 40),
    deviceObservationId: parseFieldRecoveryIdentity(
      record.deviceObservationId,
      `${path}.deviceObservationId`,
    ),
    vehiclePackId: parseFieldRecoveryIdentity(record.vehiclePackId, `${path}.vehiclePackId`),
    controllerId: parseFieldRecoveryIdentity(record.controllerId, `${path}.controllerId`),
    firmwareVersion: parseFieldRecoveryIdentity(
      record.firmwareVersion,
      `${path}.firmwareVersion`,
    ),
    adapterId: expectIdentifier(record.adapterId, `${path}.adapterId`),
    observationSha256: expectLowercaseHex(
      record.observationSha256,
      `${path}.observationSha256`,
      64,
    ),
    parameterCount,
    parameterSetSha256: expectLowercaseHex(
      record.parameterSetSha256,
      `${path}.parameterSetSha256`,
      64,
    ),
    snapshotSha256: expectLowercaseHex(
      record.snapshotSha256,
      `${path}.snapshotSha256`,
      64,
    ),
    deviceOpenAttempts: expectLiteral(
      record.deviceOpenAttempts,
      0,
      `${path}.deviceOpenAttempts`,
    ),
    hardwareWriteAttempts: expectLiteral(
      record.hardwareWriteAttempts,
      0,
      `${path}.hardwareWriteAttempts`,
    ),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      `${path}.hardwareAuthority`,
    ),
  };
}

function parseFieldParameterSnapshotSummaries(
  value: unknown,
): FieldParameterSnapshotSummary[] {
  const records = expectArray(value, "fieldParameterSnapshotSummaries");
  if (records.length > 128) {
    throw new Error("fieldParameterSnapshotSummaries exceeds its bounded length");
  }
  const summaries = records.map(parseFieldParameterSnapshotSummary);
  if (summaries.some((summary, index) => (
    index > 0 && summaries[index - 1]!.snapshotSha256 >= summary.snapshotSha256
  ))) {
    throw new Error("fieldParameterSnapshotSummaries is not strictly ordered");
  }
  return summaries;
}

function parseFieldParameterDiffReceipt(value: unknown): FieldParameterDiffReceipt {
  const path = "fieldParameterDiff";
  const record = expectExactRecord(value, path, [
    "schemaVersion", "kind", "editionId", "snapshotSha256",
    "currentParameterSetSha256", "changedCount", "changes", "deviceOpenAttempts",
    "hardwareWriteAttempts", "hardwareAuthority", "receiptSha256",
  ]);
  const changes = parseFieldParameterChanges(record.changes, `${path}.changes`);
  const changedCount = expectBoundedNonNegativeInteger(record.changedCount, `${path}.changedCount`, 256);
  if (changes.length !== changedCount) {
    throw new Error(`${path}.changedCount does not match its changes`);
  }
  return {
    schemaVersion: expectLiteral(record.schemaVersion, 1, `${path}.schemaVersion`),
    kind: expectLiteral(record.kind, "dronedream-field-parameter-diff", `${path}.kind`),
    editionId: expectHardwareDomainEdition(record.editionId, `${path}.editionId`),
    snapshotSha256: expectLowercaseHex(record.snapshotSha256, `${path}.snapshotSha256`, 64),
    currentParameterSetSha256: expectLowercaseHex(
      record.currentParameterSetSha256,
      `${path}.currentParameterSetSha256`,
      64,
    ),
    changedCount,
    changes,
    deviceOpenAttempts: expectLiteral(record.deviceOpenAttempts, 0, `${path}.deviceOpenAttempts`),
    hardwareWriteAttempts: expectLiteral(record.hardwareWriteAttempts, 0, `${path}.hardwareWriteAttempts`),
    hardwareAuthority: expectLiteral(record.hardwareAuthority, false, `${path}.hardwareAuthority`),
    receiptSha256: expectLowercaseHex(record.receiptSha256, `${path}.receiptSha256`, 64),
  };
}

function parseFieldRollbackPlan(value: unknown): FieldRollbackPlan {
  const path = "fieldRollbackPlan";
  const record = expectExactRecord(value, path, [
    "schemaVersion", "kind", "editionId", "snapshotSha256", "planSha256",
    "changes", "canExecute", "hardwareAuthority", "hardwareWriteAttempts",
    "requiredEvidence", "blockers",
  ]);
  const plan: FieldRollbackPlan = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, `${path}.schemaVersion`),
    kind: expectLiteral(record.kind, "dronedream-field-rollback-plan", `${path}.kind`),
    editionId: expectHardwareDomainEdition(record.editionId, `${path}.editionId`),
    snapshotSha256: expectLowercaseHex(record.snapshotSha256, `${path}.snapshotSha256`, 64),
    planSha256: expectLowercaseHex(record.planSha256, `${path}.planSha256`, 64),
    changes: parseFieldParameterChanges(record.changes, `${path}.changes`),
    canExecute: expectLiteral(record.canExecute, false, `${path}.canExecute`),
    hardwareAuthority: expectLiteral(record.hardwareAuthority, false, `${path}.hardwareAuthority`),
    hardwareWriteAttempts: expectLiteral(record.hardwareWriteAttempts, 0, `${path}.hardwareWriteAttempts`),
    requiredEvidence: parseSafeNonEmptyStringArray(record.requiredEvidence, `${path}.requiredEvidence`),
    blockers: parseSafeNonEmptyStringArray(record.blockers, `${path}.blockers`),
  };
  if (
    plan.requiredEvidence.length < 6
    || !plan.blockers.includes("field.registry.zero-validated-packs")
    || !plan.blockers.includes("field.snapshot.rollback-write-disabled")
  ) {
    throw new Error("Field rollback plan weakened its native safety boundary");
  }
  return plan;
}

function parseFieldPreflightPlan(value: unknown): FieldPreflightPlan {
  const path = "fieldPreflightPlan";
  const record = expectExactRecord(value, path, [
    "schemaVersion", "kind", "editionId", "executionDomain", "sourceCommit",
    "requestSha256", "planSha256", "validatedPackCount", "zone", "quorum",
    "actionDecisions", "requiredEvidence", "blockers", "canExecute",
    "hardwareAuthority", "deviceOpenAttempts", "hardwareWriteAttempts",
  ]);
  const zone = expectExactRecord(record.zone, `${path}.zone`, [
    "name", "radiusM", "maxAltitudeM", "evidenceState",
  ]);
  const quorumRecord = expectRecord(record.quorum, `${path}.quorum`);
  const quorum = Object.fromEntries(Object.entries(quorumRecord).map(([key, raw]) => [
    key,
    expectSafeNonEmptyString(raw, `${path}.quorum.${key}`),
  ]));
  const decisionsRecord = expectExactRecord(record.actionDecisions, `${path}.actionDecisions`, [
    "parameter-write", "rollback-apply", "takeover", "emergency-stop", "arm", "flight",
  ]);
  const actionDecisions = Object.fromEntries(Object.entries(decisionsRecord).map(([key, raw]) => [
    key,
    expectLiteral(raw, "deny", `${path}.actionDecisions.${key}`),
  ])) as Record<string, "deny">;
  const plan: FieldPreflightPlan = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, `${path}.schemaVersion`),
    kind: expectLiteral(record.kind, "dronedream-field-preflight-plan", `${path}.kind`),
    editionId: expectHardwareDomainEdition(record.editionId, `${path}.editionId`),
    executionDomain: expectLiteral(
      record.executionDomain,
      "real-hardware",
      `${path}.executionDomain`,
    ),
    sourceCommit: expectLowercaseHex(record.sourceCommit, `${path}.sourceCommit`, 40),
    requestSha256: expectLowercaseHex(record.requestSha256, `${path}.requestSha256`, 64),
    planSha256: expectLowercaseHex(record.planSha256, `${path}.planSha256`, 64),
    validatedPackCount: expectBoundedNonNegativeInteger(
      record.validatedPackCount,
      `${path}.validatedPackCount`,
      8,
    ),
    zone: {
      name: parseFieldRecoveryIdentity(zone.name, `${path}.zone.name`),
      radiusM: expectBoundedNonNegativeInteger(zone.radiusM, `${path}.zone.radiusM`, 10_000),
      maxAltitudeM: expectBoundedNonNegativeInteger(
        zone.maxAltitudeM,
        `${path}.zone.maxAltitudeM`,
        1_000,
      ),
      evidenceState: expectLiteral(
        zone.evidenceState,
        "operator-declared-only",
        `${path}.zone.evidenceState`,
      ),
    },
    quorum,
    actionDecisions,
    requiredEvidence: parseSafeNonEmptyStringArray(
      record.requiredEvidence,
      `${path}.requiredEvidence`,
    ),
    blockers: parseSafeNonEmptyStringArray(record.blockers, `${path}.blockers`),
    canExecute: expectLiteral(record.canExecute, false, `${path}.canExecute`),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      `${path}.hardwareAuthority`,
    ),
    deviceOpenAttempts: expectLiteral(
      record.deviceOpenAttempts,
      0,
      `${path}.deviceOpenAttempts`,
    ),
    hardwareWriteAttempts: expectLiteral(
      record.hardwareWriteAttempts,
      0,
      `${path}.hardwareWriteAttempts`,
    ),
  };
  if (
    plan.validatedPackCount !== 0
    || plan.zone.radiusM === 0
    || plan.zone.maxAltitudeM === 0
    || !plan.blockers.includes("field.registry.zero-validated-packs")
    || plan.requiredEvidence.length < 7
    || Object.values(plan.actionDecisions).some((decision) => decision !== "deny")
  ) {
    throw new Error("Field preflight plan weakened its native safety boundary");
  }
  return plan;
}

function parseFieldHardwareTuningPlan(value: unknown): FieldHardwareTuningPlan {
  const record = expectExactRecord(value, "fieldHardwarePlan", [
    "schemaVersion", "kind", "jobId", "editionId", "executionDomain", "sourceCommit",
    "requestSha256", "snapshotSha256", "observationSha256", "budget", "phases",
    "canExecute", "hardwareAuthority", "hardwareWriteAttempts", "requiredEvidence",
    "blockers", "planSha256",
  ]);
  const budget = expectExactRecord(record.budget, "fieldHardwarePlan.budget", [
    "maxIterations", "hardwareTrialBudget", "parameterWriteBudget", "providerRequests",
  ]);
  const plan: FieldHardwareTuningPlan = {
    schemaVersion: expectLiteral(record.schemaVersion, 1, "fieldHardwarePlan.schemaVersion"),
    kind: expectLiteral(
      record.kind,
      "dronedream-field-hardware-tuning-plan",
      "fieldHardwarePlan.kind",
    ),
    jobId: expectSafeNonEmptyString(record.jobId, "fieldHardwarePlan.jobId"),
    editionId: expectHardwareDomainEdition(record.editionId, "fieldHardwarePlan.editionId"),
    executionDomain: expectLiteral(
      record.executionDomain,
      "real-hardware",
      "fieldHardwarePlan.executionDomain",
    ),
    sourceCommit: expectLowercaseHex(record.sourceCommit, "fieldHardwarePlan.sourceCommit", 40),
    requestSha256: expectLowercaseHex(record.requestSha256, "fieldHardwarePlan.requestSha256", 64),
    snapshotSha256: record.snapshotSha256 === null
      ? null
      : expectLowercaseHex(record.snapshotSha256, "fieldHardwarePlan.snapshotSha256", 64),
    observationSha256: record.observationSha256 === null
      ? null
      : expectLowercaseHex(record.observationSha256, "fieldHardwarePlan.observationSha256", 64),
    budget: {
      maxIterations: expectBoundedNonNegativeInteger(
        budget.maxIterations,
        "fieldHardwarePlan.budget.maxIterations",
        32,
      ),
      hardwareTrialBudget: expectLiteral(
        budget.hardwareTrialBudget,
        0,
        "fieldHardwarePlan.budget.hardwareTrialBudget",
      ),
      parameterWriteBudget: expectLiteral(
        budget.parameterWriteBudget,
        0,
        "fieldHardwarePlan.budget.parameterWriteBudget",
      ),
      providerRequests: expectLiteral(
        budget.providerRequests,
        0,
        "fieldHardwarePlan.budget.providerRequests",
      ),
    },
    phases: parseSafeNonEmptyStringArray(record.phases, "fieldHardwarePlan.phases"),
    canExecute: expectLiteral(record.canExecute, false, "fieldHardwarePlan.canExecute"),
    hardwareAuthority: expectLiteral(
      record.hardwareAuthority,
      false,
      "fieldHardwarePlan.hardwareAuthority",
    ),
    hardwareWriteAttempts: expectLiteral(
      record.hardwareWriteAttempts,
      0,
      "fieldHardwarePlan.hardwareWriteAttempts",
    ),
    requiredEvidence: parseSafeNonEmptyStringArray(
      record.requiredEvidence,
      "fieldHardwarePlan.requiredEvidence",
    ),
    blockers: parseSafeNonEmptyStringArray(record.blockers, "fieldHardwarePlan.blockers"),
    planSha256: expectLowercaseHex(record.planSha256, "fieldHardwarePlan.planSha256", 64),
  };
  if (
    plan.blockers.length === 0
    || plan.requiredEvidence.length < 10
    || plan.phases.length < 8
    || plan.budget.maxIterations === 0
  ) {
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

function expectHardwareDomainEdition(
  value: unknown,
  path: string,
): HardwareDomainEdition {
  if (value !== "lab" && value !== "field" && value !== "autonomy") {
    throw new Error(`${path} must equal lab, field, or autonomy`);
  }
  return value;
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

function expectBoundedNonNegativeInteger(
  value: unknown,
  path: string,
  maximum: number,
): number {
  const result = expectNonNegativeInteger(value, path);
  if (result > maximum) throw new Error(`${path} is out of range`);
  return result;
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
