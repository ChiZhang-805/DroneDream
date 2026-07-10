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

async function invokeDesktop<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  const core = getTauriCore();
  if (!core) throw new DesktopRuntimeUnavailableError();
  return core.invoke(command, args) as Promise<T>;
}

export function isDesktopRuntime(): boolean {
  return getTauriCore() !== null;
}

export function probeSystemPrerequisites(): Promise<SystemPrerequisiteReport> {
  return invokeDesktop("probe_system_prerequisites");
}

export function probeRuntimeStatus(): Promise<RuntimeStatusReport> {
  return invokeDesktop("probe_runtime_status");
}

export function getRuntimeInstallPlan(
  targetRoot?: string,
): Promise<RuntimeInstallPlan> {
  return invokeDesktop(
    "get_runtime_install_plan",
    targetRoot ? { targetRoot } : undefined,
  );
}
