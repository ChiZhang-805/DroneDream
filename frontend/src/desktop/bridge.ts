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

interface TauriCore {
  invoke(command: string, args?: Record<string, unknown>): Promise<unknown>;
}

interface TauriGlobal {
  core?: TauriCore;
}

type UnknownRecord = Record<string, unknown>;

const RUNTIME_NAME = "DroneDreamRuntime";
const REQUIRED_RUNTIME_COMPONENT_IDS = [
  "wsl-runtime",
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
  if (
    requiredIds.length !== REQUIRED_RUNTIME_COMPONENT_IDS.length ||
    REQUIRED_RUNTIME_COMPONENT_IDS.some((id) => !requiredIdSet.has(id))
  ) {
    throw new Error(
      `report.components must mark exactly ${REQUIRED_RUNTIME_COMPONENT_IDS.join(", ")} as required`,
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

function expectNullableString(value: unknown, path: string): string | null {
  if (value == null) return null;
  return expectString(value, path);
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
