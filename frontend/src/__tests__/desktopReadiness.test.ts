import { describe, expect, it } from "vitest";

import type {
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "../desktop/bridge";
import {
  isOverallDesktopReady,
  isRuntimeConfirmedMissing,
  isRuntimeFullyReady,
} from "../desktop/readiness";

const componentIds = [
  "wsl-runtime",
  "host-ownership",
  "runtime-manifest",
  "local-backend",
  "px4",
  "gazebo",
] as const;

const prerequisites: SystemPrerequisiteReport = {
  platform: "windows",
  supported: true,
  windows: {
    caption: "Windows 11 Pro",
    version: "10.0.26100",
    buildNumber: "26100",
    architecture: "64-bit",
  },
  wsl: { executableAvailable: true, distributions: [] },
  memory: { totalBytes: 16 * 1024 ** 3, availableBytes: 8 * 1024 ** 3 },
  disks: [],
  gpus: [],
  probeErrors: [],
};

const readyRuntime: RuntimeStatusReport = {
  runtimeName: "DroneDreamRuntime",
  installed: true,
  running: true,
  ready: true,
  version: "2026.07",
  dataRoot: "E:\\DroneDream",
  components: componentIds.map((id) => ({
    id,
    label: id,
    status: "ready",
    required: true,
    version: null,
    detail: null,
  })),
  diagnostics: [],
};

const missingRuntime: RuntimeStatusReport = {
  ...readyRuntime,
  installed: false,
  running: false,
  ready: false,
  version: null,
  dataRoot: null,
  components: readyRuntime.components.map((component) => ({
    ...component,
    status: "missing",
  })),
};

describe("desktop readiness", () => {
  it("requires supported Windows, known memory, WSL, and a fully ready runtime", () => {
    expect(isOverallDesktopReady(prerequisites, readyRuntime)).toBe(true);
    expect(isOverallDesktopReady({ ...prerequisites, supported: false }, readyRuntime))
      .toBe(false);
    expect(isOverallDesktopReady({ ...prerequisites, memory: null }, readyRuntime))
      .toBe(false);
    expect(isOverallDesktopReady({
      ...prerequisites,
      memory: { totalBytes: 14 * 1024 ** 3, availableBytes: 8 * 1024 ** 3 },
    }, readyRuntime)).toBe(false);
    expect(isOverallDesktopReady({
      ...prerequisites,
      wsl: { executableAvailable: false, distributions: [] },
    }, readyRuntime)).toBe(false);
    expect(isOverallDesktopReady(prerequisites, missingRuntime)).toBe(false);
  });

  it("does not block an installed runtime for GPU or disk-only probe failures", () => {
    expect(isOverallDesktopReady({
      ...prerequisites,
      disks: [],
      gpus: [],
      probeErrors: ["Disk probe failed", "GPU probe failed"],
    }, readyRuntime)).toBe(true);
  });

  it("requires every required component to be ready", () => {
    expect(isRuntimeFullyReady(readyRuntime)).toBe(true);
    expect(isRuntimeFullyReady({
      ...readyRuntime,
      components: readyRuntime.components.map((component) =>
        component.id === "px4" ? { ...component, status: "unknown" } : component,
      ),
    })).toBe(false);
  });

  it("distinguishes confirmed missing from an uncertain failed probe", () => {
    expect(isRuntimeConfirmedMissing(missingRuntime)).toBe(true);
    expect(isRuntimeConfirmedMissing({
      ...missingRuntime,
      components: missingRuntime.components.map((component) =>
        component.id === "wsl-runtime"
          ? { ...component, status: "unknown" }
          : component,
      ),
      diagnostics: ["Unable to inspect the WSL registry."],
    })).toBe(false);
  });
});
