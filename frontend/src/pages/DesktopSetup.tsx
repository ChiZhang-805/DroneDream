import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Alert } from "../components/Alert";
import { Loading } from "../components/States";
import { SectionCard } from "../components/SectionCard";
import {
  autoStartInstallerRuntime,
  cancelRuntimeInstall,
  discardInstallerRuntimeIntent,
  getInstallerRuntimeIntent,
  getRuntimeInstallProgress,
  getRuntimeInstallPlan,
  isDesktopRuntime,
  probeRuntimeStatus,
  probeSystemPrerequisites,
  repairRuntime,
  startRuntime,
  startRuntimeInstall,
} from "../desktop/bridge";
import type {
  DiskInfo,
  InstallerRuntimeAutoStartResult,
  InstallerRuntimeDiscardResult,
  InstallerRuntimeIntent,
  RuntimeComponentState,
  RuntimeInstallPhase,
  RuntimeInstallPlan,
  RuntimeInstallSnapshot,
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "../desktop/bridge";
import { formatBytes } from "../desktop/format";
import { useDesktopRuntimeAccess } from "../desktop/access";
import {
  isOverallDesktopReady,
  isRuntimeConfirmedMissing,
  isRuntimeFullyReady,
  MINIMUM_MEMORY_BYTES,
} from "../desktop/readiness";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";

const DroneLaunchScene = lazy(async () => {
  const module = await import("../components/DroneLaunchScene");
  return { default: module.DroneLaunchScene };
});

interface ProbeState {
  prerequisites: SystemPrerequisiteReport | null;
  runtime: RuntimeStatusReport | null;
  plan: RuntimeInstallPlan | null;
  issues: ProbeIssue[];
  loading: boolean;
  planLoading: boolean;
  prerequisitesFresh: boolean;
  runtimeFresh: boolean;
}

type ProbeIssueSource = "prerequisites" | "runtime" | "plan";

interface ProbeIssue {
  source: ProbeIssueSource;
  command: string;
  message: string;
}

interface InstallState {
  snapshot: RuntimeInstallSnapshot | null;
  commandError: string | null;
  commandBusy: boolean;
}

interface InstallerHandoffState {
  intent: InstallerRuntimeIntent | null;
  result: InstallerRuntimeAutoStartResult | null;
  commandError: string | null;
  checking: boolean;
  autoStarting: boolean;
  previewSettled: boolean;
  autoStartUncertain: boolean;
  discarding: boolean;
  discardResult: InstallerRuntimeDiscardResult | null;
}

const INITIAL_STATE: ProbeState = {
  prerequisites: null,
  runtime: null,
  plan: null,
  issues: [],
  loading: false,
  planLoading: false,
  prerequisitesFresh: false,
  runtimeFresh: false,
};

const INITIAL_INSTALL_STATE: InstallState = {
  snapshot: null,
  commandError: null,
  commandBusy: false,
};

const INITIAL_INSTALLER_HANDOFF_STATE: InstallerHandoffState = {
  intent: null,
  result: null,
  commandError: null,
  checking: false,
  autoStarting: false,
  previewSettled: false,
  autoStartUncertain: false,
  discarding: false,
  discardResult: null,
};

const ACTIVE_INSTALL_PHASES = new Set<RuntimeInstallPhase>([
  "queued",
  "verifyingManifest",
  "downloading",
  "verifyingArchive",
  "importing",
  "starting",
  "healthChecking",
]);

const GIB = 1024 ** 3;
const INSTALLER_AUTO_START_TIMEOUT_MS = 15_000;

function configuredRuntimeReleaseManifestUrl(): string | null {
  const configured = import.meta.env.VITE_RUNTIME_RELEASE_MANIFEST_URL?.trim();
  if (!configured) return null;
  try {
    const url = new URL(configured);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function fixedDiskOptions(disks: DiskInfo[]): DiskInfo[] {
  // The prerequisite command returns only DriveType=3 disks. Keep the UI
  // constrained to well-formed local drive roots from that trusted report.
  const unique = new Map<string, DiskInfo>();
  for (const disk of disks) {
    const drive = disk.drive.trim().toUpperCase();
    if (!/^[A-Z]:$/.test(drive) || unique.has(drive)) continue;
    unique.set(drive, { ...disk, drive });
  }
  return [...unique.values()].sort((left, right) => {
    if (left.isSystemDrive !== right.isSystemDrive) {
      return left.isSystemDrive ? 1 : -1;
    }
    return right.freeBytes - left.freeBytes || left.drive.localeCompare(right.drive);
  });
}

function chooseRuntimeDrive(disks: DiskInfo[], currentDrive: string): string {
  const normalizedCurrent = currentDrive.trim().toUpperCase();
  return disks.some((disk) => disk.drive === normalizedCurrent)
    ? normalizedCurrent
    : "";
}

function runtimeTargetRoot(drive: string): string | undefined {
  const normalized = drive.trim().toUpperCase();
  return /^[A-Z]:$/.test(normalized) ? `${normalized}\\DroneDream` : undefined;
}

async function getSettledInstallPlan(
  drive: string,
  exactTargetRoot?: string,
) {
  try {
    return {
      status: "fulfilled" as const,
      value: await getRuntimeInstallPlan(
        exactTargetRoot ?? runtimeTargetRoot(drive),
      ),
    };
  } catch (reason) {
    return { status: "rejected" as const, reason };
  }
}

async function getSettledInstallProgress() {
  try {
    return {
      status: "fulfilled" as const,
      value: await getRuntimeInstallProgress(),
    };
  } catch (reason) {
    return { status: "rejected" as const, reason };
  }
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function isActiveInstall(snapshot: RuntimeInstallSnapshot | null): boolean {
  return snapshot !== null && ACTIVE_INSTALL_PHASES.has(snapshot.phase);
}

function replaceIssues(
  current: ProbeIssue[],
  sources: ProbeIssueSource[],
  replacements: ProbeIssue[],
): ProbeIssue[] {
  const replacedSources = new Set(sources);
  return [
    ...current.filter((issue) => !replacedSources.has(issue.source)),
    ...replacements,
  ];
}

function probeIssue(
  source: ProbeIssueSource,
  command: string,
  reason: unknown,
): ProbeIssue {
  return { source, command, message: errorMessage(reason) };
}

export function DesktopSetup() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const { refresh: refreshRuntimeAccess } = useDesktopRuntimeAccess();
  const desktopAvailable = isDesktopRuntime();
  const requestId = useRef(0);
  const installerIntentPromise = useRef<Promise<InstallerRuntimeIntent> | null>(null);
  const installerAutoStartPromise = useRef<
    Promise<InstallerRuntimeAutoStartResult> | null
  >(null);
  const installerDiscardRequested = useRef(false);
  const installerDiscardSucceeded = useRef(false);
  const componentMounted = useRef(false);
  const selectedDriveRef = useRef("");
  const [state, setState] = useState<ProbeState>(() => ({
    ...INITIAL_STATE,
    loading: desktopAvailable,
  }));
  const [installState, setInstallState] = useState<InstallState>(
    INITIAL_INSTALL_STATE,
  );
  const [installerHandoffState, setInstallerHandoffState] =
    useState<InstallerHandoffState>(() => ({
      ...INITIAL_INSTALLER_HANDOFF_STATE,
      checking: desktopAvailable,
    }));
  const [receiptCleanupRecovered, setReceiptCleanupRecovered] = useState(false);
  const [runtimeCommandError, setRuntimeCommandError] = useState<string | null>(null);
  const [runtimeCommandBusy, setRuntimeCommandBusy] = useState(false);
  const [selectedDrive, setSelectedDrive] = useState("");
  const [installerAttempt, setInstallerAttempt] = useState(0);
  const releaseManifestUrl = configuredRuntimeReleaseManifestUrl();
  const installActive = isActiveInstall(installState.snapshot);
  const receiptCleanupPending =
    installState.snapshot?.phase === "failed" &&
    installState.snapshot.error?.code === "installer_receipt_cleanup_failed";
  const busy =
    state.loading ||
    state.planLoading ||
    installerHandoffState.checking ||
    installerHandoffState.autoStarting ||
    installerHandoffState.discarding ||
    installState.commandBusy ||
    runtimeCommandBusy ||
    installActive;
  const showInstallPlanner =
    state.prerequisitesFresh &&
    state.runtimeFresh &&
    isRuntimeConfirmedMissing(state.runtime);
  const localRuntimeReady =
    state.prerequisitesFresh &&
    state.runtimeFresh &&
    isOverallDesktopReady(state.prerequisites, state.runtime);
  const requestedFeature = searchParams.get("required");
  const requestedFeatureLabel = requestedFeature === "experiment"
    ? t("runtimeGate.featureExperiment")
    : requestedFeature === "job"
      ? t("runtimeGate.featureJob")
      : requestedFeature === "batch"
        ? t("runtimeGate.featureBatch")
        : null;

  useEffect(() => {
    componentMounted.current = true;
    return () => {
      componentMounted.current = false;
    };
  }, []);

  const refresh = useCallback(async (installerTargetRoot?: string) => {
    if (!desktopAvailable) return;
    const currentRequest = ++requestId.current;
    setState((current) => ({
      ...current,
      loading: true,
      planLoading: false,
      plan: null,
      prerequisitesFresh: false,
      runtimeFresh: false,
    }));

    const [prerequisites, runtime] = await Promise.allSettled([
      probeSystemPrerequisites(),
      probeRuntimeStatus(),
    ]);
    if (requestId.current !== currentRequest) return;

    // Keep the navigation/action gate in sync after every explicit setup-page
    // check, including transitions from ready to stopped or uncertain. The
    // access provider performs its own fail-closed probe, so stale local
    // reports are never promoted into global readiness.
    void refreshRuntimeAccess();

    const probeIssues: ProbeIssue[] = [];
    if (prerequisites.status === "rejected") {
      probeIssues.push(probeIssue(
        "prerequisites",
        "probe_system_prerequisites",
        prerequisites.reason,
      ));
    }
    if (runtime.status === "rejected") {
      probeIssues.push(probeIssue("runtime", "probe_runtime_status", runtime.reason));
    }

    const fixedDisks = prerequisites.status === "fulfilled"
      ? fixedDiskOptions(prerequisites.value.disks)
      : [];
    let nextDrive = prerequisites.status === "fulfilled"
      ? chooseRuntimeDrive(fixedDisks, selectedDriveRef.current)
      : selectedDriveRef.current;
    const installerDrive = installerTargetRoot?.slice(0, 2).toUpperCase();
    if (
      prerequisites.status === "fulfilled" &&
      installerDrive &&
      fixedDisks.some((disk) => disk.drive === installerDrive)
    ) {
      nextDrive = installerDrive;
    }
    if (prerequisites.status === "fulfilled") {
      selectedDriveRef.current = nextDrive;
      setSelectedDrive(nextDrive);
    }
    const shouldRequestPlan =
      prerequisites.status === "fulfilled" &&
      runtime.status === "fulfilled" &&
      isRuntimeConfirmedMissing(runtime.value) &&
      (fixedDisks.length > 0 || installerTargetRoot !== undefined);

    setState((current) => ({
      ...current,
      prerequisites: prerequisites.status === "fulfilled"
        ? prerequisites.value
        : current.prerequisites,
      runtime: runtime.status === "fulfilled" ? runtime.value : current.runtime,
      plan: null,
      issues: replaceIssues(
        current.issues,
        ["prerequisites", "runtime", "plan"],
        probeIssues,
      ),
      loading: false,
      planLoading: shouldRequestPlan,
      prerequisitesFresh: prerequisites.status === "fulfilled",
      runtimeFresh: runtime.status === "fulfilled",
    }));

    if (!shouldRequestPlan) return;

    const progress = await getSettledInstallProgress();
    if (requestId.current !== currentRequest) return;

    if (progress.status === "fulfilled") {
      setInstallState({
        snapshot: progress.value,
        commandError: null,
        commandBusy: false,
      });
      const progressDrive = progress.value.targetRoot?.slice(0, 2).toUpperCase();
      if (progressDrive && fixedDisks.some((disk) => disk.drive === progressDrive)) {
        nextDrive = progressDrive;
        selectedDriveRef.current = progressDrive;
        setSelectedDrive(progressDrive);
      }
    } else {
      setInstallState((current) => ({
        ...current,
        commandError: `get_runtime_install_progress: ${errorMessage(progress.reason)}`,
        commandBusy: false,
      }));
    }

    const progressTargetRoot = progress.status === "fulfilled"
      ? progress.value.targetRoot ?? undefined
      : undefined;
    const exactTargetRoot = installerTargetRoot ?? progressTargetRoot;
    const plan = await getSettledInstallPlan(nextDrive, exactTargetRoot);
    if (requestId.current !== currentRequest) return;

    if (plan.status === "fulfilled") {
      const plannedDrive = plan.value.targetRoot.slice(0, 2).toUpperCase();
      const recommendedDrive = chooseRuntimeDrive(fixedDisks, plannedDrive);
      selectedDriveRef.current = recommendedDrive;
      setSelectedDrive(recommendedDrive);
    }

    const planIssues = plan.status === "rejected"
      ? [probeIssue("plan", "get_runtime_install_plan", plan.reason)]
      : [];
    setState((current) => ({
      ...current,
      plan: plan.status === "fulfilled" ? plan.value : null,
      issues: replaceIssues(current.issues, ["plan"], planIssues),
      planLoading: false,
    }));
  }, [desktopAvailable, refreshRuntimeAccess]);

  const selectRuntimeDrive = useCallback(async (drive: string) => {
    if (
      !desktopAvailable ||
      !state.prerequisitesFresh ||
      !state.runtimeFresh ||
      state.runtime?.installed !== false ||
      isActiveInstall(installState.snapshot)
    ) return;
    const fixedDisks = fixedDiskOptions(state.prerequisites?.disks ?? []);
    if (!fixedDisks.some((disk) => disk.drive === drive)) return;

    const currentRequest = ++requestId.current;
    selectedDriveRef.current = drive;
    setSelectedDrive(drive);
    const selectedTargetRoot = runtimeTargetRoot(drive);
    if (
      installState.snapshot?.targetRoot &&
      installState.snapshot.targetRoot !== selectedTargetRoot
    ) {
      setInstallState(INITIAL_INSTALL_STATE);
    }
    setState((current) => ({
      ...current,
      plan: null,
      planLoading: true,
      issues: replaceIssues(current.issues, ["plan"], []),
    }));

    const plan = await getSettledInstallPlan(drive);
    if (requestId.current !== currentRequest) return;

    setState((current) => ({
      ...current,
      plan: plan.status === "fulfilled" ? plan.value : null,
      planLoading: false,
      issues: replaceIssues(
        current.issues,
        ["plan"],
        plan.status === "rejected"
          ? [probeIssue("plan", "get_runtime_install_plan", plan.reason)]
          : [],
      ),
    }));
  }, [
    desktopAvailable,
    installState.snapshot,
    state.prerequisites,
    state.prerequisitesFresh,
    state.runtime,
    state.runtimeFresh,
  ]);

  const beginOrResumeInstall = useCallback(async () => {
    const targetRoot = state.plan?.targetRoot;
    if (
      !desktopAvailable ||
      installState.commandBusy ||
      isActiveInstall(installState.snapshot) ||
      !state.plan?.canInstall ||
      state.plan.blockers.length > 0 ||
      !targetRoot ||
      !releaseManifestUrl
    ) return;

    setInstallState((current) => ({
      ...current,
      commandError: null,
      commandBusy: true,
    }));
    try {
      const snapshot = await startRuntimeInstall({
        targetRoot,
        releaseManifestUrl,
      });
      setInstallState({ snapshot, commandError: null, commandBusy: false });
    } catch (error) {
      setInstallState((current) => ({
        ...current,
        commandError: `start_runtime_install: ${errorMessage(error)}`,
        commandBusy: false,
      }));
    }
  }, [
    desktopAvailable,
    installState.commandBusy,
    installState.snapshot,
    releaseManifestUrl,
    state.plan,
  ]);

  const cancelInstall = useCallback(async () => {
    if (
      !desktopAvailable ||
      installState.commandBusy ||
      !isActiveInstall(installState.snapshot)
    ) return;
    setInstallState((current) => ({
      ...current,
      commandError: null,
      commandBusy: true,
    }));
    try {
      const snapshot = await cancelRuntimeInstall();
      setInstallState({ snapshot, commandError: null, commandBusy: false });
    } catch (error) {
      setInstallState((current) => ({
        ...current,
        commandError: `cancel_runtime_install: ${errorMessage(error)}`,
        commandBusy: false,
      }));
    }
  }, [desktopAvailable, installState.commandBusy, installState.snapshot]);

  const runRuntimeAction = useCallback(async (action: "start" | "repair") => {
    if (!desktopAvailable || runtimeCommandBusy) return;
    setRuntimeCommandError(null);
    setRuntimeCommandBusy(true);
    try {
      const runtime = action === "start" ? await startRuntime() : await repairRuntime();
      setState((current) => ({
        ...current,
        runtime,
        runtimeFresh: true,
        issues: replaceIssues(current.issues, ["runtime"], []),
      }));
    } catch (error) {
      setRuntimeCommandError(
        `${action === "start" ? "start_runtime" : "repair_runtime"}: ${errorMessage(error)}`,
      );
    } finally {
      setRuntimeCommandBusy(false);
    }
  }, [desktopAvailable, runtimeCommandBusy]);

  const pollingOperationId = installState.snapshot?.operationId;
  const pollingPhase = installState.snapshot?.phase;
  useEffect(() => {
    if (
      !desktopAvailable ||
      !pollingPhase ||
      !ACTIVE_INSTALL_PHASES.has(pollingPhase)
    ) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const snapshot = await getRuntimeInstallProgress();
        if (disposed) return;
        setInstallState((current) => ({
          ...current,
          snapshot,
          commandError: null,
        }));
        if (isActiveInstall(snapshot)) timer = setTimeout(poll, 750);
      } catch (error) {
        if (disposed) return;
        setInstallState((current) => ({
          ...current,
          commandError: `get_runtime_install_progress: ${errorMessage(error)}`,
        }));
        timer = setTimeout(poll, 1500);
      }
    };

    timer = setTimeout(poll, 350);
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
    };
  }, [
    desktopAvailable,
    pollingOperationId,
    pollingPhase,
  ]);

  const completedOperation = useRef<string | null>(null);
  useEffect(() => {
    const snapshot = installState.snapshot;
    if (
      snapshot?.phase !== "completed" ||
      !snapshot.operationId ||
      completedOperation.current === snapshot.operationId
    ) return;
    completedOperation.current = snapshot.operationId;
    void refresh();
  }, [installState.snapshot, refresh]);

  useEffect(() => {
    if (!desktopAvailable) return;
    let disposed = false;
    // Peeking is strictly read-only. It lets the page render the exact confirmed
    // disk, download size, plan, and controls before the atomic start command is
    // allowed to claim the handoff or begin network activity.
    const intentPromise = installerIntentPromise.current ??=
      getInstallerRuntimeIntent();

    void (async () => {
      let installerTargetRoot: string | undefined;
      try {
        const intent = await intentPromise;
        if (disposed) return;
        installerTargetRoot = intent.status === "ready"
          ? intent.targetRoot ?? undefined
          : undefined;
        setInstallerHandoffState({
          intent,
          result: null,
          commandError: null,
          checking: false,
          autoStarting: false,
          previewSettled: false,
          autoStartUncertain: false,
          discarding: false,
          discardResult: null,
        });
      } catch (error) {
        if (disposed) return;
        setInstallerHandoffState({
          intent: null,
          result: null,
          commandError: `get_installer_runtime_intent: ${errorMessage(error)}`,
          checking: false,
          autoStarting: false,
          previewSettled: false,
          autoStartUncertain: false,
          discarding: false,
          discardResult: null,
        });
      }
      if (!disposed) {
        await refresh(installerTargetRoot);
        if (!disposed) {
          setInstallerHandoffState((current) => ({
            ...current,
            previewSettled: true,
          }));
        }
      }
    })();

    return () => {
      disposed = true;
      requestId.current += 1;
    };
  }, [desktopAvailable, installerAttempt, refresh]);

  const installerIntent = installerHandoffState.intent;
  const installerIntentReady = installerIntent?.status === "ready";
  const exactInstallerPlanReady = Boolean(
    installerIntentReady &&
    installerHandoffState.previewSettled &&
    showInstallPlanner &&
    state.plan &&
    state.plan.targetRoot === installerIntent?.targetRoot,
  );
  const installerIntentShouldBeConsumed = Boolean(
    installerIntent &&
    installerHandoffState.previewSettled &&
    (installerIntent.status === "desktopOnly" ||
      installerIntent.status === "invalid" ||
      (installerIntent.status === "ready" && exactInstallerPlanReady)),
  );

  const reconcileLateInstallerCompletion = useCallback(async (
    reportedSnapshot: RuntimeInstallSnapshot | null,
  ) => {
    const progress = await getSettledInstallProgress();
    const recoveredSnapshot = progress.status === "fulfilled" &&
        isActiveInstall(progress.value)
      ? progress.value
      : isActiveInstall(reportedSnapshot)
        ? reportedSnapshot
        : null;
    if (!componentMounted.current || !recoveredSnapshot) return;

    setInstallState({
      snapshot: recoveredSnapshot,
      commandError: null,
      commandBusy: false,
    });
    setInstallerHandoffState((current) => ({
      ...current,
      result: null,
      commandError: null,
      autoStarting: false,
      autoStartUncertain: false,
      discarding: false,
      discardResult: {
        discarded: false,
        message: t("desktop.autoInstallRecoveredAfterDiscard"),
      },
    }));
  }, [t]);

  useEffect(() => {
    if (
      !desktopAvailable ||
      !installerIntentShouldBeConsumed ||
      installerHandoffState.result ||
      installerHandoffState.commandError ||
      installerHandoffState.discarding ||
      installerHandoffState.discardResult ||
      installerDiscardRequested.current ||
      installerAutoStartPromise.current
    ) return;

    let disposed = false;
    let frame = requestAnimationFrame(() => {
      if (disposed || installerDiscardRequested.current) return;
      setInstallerHandoffState((current) => ({
        ...current,
        autoStarting: true,
      }));
      // This is the trust boundary. Rust revalidates and atomically claims the
      // handoff, so the target is never sent back through the ordinary start
      // command and a stale or changed disk fails closed.
      const autoStartPromise = installerAutoStartPromise.current ??=
        autoStartInstallerRuntime();
      void (async () => {
        try {
          const result = await withTimeout(
            autoStartPromise,
            INSTALLER_AUTO_START_TIMEOUT_MS,
            "the atomic installer handoff timed out",
          );
          if (installerDiscardSucceeded.current) {
            await reconcileLateInstallerCompletion(result.snapshot);
            return;
          }
          if (
            !componentMounted.current ||
            installerAutoStartPromise.current !== autoStartPromise
          ) return;
          if (installerIntent?.status === "ready") {
            if (
              (result.disposition === "started" || result.disposition === "resumed") &&
              result.targetRoot !== installerIntent.targetRoot
            ) {
              throw new Error(
                "the atomically claimed target does not match the confirmed installer target",
              );
            }
            if (
              (result.disposition === "started" ||
                result.disposition === "resumed" ||
                result.disposition === "alreadyInstalled") &&
              result.mode !== installerIntent.mode
            ) {
              throw new Error(
                "the atomically claimed mode does not match the confirmed installer mode",
              );
            }
            if (result.disposition === "none" || result.disposition === "desktopOnly") {
              throw new Error(
                result.message ??
                  "the confirmed installer choice changed before automatic setup could claim it",
              );
            }
          } else if (installerIntent?.status === "desktopOnly") {
            if (
              result.disposition !== "invalid" &&
              (result.disposition !== "desktopOnly" ||
                result.mode !== "install-app-only")
            ) {
              throw new Error(
                result.message ?? "the desktop-only installer choice could not be consumed",
              );
            }
          } else if (
            installerIntent?.status === "invalid" &&
            result.disposition !== "invalid"
          ) {
            throw new Error(
              result.message ?? "the invalid installer receipt could not be cleared",
            );
          }
          setInstallerHandoffState((current) => ({
            ...current,
            result,
            commandError: null,
            autoStarting: false,
            autoStartUncertain: false,
            discarding: false,
            discardResult: null,
          }));
          if (result.snapshot) {
            setInstallState({
              snapshot: result.snapshot,
              commandError: null,
              commandBusy: false,
            });
          }
          if (result.disposition === "alreadyInstalled") void refresh();
        } catch (error) {
          if (installerDiscardSucceeded.current) {
            await reconcileLateInstallerCompletion(null);
            return;
          }
          if (
            !componentMounted.current ||
            installerAutoStartPromise.current !== autoStartPromise
          ) return;
          const progress = await getSettledInstallProgress();
          if (
            !componentMounted.current ||
            installerAutoStartPromise.current !== autoStartPromise
          ) return;
          const recoveredSnapshot = progress.status === "fulfilled" &&
            progress.value.phase !== "idle"
            ? progress.value
            : null;
          if (recoveredSnapshot) {
            setInstallState({
              snapshot: recoveredSnapshot,
              commandError: null,
              commandBusy: false,
            });
          }
          const progressDetail = progress.status === "rejected"
            ? `; get_runtime_install_progress: ${errorMessage(progress.reason)}`
            : "";
          setInstallerHandoffState((current) => ({
            ...current,
            result: null,
            commandError:
              `auto_start_installer_runtime: ${errorMessage(error)}${progressDetail}`,
            autoStarting: false,
            autoStartUncertain: recoveredSnapshot === null,
            discarding: false,
          }));
        }
      })();
    });

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      frame = 0;
    };
  }, [
    desktopAvailable,
    installerHandoffState.commandError,
    installerHandoffState.discarding,
    installerHandoffState.discardResult,
    installerHandoffState.result,
    installerIntentShouldBeConsumed,
    installerIntent?.mode,
    installerIntent?.status,
    installerIntent?.targetRoot,
    reconcileLateInstallerCompletion,
    refresh,
  ]);

  const automaticStartPending = Boolean(
    installerIntentReady &&
    !installerHandoffState.result &&
    (!installerHandoffState.commandError || installerHandoffState.autoStartUncertain) &&
    (!installerHandoffState.discardResult ||
      installerHandoffState.autoStartUncertain),
  );
  const restartContinuationPending = Boolean(
    installerIntentReady &&
    installState.snapshot?.phase === "waitingForRestart",
  );
  const invalidInstallerHandoffRecoverable = Boolean(
    installerHandoffState.result?.disposition === "invalid" ||
    installerIntent?.status === "invalid",
  );
  const installerHandoffDiscardAvailable = Boolean(
    automaticStartPending ||
    restartContinuationPending ||
    invalidInstallerHandoffRecoverable ||
    receiptCleanupPending,
  );
  const installerManagedInstall = Boolean(
    installerIntentReady &&
    (automaticStartPending ||
      installerHandoffState.result?.disposition === "started" ||
      installerHandoffState.result?.disposition === "resumed" ||
      (installState.snapshot?.phase !== undefined &&
        installState.snapshot.phase !== "idle" &&
        installState.snapshot.targetRoot === installerIntent?.targetRoot)),
  );
  const automaticStartScheduled = Boolean(
    automaticStartPending &&
    !installerHandoffState.commandError &&
    !installerHandoffState.discardResult,
  );
  const retryInstallerHandoff = useCallback(() => {
    if (installerHandoffState.autoStarting) return;
    installerIntentPromise.current = null;
    installerAutoStartPromise.current = null;
    installerDiscardRequested.current = false;
    installerDiscardSucceeded.current = false;
    setReceiptCleanupRecovered(false);
    setInstallerHandoffState({
      ...INITIAL_INSTALLER_HANDOFF_STATE,
      checking: true,
    });
    setInstallerAttempt((current) => current + 1);
  }, [installerHandoffState.autoStarting]);
  const discardAutomaticInstall = useCallback(async () => {
    if (!installerHandoffDiscardAvailable || installerHandoffState.discarding) return;
    installerDiscardRequested.current = true;
    installerDiscardSucceeded.current = false;
    setInstallerHandoffState((current) => ({
      ...current,
      discarding: true,
      discardResult: null,
    }));

    try {
      const discardResult = await withTimeout(
        discardInstallerRuntimeIntent(),
        INSTALLER_AUTO_START_TIMEOUT_MS,
        "discarding the pending installer handoff timed out",
      );
      if (discardResult.discarded) {
        installerDiscardSucceeded.current = true;
        installerAutoStartPromise.current = null;
        setInstallerHandoffState((current) => ({
          ...current,
          intent: {
            status: "none",
            mode: null,
            targetRoot: null,
            message: null,
          },
          result: null,
          commandError: null,
          autoStarting: false,
          autoStartUncertain: false,
          discarding: false,
          discardResult,
        }));
        if (receiptCleanupPending) {
          const runtimeWasInstalled = Boolean(
            installState.snapshot?.installedVersion,
          );
          setReceiptCleanupRecovered(true);
          setInstallState(INITIAL_INSTALL_STATE);
          if (runtimeWasInstalled) await refresh();
          return;
        }
        void reconcileLateInstallerCompletion(null);
        return;
      }

      installerDiscardRequested.current = false;
      const progress = await getSettledInstallProgress();
      const recoveredSnapshot = progress.status === "fulfilled" &&
        progress.value.phase !== "idle"
        ? progress.value
        : null;
      if (recoveredSnapshot) {
        setInstallState({
          snapshot: recoveredSnapshot,
          commandError: null,
          commandBusy: false,
        });
      }
      setInstallerHandoffState((current) => ({
        ...current,
        autoStarting: false,
        autoStartUncertain: recoveredSnapshot === null,
        discarding: false,
        discardResult,
      }));
    } catch (error) {
      installerDiscardRequested.current = false;
      const progress = await getSettledInstallProgress();
      const recoveredSnapshot = progress.status === "fulfilled" &&
        progress.value.phase !== "idle"
        ? progress.value
        : null;
      if (recoveredSnapshot) {
        setInstallState({
          snapshot: recoveredSnapshot,
          commandError: null,
          commandBusy: false,
        });
      }
      setInstallerHandoffState((current) => ({
        ...current,
        commandError:
          `discard_installer_runtime_intent: ${errorMessage(error)}`,
        autoStarting: false,
        autoStartUncertain: recoveredSnapshot === null,
        discarding: false,
        discardResult: null,
      }));
    }
  }, [
    installerHandoffDiscardAvailable,
    installerHandoffState.discarding,
    installState.snapshot,
    receiptCleanupPending,
    reconcileLateInstallerCompletion,
    refresh,
  ]);

  if (desktopAvailable) {
    return (
      <section
        className="desktop-launcher"
        aria-busy={busy}
      >
        <RuntimeLauncherHero
          snapshot={installState.snapshot}
          ready={localRuntimeReady}
          checking={state.loading || installerHandoffState.checking}
          automaticStartPending={automaticStartPending}
        />

        {requestedFeatureLabel && !localRuntimeReady ? (
          <Alert tone="warning" title={t("runtimeGate.redirectTitle")}>
            <p className="desktop-alert-copy">{t("runtimeGate.redirectBody")}</p>
            <p className="desktop-alert-copy">
              <strong>{t("runtimeGate.requestedFeature")}:</strong>{" "}
              {requestedFeatureLabel}
            </p>
          </Alert>
        ) : null}

        <InstallerHandoffNotice
          state={installerHandoffState}
          discardAvailable={installerHandoffDiscardAvailable}
          discardBusy={installerHandoffState.discarding}
          receiptCleanupRecovered={receiptCleanupRecovered}
          waitingForRestart={installState.snapshot?.phase === "waitingForRestart"}
          onRetry={retryInstallerHandoff}
          onDiscard={() => void discardAutomaticInstall()}
        />

        {localRuntimeReady ? (
          <div className="launcher-ready-actions">
            <Link to="/dashboard" className="btn btn-primary launcher-primary-action">
              {t("launcher.openWorkspace")}
              <span aria-hidden="true">→</span>
            </Link>
            <span>{t("launcher.readyHint")}</span>
          </div>
        ) : (
          <>
            {state.issues.length > 0 ? (
              <Alert tone="warning" title={t("desktop.probeIssue")}>
                <p className="desktop-alert-copy">{t("desktop.partialFailure")}</p>
                <ul className="desktop-diagnostic-list">
                  {state.issues.map((issue) => (
                    <li key={issue.source}>
                      <code>{issue.command}: {issue.message}</code>
                    </li>
                  ))}
                </ul>
              </Alert>
            ) : null}

            {runtimeCommandError ? (
              <Alert tone="warning" title={t("desktop.runtimeActionFailed")}>
                <code>{runtimeCommandError}</code>
              </Alert>
            ) : null}
            {state.runtimeFresh && state.runtime?.installed ? (
              <InstalledRuntimeNotice
                report={state.runtime}
                busy={runtimeCommandBusy}
                onStart={() => void runRuntimeAction("start")}
                onRepair={() => void runRuntimeAction("repair")}
              />
            ) : null}

            {showInstallPlanner && state.prerequisites && !installActive ? (
              <div className="launcher-storage-card">
                <div>
                  <span className="launcher-card-kicker">{t("launcher.storageKicker")}</span>
                  <strong>{t("desktop.storageTitle")}</strong>
                </div>
                <RuntimeStorageSelector
                  disks={fixedDiskOptions(state.prerequisites.disks)}
                  selectedDrive={selectedDrive}
                  disabled={
                    busy ||
                    automaticStartPending ||
                    installState.snapshot?.phase === "waitingForRestart"
                  }
                  onChange={(drive) => void selectRuntimeDrive(drive)}
                />
              </div>
            ) : null}
            {showInstallPlanner && state.planLoading ? (
              <Loading label={t("desktop.planUpdating")} />
            ) : null}
            {automaticStartPending && !exactInstallerPlanReady ? (
              <InstallerPlanFallback
                targetRoot={installerIntent?.targetRoot ?? ""}
                issues={state.issues}
                checking={
                  !installerHandoffState.previewSettled ||
                  state.loading ||
                  state.planLoading
                }
                discardBusy={installerHandoffState.discarding}
                onRetry={retryInstallerHandoff}
                onDiscard={() => void discardAutomaticInstall()}
              />
            ) : null}
            {(showInstallPlanner && state.plan) ||
            (installState.snapshot && installState.snapshot.phase !== "idle") ? (
              <RuntimeInstallControls
                launcherMode
                plan={state.plan}
                snapshot={installState.snapshot}
                commandError={installState.commandError}
                commandBusy={installState.commandBusy}
                automaticStartPending={automaticStartPending}
                automaticStartUncertain={installerHandoffState.autoStartUncertain}
                automaticDiscardBusy={installerHandoffState.discarding}
                receiptCleanupPending={receiptCleanupPending}
                receiptCleanupInstalled={Boolean(
                  installState.snapshot?.installedVersion,
                )}
                restartContinuationPending={restartContinuationPending}
                releaseManifestUrlAvailable={
                  releaseManifestUrl !== null || installerManagedInstall
                }
                onStart={() => void beginOrResumeInstall()}
                onCancel={() => void cancelInstall()}
                onDiscardAutomatic={() => void discardAutomaticInstall()}
              />
            ) : null}
          </>
        )}

        <div className="launcher-secondary-actions">
          <button
            type="button"
            className="btn"
            onClick={() => void refresh(
              automaticStartPending
                ? installerIntent?.targetRoot ?? undefined
                : undefined,
            )}
            disabled={busy}
          >
            {state.loading
              ? t("desktop.checking")
              : state.planLoading
                ? t("desktop.planUpdating")
                : t("desktop.refresh")}
          </button>
        </div>

        <details className="launcher-details">
          <summary>
            <span>
              <strong>{t("launcher.details")}</strong>
              <small>{t("launcher.detailsHint")}</small>
            </span>
            <span aria-hidden="true">⌄</span>
          </summary>
          <div className="launcher-details-content stack-md">
            <div className="launcher-details-toolbar">
              <strong>{t("launcher.details")}</strong>
              <button
                type="button"
                className="btn"
                onClick={(event) => {
                  event.currentTarget.closest("details")?.removeAttribute("open");
                }}
              >
                {t("launcher.closeDetails")}
              </button>
            </div>
            <ReadinessHero
              prerequisites={state.prerequisites}
              runtime={state.runtime}
              loading={state.loading}
              prerequisitesFresh={state.prerequisitesFresh}
              runtimeFresh={state.runtimeFresh}
            />
            {state.prerequisites ? (
              <PrerequisiteOverview
                report={state.prerequisites}
                stale={!state.prerequisitesFresh}
              />
            ) : null}
            {state.runtime ? (
              <RuntimeOverview report={state.runtime} stale={!state.runtimeFresh} />
            ) : null}
            {localRuntimeReady && state.runtimeFresh && state.runtime?.installed ? (
              <InstalledRuntimeNotice
                report={state.runtime}
                busy={runtimeCommandBusy}
                onStart={() => void runRuntimeAction("start")}
                onRepair={() => void runRuntimeAction("repair")}
              />
            ) : null}
            {showInstallPlanner && state.plan ? (
              <InstallPlanOverview
                plan={state.plan}
                automaticInstallConfirmed={automaticStartScheduled}
              />
            ) : null}
          </div>
        </details>
      </section>
    );
  }

  return (
    <section
      className="desktop-setup-page stack-md"
      aria-busy={desktopAvailable ? busy : undefined}
    >
      <header className="page-header desktop-setup-header">
        <div>
          <div className="desktop-eyebrow">{t("desktop.eyebrow")}</div>
          <h1>{t("desktop.title")}</h1>
          <p className="page-header-subtitle">{t("desktop.subtitle")}</p>
        </div>
        {desktopAvailable ? (
          <button
            type="button"
            className="btn"
            onClick={() => void refresh(
              automaticStartPending
                ? installerIntent?.targetRoot ?? undefined
                : undefined,
            )}
            disabled={busy}
          >
            {state.loading
              ? t("desktop.checking")
              : state.planLoading
                ? t("desktop.planUpdating")
                : t("desktop.refresh")}
          </button>
        ) : null}
      </header>

      {requestedFeatureLabel && !localRuntimeReady ? (
        <Alert tone="warning" title={t("runtimeGate.redirectTitle")}>
          <p className="desktop-alert-copy">{t("runtimeGate.redirectBody")}</p>
          <p className="desktop-alert-copy">
            <strong>{t("runtimeGate.requestedFeature")}:</strong>{" "}
            {requestedFeatureLabel}
          </p>
        </Alert>
      ) : null}

      {!desktopAvailable ? (
        <BrowserExplanation />
      ) : (
        <>
          <ReadinessHero
            prerequisites={state.prerequisites}
            runtime={state.runtime}
            loading={state.loading}
            prerequisitesFresh={state.prerequisitesFresh}
            runtimeFresh={state.runtimeFresh}
          />

          <InstallerHandoffNotice
            state={installerHandoffState}
            discardAvailable={installerHandoffDiscardAvailable}
            discardBusy={installerHandoffState.discarding}
            receiptCleanupRecovered={receiptCleanupRecovered}
            waitingForRestart={installState.snapshot?.phase === "waitingForRestart"}
            onRetry={retryInstallerHandoff}
            onDiscard={() => void discardAutomaticInstall()}
          />

          {state.issues.length > 0 ? (
            <Alert tone="warning" title={t("desktop.probeIssue")}>
              <p className="desktop-alert-copy">{t("desktop.partialFailure")}</p>
              <ul className="desktop-diagnostic-list">
                {state.issues.map((issue) => (
                  <li key={issue.source}>
                    <code>{issue.command}: {issue.message}</code>
                  </li>
                ))}
              </ul>
            </Alert>
          ) : null}

          {state.loading && !state.prerequisites && !state.runtime && !state.plan ? (
            <Loading label={t("desktop.checking")} />
          ) : null}

          {state.prerequisites ? (
            <PrerequisiteOverview
              report={state.prerequisites}
              stale={!state.prerequisitesFresh}
            />
          ) : null}
          {state.runtime ? (
            <RuntimeOverview report={state.runtime} stale={!state.runtimeFresh} />
          ) : null}
          {runtimeCommandError ? (
            <Alert tone="warning" title={t("desktop.runtimeActionFailed")}>
              <code>{runtimeCommandError}</code>
            </Alert>
          ) : null}
          {state.runtimeFresh && state.runtime?.installed ? (
            <InstalledRuntimeNotice
              report={state.runtime}
              busy={runtimeCommandBusy}
              onStart={() => void runRuntimeAction("start")}
              onRepair={() => void runRuntimeAction("repair")}
            />
          ) : null}
          {showInstallPlanner && state.prerequisites ? (
            <RuntimeStorageSelector
              disks={fixedDiskOptions(state.prerequisites.disks)}
              selectedDrive={selectedDrive}
              disabled={
                busy ||
                automaticStartPending ||
                installState.snapshot?.phase === "waitingForRestart"
              }
              onChange={(drive) => void selectRuntimeDrive(drive)}
            />
          ) : null}
          {showInstallPlanner && state.planLoading ? (
            <Loading label={t("desktop.planUpdating")} />
          ) : null}
          {showInstallPlanner && state.plan ? (
            <InstallPlanOverview
              plan={state.plan}
              automaticInstallConfirmed={automaticStartScheduled}
            />
          ) : null}
          {automaticStartPending && !exactInstallerPlanReady ? (
            <InstallerPlanFallback
              targetRoot={installerIntent?.targetRoot ?? ""}
              issues={state.issues}
              checking={
                !installerHandoffState.previewSettled ||
                state.loading ||
                state.planLoading
              }
              discardBusy={installerHandoffState.discarding}
              onRetry={retryInstallerHandoff}
              onDiscard={() => void discardAutomaticInstall()}
            />
          ) : null}
          {(showInstallPlanner && state.plan) ||
          (installState.snapshot && installState.snapshot.phase !== "idle") ? (
            <RuntimeInstallControls
              plan={state.plan}
              snapshot={installState.snapshot}
              commandError={installState.commandError}
              commandBusy={installState.commandBusy}
              automaticStartPending={automaticStartPending}
              automaticStartUncertain={installerHandoffState.autoStartUncertain}
              automaticDiscardBusy={installerHandoffState.discarding}
              receiptCleanupPending={receiptCleanupPending}
              receiptCleanupInstalled={Boolean(
                installState.snapshot?.installedVersion,
              )}
              restartContinuationPending={restartContinuationPending}
              releaseManifestUrlAvailable={
                releaseManifestUrl !== null || installerManagedInstall
              }
              onStart={() => void beginOrResumeInstall()}
              onCancel={() => void cancelInstall()}
              onDiscardAutomatic={() => void discardAutomaticInstall()}
            />
          ) : null}
        </>
      )}
    </section>
  );
}

function BrowserExplanation() {
  const { t } = useI18n();
  return (
    <div className="desktop-browser-card" role="note">
      <div className="desktop-browser-illustration" aria-hidden="true">
        <span>◇</span>
        <span>WSL 2</span>
      </div>
      <div>
        <h2>{t("desktop.browserTitle")}</h2>
        <p>{t("desktop.browserBody")}</p>
        <p className="desktop-browser-hint">{t("desktop.browserHint")}</p>
      </div>
    </div>
  );
}

function InstallerHandoffNotice({
  state,
  discardAvailable,
  discardBusy,
  receiptCleanupRecovered,
  waitingForRestart,
  onRetry,
  onDiscard,
}: {
  state: InstallerHandoffState;
  discardAvailable: boolean;
  discardBusy: boolean;
  receiptCleanupRecovered: boolean;
  waitingForRestart: boolean;
  onRetry: () => void;
  onDiscard: () => void;
}) {
  const { t } = useI18n();
  if (state.checking) {
    return (
      <Alert tone="info" title={t("desktop.installerChoiceChecking")}>
        {t("desktop.installerChoiceCheckingHint")}
      </Alert>
    );
  }
  if (state.discardResult?.discarded) {
    return (
      <Alert
        tone="success"
        title={t(receiptCleanupRecovered
          ? "desktop.receiptCleanupRecovered"
          : waitingForRestart
            ? "desktop.restartContinuationCancelled"
            : "desktop.autoInstallCancelled")}
      >
        {t(receiptCleanupRecovered
          ? "desktop.receiptCleanupRecoveredHint"
          : waitingForRestart
            ? "desktop.restartContinuationCancelledHint"
            : "desktop.autoInstallCancelledHint")}
      </Alert>
    );
  }
  if (state.discardResult && !state.discardResult.discarded) {
    return (
      <Alert
        tone="warning"
        title={t(state.autoStartUncertain
          ? "desktop.autoInstallCancelNotConfirmed"
          : "desktop.autoInstallAlreadyStarted")}
      >
        <p>
          {state.discardResult.message ?? t(state.autoStartUncertain
            ? "desktop.autoInstallCancelNotConfirmedHint"
            : "desktop.autoInstallAlreadyStartedHint")}
        </p>
        {state.autoStartUncertain ? (
          <button type="button" className="btn" onClick={onRetry}>
            {t("desktop.retryInstallerCheck")}
          </button>
        ) : null}
      </Alert>
    );
  }
  if (state.commandError) {
    return (
      <Alert tone="warning" title={t("desktop.installerChoiceFailed")}>
        <p><code>{state.commandError}</code></p>
        <button type="button" className="btn" onClick={onRetry}>
          {t("desktop.retryInstallerCheck")}
        </button>
      </Alert>
    );
  }
  const result = state.result;
  if (result?.disposition === "invalid") {
    return (
      <Alert tone="warning" title={t("desktop.installerChoiceInvalid")}>
        <p>{t("desktop.installerChoiceInvalidHint")}</p>
        {result.message ? <p>{result.message}</p> : null}
        <div className="desktop-install-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={state.autoStarting || discardBusy}
            onClick={onRetry}
          >
            {t("desktop.retryInstallerCheck")}
          </button>
          {discardAvailable ? (
            <button
              type="button"
              className="btn"
              disabled={discardBusy}
              onClick={onDiscard}
            >
              {discardBusy
                ? t("desktop.cancellingAutomaticInstall")
                : t("desktop.cancelAutomaticInstall")}
            </button>
          ) : null}
        </div>
      </Alert>
    );
  }
  if (result?.disposition === "alreadyInstalled") {
    return (
      <Alert tone="success" title={t("desktop.installerRuntimeAlreadyInstalled")}>
        {t("desktop.installerRuntimeAlreadyInstalledHint")}
      </Alert>
    );
  }
  if (result?.disposition === "resumed") {
    return (
      <Alert tone="success" title={t("desktop.autoInstallResumed")}>
        {t("desktop.autoInstallResumedHint")}
      </Alert>
    );
  }
  if (result?.disposition === "started") {
    return (
      <Alert tone="success" title={t("desktop.autoInstallStarted")}>
        {t("desktop.autoInstallStartedHint")}
      </Alert>
    );
  }

  const intent = state.intent;
  if (!intent || intent.status === "none") return null;
  if (intent.status === "desktopOnly") {
    return (
      <Alert tone="info" title={t("desktop.desktopOnlySelected")}>
        {t("desktop.desktopOnlySelectedHint")}
      </Alert>
    );
  }
  if (intent.status === "invalid") {
    return (
      <Alert tone="warning" title={t("desktop.installerChoiceInvalid")}>
        <p>{t("desktop.installerChoiceInvalidHint")}</p>
        {intent.message ? <p>{intent.message}</p> : null}
        <div className="desktop-install-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={state.autoStarting || discardBusy}
            onClick={onRetry}
          >
            {t("desktop.retryInstallerCheck")}
          </button>
          {discardAvailable ? (
            <button
              type="button"
              className="btn"
              disabled={discardBusy}
              onClick={onDiscard}
            >
              {discardBusy
                ? t("desktop.cancellingAutomaticInstall")
                : t("desktop.cancelAutomaticInstall")}
            </button>
          ) : null}
        </div>
      </Alert>
    );
  }
  return (
    <Alert tone="info" title={t("desktop.installerChoiceReady")}>
      {t("desktop.installerChoiceReadyHint")}
    </Alert>
  );
}

function InstallerPlanFallback({
  targetRoot,
  issues,
  checking,
  discardBusy,
  onRetry,
  onDiscard,
}: {
  targetRoot: string;
  issues: ProbeIssue[];
  checking: boolean;
  discardBusy: boolean;
  onRetry: () => void;
  onDiscard: () => void;
}) {
  const { t } = useI18n();
  return (
    <SectionCard
      title={t("desktop.installerFallbackTitle")}
      description={t("desktop.installerFallbackHint")}
    >
      <p className="desktop-installer-target">
        {t("desktop.confirmedTarget")}: <code>{targetRoot}</code>
      </p>
      {checking ? (
        <Loading label={t("desktop.checkingExactPlan")} />
      ) : issues.length > 0 ? (
        <ul className="desktop-diagnostic-list">
          {issues.map((issue) => (
            <li key={issue.source}>
              <code>{issue.command}: {issue.message}</code>
            </li>
          ))}
        </ul>
      ) : (
        <p>{t("desktop.exactPlanUnavailable")}</p>
      )}
      <div className="desktop-install-actions">
        <button
          type="button"
          className="btn btn-primary"
          disabled={checking || discardBusy}
          onClick={onRetry}
        >
          {t("desktop.retryInstallerCheck")}
        </button>
        <button
          type="button"
          className="btn"
          disabled={discardBusy}
          onClick={onDiscard}
        >
          {discardBusy
            ? t("desktop.cancellingAutomaticInstall")
            : t("desktop.cancelAutomaticInstall")}
        </button>
      </div>
    </SectionCard>
  );
}

function ReadinessHero({
  prerequisites,
  runtime,
  loading,
  prerequisitesFresh,
  runtimeFresh,
}: {
  prerequisites: SystemPrerequisiteReport | null;
  runtime: RuntimeStatusReport | null;
  loading: boolean;
  prerequisitesFresh: boolean;
  runtimeFresh: boolean;
}) {
  const { t } = useI18n();
  const ready =
    prerequisitesFresh &&
    runtimeFresh &&
    isOverallDesktopReady(prerequisites, runtime);
  const title = loading
    ? t("desktop.checking")
    : prerequisitesFresh && runtimeFresh && runtime
      ? ready
        ? t("desktop.ready")
        : t("desktop.needsAction")
      : t("desktop.statusUnavailable");

  return (
    <div
      className={`desktop-readiness-hero ${
        ready ? "desktop-readiness-ready" : "desktop-readiness-pending"
      }`}
      role="status"
      aria-live="polite"
    >
      <span className="desktop-readiness-icon" aria-hidden="true">
        {ready ? "✓" : loading ? "…" : "!"}
      </span>
      <div>
        <strong>{title}</strong>
        {runtime && !loading ? (
          <span>
            {runtime.runtimeName} · {runtime.installed
              ? t("desktop.installed")
              : t("desktop.notInstalled")} · {runtime.running
              ? t("desktop.running")
              : t("desktop.stopped")}
          </span>
        ) : null}
      </div>
      {ready ? (
        <Link to="/jobs/new" className="btn btn-primary">
          {t("desktop.continue")}
        </Link>
      ) : null}
    </div>
  );
}

function PrerequisiteOverview({
  report,
  stale,
}: {
  report: SystemPrerequisiteReport;
  stale: boolean;
}) {
  const { t } = useI18n();
  const hasWsl2 = report.wsl.distributions.some((distribution) => distribution.version === 2);
  const memoryReady = (report.memory?.totalBytes ?? 0) >= MINIMUM_MEMORY_BYTES;
  const bestDisk = report.disks.reduce<DiskInfo | null>(
    (best, disk) => (!best || disk.freeBytes > best.freeBytes ? disk : best),
    null,
  );

  return (
    <SectionCard
      title={t("desktop.overviewTitle")}
      description={t("desktop.overviewDesc")}
      actions={stale ? <StaleResultBadge /> : null}
    >
      <div className="desktop-check-grid">
        <CheckCard
          label={t("desktop.os")}
          state={report.supported ? "ready" : "warning"}
          value={report.windows?.caption ?? report.platform}
          detail={report.windows
            ? `${report.windows.architecture} · ${report.windows.version} (${report.windows.buildNumber})`
            : t(report.supported ? "desktop.supported" : "desktop.unsupported")}
        />
        <CheckCard
          label={t("desktop.wsl")}
          state={report.wsl.executableAvailable && hasWsl2 ? "ready" : "warning"}
          value={report.wsl.executableAvailable
            ? hasWsl2
              ? t("desktop.supported")
              : t("desktop.needsAction")
            : t("desktop.unsupported")}
          detail={report.wsl.distributions.length > 0
            ? report.wsl.distributions
                .map((distribution) =>
                  `${distribution.name} · WSL ${distribution.version ?? "?"}${
                    distribution.isDefault ? ` · ${t("desktop.defaultDistro")}` : ""
                  }`,
                )
                .join(" | ")
            : t("desktop.noDistro")}
        />
        <CheckCard
          label={t("desktop.memory")}
          state={memoryReady ? "ready" : "warning"}
          value={report.memory ? formatBytes(report.memory.totalBytes) : "—"}
          detail={report.memory
            ? `${formatBytes(report.memory.availableBytes)} ${t("desktop.available")}`
            : t("desktop.statusUnavailable")}
        />
        <CheckCard
          label={t("desktop.disk")}
          state={(bestDisk?.freeBytes ?? 0) >= 40 * GIB ? "ready" : "warning"}
          value={bestDisk
            ? `${bestDisk.drive} · ${formatBytes(bestDisk.freeBytes)} ${t("desktop.available")}`
            : "—"}
          detail={report.disks
            .map((disk) =>
              `${disk.drive} ${formatBytes(disk.freeBytes)} / ${formatBytes(disk.totalBytes)}${
                disk.isSystemDrive ? ` · ${t("desktop.systemDrive")}` : ""
              }`,
            )
            .join(" | ") || t("desktop.statusUnavailable")}
        />
      </div>

      <div className="desktop-hardware-list">
        <h3>{t("desktop.gpu")}</h3>
        {report.gpus.length > 0 ? (
          <ul>
            {report.gpus.map((gpu, index) => (
              <li key={`${gpu.name}-${index}`}>
                <strong>{gpu.name}</strong>
                <span>
                  {gpu.adapterRamBytes ? formatBytes(gpu.adapterRamBytes) : null}
                  {gpu.adapterRamBytes && gpu.driverVersion ? " · " : null}
                  {gpu.driverVersion
                    ? `${t("desktop.driver")} ${gpu.driverVersion}`
                    : null}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p>{t("desktop.noGpu")}</p>
        )}
      </div>

      {report.probeErrors.length > 0 ? (
        <Alert tone="warning" title={t("desktop.probeIssue")}>
          <ul className="desktop-diagnostic-list">
            {report.probeErrors.map((error, index) => (
              <li key={`${index}-${error}`}>{error}</li>
            ))}
          </ul>
        </Alert>
      ) : null}
    </SectionCard>
  );
}

function CheckCard({
  label,
  state,
  value,
  detail,
}: {
  label: string;
  state: "ready" | "warning";
  value: string;
  detail: string;
}) {
  const { t } = useI18n();
  return (
    <article className={`desktop-check-card desktop-check-${state}`}>
      <div className="desktop-check-heading">
        <span>{label}</span>
        <span>
          <span aria-hidden="true">{state === "ready" ? "✓" : "!"}</span>
          <span className="sr-only">
            {state === "ready" ? t("desktop.checkReady") : t("desktop.checkWarning")}
          </span>
        </span>
      </div>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function RuntimeStorageSelector({
  disks,
  selectedDrive,
  disabled,
  onChange,
}: {
  disks: DiskInfo[];
  selectedDrive: string;
  disabled: boolean;
  onChange: (drive: string) => void;
}) {
  const { t } = useI18n();
  const targetRoot = runtimeTargetRoot(selectedDrive);

  return (
    <SectionCard
      title={t("desktop.storageTitle")}
      description={t("desktop.storageDesc")}
    >
      {disks.length === 0 ? (
        <Alert tone="warning" title={t("desktop.storageNoDisk")}>
          <p>{t("desktop.storageNoDiskHint")}</p>
        </Alert>
      ) : (
        <div className="desktop-storage-selector">
          <div className="form-field">
            <label htmlFor="desktop-runtime-drive">{t("desktop.storageDrive")}</label>
            <select
              id="desktop-runtime-drive"
              value={selectedDrive}
              disabled={disabled}
              aria-describedby="desktop-runtime-target"
              onChange={(event) => onChange(event.target.value)}
            >
              {disks.map((disk) => (
                <option key={disk.drive} value={disk.drive}>
                  {disk.drive} · {formatBytes(disk.freeBytes)} {t("desktop.availableOf")}{" "}
                  {formatBytes(disk.totalBytes)}
                  {disk.isSystemDrive ? ` · ${t("desktop.systemDrive")}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="desktop-storage-target" id="desktop-runtime-target">
            <span>{t("desktop.storageTarget")}</span>
            <code>{targetRoot ?? "—"}</code>
          </div>
        </div>
      )}
    </SectionCard>
  );
}

function RuntimeOverview({
  report,
  stale,
}: {
  report: RuntimeStatusReport;
  stale: boolean;
}) {
  const { t } = useI18n();
  const ready = !stale && isRuntimeFullyReady(report);
  return (
    <SectionCard
      title={t("desktop.runtimeTitle")}
      description={t("desktop.runtimeDesc")}
      actions={
        stale ? (
          <StaleResultBadge />
        ) : (
          <span className={`desktop-runtime-pill ${ready ? "ready" : "pending"}`}>
            {ready ? t("desktop.runtimeHealthy") : t("desktop.needsAction")}
          </span>
        )
      }
    >
      <dl className="desktop-runtime-facts">
        <div>
          <dt>{t("desktop.installed")}</dt>
          <dd>{report.installed ? t("desktop.yes") : t("desktop.no")}</dd>
        </div>
        <div>
          <dt>{t("desktop.running")}</dt>
          <dd>{report.running ? t("desktop.yes") : t("desktop.no")}</dd>
        </div>
        <div>
          <dt>{t("desktop.runtimeVersion")}</dt>
          <dd>{report.version || "—"}</dd>
        </div>
        <div>
          <dt>{t("desktop.runtimeLocation")}</dt>
          <dd><code>{report.dataRoot || "—"}</code></dd>
        </div>
      </dl>

      {report.components.length > 0 ? (
        <div className="desktop-component-list">
          {report.components.map((component) => (
            <article key={component.id} className="desktop-component-row">
              <span
                className={`desktop-component-state desktop-component-${component.status}`}
                aria-hidden="true"
              />
              <div>
                <strong>{translatedComponentLabel(t, component.id, component.label)}</strong>
                <span>{component.detail || component.version || "—"}</span>
              </div>
              <div className="desktop-component-badges">
                <span className={`desktop-status-badge desktop-status-${component.status}`}>
                  {t(componentStateKey(component.status))}
                </span>
                <span className="desktop-requirement-badge">
                  {component.required ? t("desktop.required") : t("desktop.optional")}
                </span>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      {report.diagnostics.length > 0 ? (
        <div className="desktop-diagnostics">
          <h3>{t("desktop.diagnosticsTitle")}</h3>
          <ul className="desktop-diagnostic-list">
            {report.diagnostics.map((diagnostic, index) => (
              <li key={`${index}-${diagnostic}`}>{diagnostic}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </SectionCard>
  );
}

function StaleResultBadge() {
  const { t } = useI18n();
  return <span className="desktop-stale-pill">{t("desktop.lastSuccessful")}</span>;
}

function InstalledRuntimeNotice({
  report,
  busy,
  onStart,
  onRepair,
}: {
  report: RuntimeStatusReport;
  busy: boolean;
  onStart: () => void;
  onRepair: () => void;
}) {
  const { t } = useI18n();
  const ready = isRuntimeFullyReady(report);
  return (
    <Alert
      tone={ready ? "success" : "warning"}
      title={ready
        ? t("desktop.runtimeAlreadyReady")
        : t("desktop.runtimeNeedsRepair")}
    >
      <p>{t("desktop.installedStorageHint")}</p>
      {!ready ? (
        <div className="desktop-install-actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={report.running ? onRepair : onStart}
          >
            {busy
              ? t("desktop.runtimeActionRunning")
              : report.running
                ? t("desktop.repairRuntime")
                : t("desktop.startRuntime")}
          </button>
        </div>
      ) : null}
    </Alert>
  );
}

function InstallPlanOverview({
  plan,
  automaticInstallConfirmed,
}: {
  plan: RuntimeInstallPlan;
  automaticInstallConfirmed: boolean;
}) {
  const { t } = useI18n();
  const canProceed = plan.canInstall && plan.blockers.length === 0;
  const blockers = plan.blockers.length > 0
    ? plan.blockers
    : plan.canInstall
      ? []
      : [t("desktop.unknownBlocker")];
  return (
    <SectionCard
      title={t("desktop.planTitle")}
      description={t("desktop.planDesc")}
    >
      <div className="desktop-plan-summary">
        <PlanFact label={t("desktop.target")} value={plan.targetRoot || "—"} mono />
        <PlanFact label={t("desktop.download")} value={formatBytes(plan.estimatedDownloadBytes)} />
        <PlanFact label={t("desktop.installedSize")} value={formatBytes(plan.estimatedInstalledBytes)} />
        <PlanFact
          label={t("desktop.administrator")}
          value={plan.requiresAdministrator ? t("desktop.yes") : t("desktop.no")}
        />
        <PlanFact
          label={t("desktop.restart")}
          value={plan.requiresRestart ? t("desktop.yes") : t("desktop.no")}
        />
      </div>

      <Alert
        tone={canProceed ? "success" : "warning"}
        title={canProceed ? t("desktop.canInstall") : t("desktop.planBlocked")}
      >
        {t(automaticInstallConfirmed
          ? "desktop.confirmedInstallChanges"
          : "desktop.noChanges")}
      </Alert>

      {blockers.length > 0 ? (
        <div className="desktop-plan-blockers">
          <h3>{t("desktop.blockers")}</h3>
          <ul className="desktop-diagnostic-list">
            {blockers.map((blocker, index) => (
              <li key={`${index}-${blocker}`}>{blocker}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="desktop-install-steps">
        <h3>{t("desktop.steps")}</h3>
        <ol>
          {plan.steps.map((step, index) => (
            <li key={step.id}>
              <span className="desktop-step-number">{index + 1}</span>
              <div>
                <strong>{translatedStepText(t, step.id, "title", step.title)}</strong>
                <p>{translatedStepText(t, step.id, "description", step.description)}</p>
                <div className="desktop-step-meta">
                  {step.requiresAdministrator ? (
                    <span>{t("desktop.administrator")}</span>
                  ) : null}
                  {step.destructive ? <span>{t("desktop.destructive")}</span> : null}
                  {step.estimatedBytes ? <span>{formatBytes(step.estimatedBytes)}</span> : null}
                </div>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </SectionCard>
  );
}

interface TransferEstimate {
  bytesPerSecond: number | null;
  secondsRemaining: number | null;
}

interface TransferSample {
  operationId: string;
  bytes: number;
  capturedAt: number;
}

function useRuntimeTransferEstimate(
  snapshot: RuntimeInstallSnapshot | null,
): TransferEstimate {
  const samples = useRef<TransferSample[]>([]);
  const [estimate, setEstimate] = useState<TransferEstimate>({
    bytesPerSecond: null,
    secondsRemaining: null,
  });

  useEffect(() => {
    if (
      snapshot?.phase !== "downloading" ||
      !snapshot.operationId ||
      snapshot.bytesTotal === null
    ) {
      samples.current = [];
      setEstimate({ bytesPerSecond: null, secondsRemaining: null });
      return;
    }

    const now = performance.now();
    const operationSamples = samples.current.filter(
      (sample) =>
        sample.operationId === snapshot.operationId &&
        now - sample.capturedAt <= 20_000,
    );
    const previous = operationSamples.at(-1);
    if (!previous || previous.bytes !== snapshot.bytesDownloaded) {
      operationSamples.push({
        operationId: snapshot.operationId,
        bytes: snapshot.bytesDownloaded,
        capturedAt: now,
      });
    }
    samples.current = operationSamples.slice(-24);

    const first = samples.current[0];
    const last = samples.current.at(-1);
    if (!first || !last || first === last) {
      setEstimate({ bytesPerSecond: null, secondsRemaining: null });
      return;
    }
    const elapsedSeconds = (last.capturedAt - first.capturedAt) / 1000;
    const transferred = last.bytes - first.bytes;
    if (elapsedSeconds < 1.5 || transferred <= 0) {
      setEstimate({ bytesPerSecond: null, secondsRemaining: null });
      return;
    }
    const bytesPerSecond = transferred / elapsedSeconds;
    const remainingBytes = Math.max(0, snapshot.bytesTotal - snapshot.bytesDownloaded);
    setEstimate({
      bytesPerSecond,
      secondsRemaining: Math.ceil(remainingBytes / bytesPerSecond),
    });
  }, [
    snapshot?.bytesDownloaded,
    snapshot?.bytesTotal,
    snapshot?.operationId,
    snapshot?.phase,
  ]);

  return estimate;
}

function formatRemainingTime(seconds: number, locale: "en" | "zh-CN"): string {
  if (seconds < 60) return locale === "zh-CN" ? "不足 1 分钟" : "less than a minute";
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) {
    return locale === "zh-CN" ? `约 ${minutes} 分钟` : `about ${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  if (locale === "zh-CN") {
    return remainder > 0 ? `约 ${hours} 小时 ${remainder} 分钟` : `约 ${hours} 小时`;
  }
  return remainder > 0 ? `about ${hours} hr ${remainder} min` : `about ${hours} hr`;
}

function RuntimeLauncherHero({
  snapshot,
  ready,
  checking,
  automaticStartPending,
}: {
  snapshot: RuntimeInstallSnapshot | null;
  ready: boolean;
  checking: boolean;
  automaticStartPending: boolean;
}) {
  const { locale, t } = useI18n();
  const phase = snapshot?.phase ?? "idle";
  const active = isActiveInstall(snapshot);
  const total = snapshot?.bytesTotal ?? null;
  const downloaded = snapshot?.bytesDownloaded ?? 0;
  const percent = total && total > 0
    ? Math.min(100, Math.round((downloaded / total) * 100))
    : ready || phase === "completed"
      ? 100
      : null;
  const estimate = useRuntimeTransferEstimate(snapshot);
  const currentProgressIndex = INSTALL_PROGRESS_PHASES.indexOf(phase);
  const headline = ready
    ? t("launcher.title.ready")
    : phase === "downloading"
      ? t("launcher.title.downloading")
      : active || phase === "waitingForRestart"
        ? t("launcher.title.preparing")
        : checking || automaticStartPending
          ? t("launcher.title.checking")
          : t("launcher.title.welcome");
  const subtitle = ready
    ? t("launcher.subtitle.ready")
    : active
      ? t("launcher.subtitle.active")
      : t("launcher.subtitle.welcome");

  return (
    <div className={`launcher-hero launcher-hero-${ready ? "ready" : phase}`}>
      <div className="launcher-hero-visual">
        <Suspense fallback={<DroneSceneLoadingFallback />}>
          <DroneLaunchScene active={active || ready} progress={percent} />
        </Suspense>
        <div className="launcher-hero-copy">
          <span className="launcher-eyebrow">
            <span aria-hidden="true" />
            {t("launcher.eyebrow")}
          </span>
          <h1>{headline}</h1>
          <p>{subtitle}</p>
        </div>
      </div>

      <div className="launcher-progress-panel" role="status" aria-live="polite">
        <div className="launcher-progress-heading">
          <div>
            <span>{t("desktop.currentStage")}</span>
            <strong>
              {ready
                ? t("desktop.installPhase.completed")
                : automaticStartPending && phase === "idle"
                  ? t("desktop.installPhase.confirmed")
                  : checking && phase === "idle"
                    ? t("desktop.checking")
                    : t(installPhaseKey(phase))}
            </strong>
          </div>
          <strong>{percent === null ? "—" : `${percent}%`}</strong>
        </div>
        <div className={`launcher-progress-track${percent === null && (active || checking) ? " indeterminate" : ""}`}>
          <span style={{ width: `${percent ?? 0}%` }} />
        </div>
        <div className="launcher-transfer-row">
          <span>
            {total === null
              ? downloaded > 0
                ? `${formatBytes(downloaded)} ${t("desktop.downloaded")}`
                : t("launcher.waitingForSize")
              : `${formatBytes(downloaded)} / ${formatBytes(total)}`}
          </span>
          <span className="launcher-transfer-metrics">
            {phase === "downloading" ? (
              <>
                <span>
                  {estimate.bytesPerSecond === null
                    ? t("launcher.calculatingSpeed")
                    : `${formatBytes(Math.round(estimate.bytesPerSecond))}/s`}
                </span>
                <span aria-hidden="true">·</span>
                <span>
                  {estimate.secondsRemaining === null
                    ? t("launcher.calculatingTime")
                    : `${t("launcher.remaining")} ${formatRemainingTime(
                        estimate.secondsRemaining,
                        locale,
                      )}`}
                </span>
              </>
            ) : snapshot?.currentPart !== null && snapshot?.currentPart !== undefined &&
              snapshot.totalParts !== null ? (
                <span>
                  {t("desktop.downloadPart")} {snapshot.currentPart} / {snapshot.totalParts}
                </span>
              ) : null}
          </span>
        </div>

        <ol className="launcher-stage-strip" aria-label={t("desktop.installStages")}>
          {INSTALL_PROGRESS_PHASES.map((installPhase, index) => {
            const complete = ready || phase === "completed" || currentProgressIndex > index;
            const current = phase === installPhase;
            return (
              <li
                key={installPhase}
                className={complete ? "complete" : current ? "current" : "pending"}
              >
                <span aria-hidden="true">{complete ? "✓" : index + 1}</span>
                <small>{t(installPhaseKey(installPhase))}</small>
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}

function DroneSceneLoadingFallback() {
  return (
    <div className="drone-launch-scene" aria-hidden="true">
      <div className="drone-launch-aura" />
      <div className="drone-launch-fallback">
        <span className="drone-launch-fallback-body" />
        <span className="drone-launch-fallback-rotor rotor-a" />
        <span className="drone-launch-fallback-rotor rotor-b" />
        <span className="drone-launch-fallback-rotor rotor-c" />
        <span className="drone-launch-fallback-rotor rotor-d" />
      </div>
    </div>
  );
}

const INSTALL_PROGRESS_PHASES: RuntimeInstallPhase[] = [
  "verifyingManifest",
  "downloading",
  "verifyingArchive",
  "importing",
  "starting",
  "healthChecking",
];

function RuntimeInstallControls({
  launcherMode = false,
  plan,
  snapshot,
  commandError,
  commandBusy,
  automaticStartPending,
  automaticStartUncertain,
  automaticDiscardBusy,
  receiptCleanupPending,
  receiptCleanupInstalled,
  restartContinuationPending,
  releaseManifestUrlAvailable,
  onStart,
  onCancel,
  onDiscardAutomatic,
}: {
  launcherMode?: boolean;
  plan: RuntimeInstallPlan | null;
  snapshot: RuntimeInstallSnapshot | null;
  commandError: string | null;
  commandBusy: boolean;
  automaticStartPending: boolean;
  automaticStartUncertain: boolean;
  automaticDiscardBusy: boolean;
  receiptCleanupPending: boolean;
  receiptCleanupInstalled: boolean;
  restartContinuationPending: boolean;
  releaseManifestUrlAvailable: boolean;
  onStart: () => void;
  onCancel: () => void;
  onDiscardAutomatic: () => void;
}) {
  const { t } = useI18n();
  const phase = snapshot?.phase ?? "idle";
  const active = isActiveInstall(snapshot);
  const planCanInstall = Boolean(
    plan?.canInstall &&
    plan.blockers.length === 0,
  );
  const canInstall = planCanInstall && releaseManifestUrlAvailable;
  const canRetry =
    phase !== "failed" ||
    Boolean(snapshot?.resumable || snapshot?.error?.retryable);
  const total = snapshot?.bytesTotal ?? null;
  const downloaded = snapshot?.bytesDownloaded ?? 0;
  const percent = total && total > 0
    ? Math.min(100, Math.round((downloaded / total) * 100))
    : null;
  const currentProgressIndex = INSTALL_PROGRESS_PHASES.indexOf(phase);
  const automaticStartWillRun =
    automaticStartPending && !automaticStartUncertain;
  const automaticStartNeedsFailClosedValidation =
    automaticStartWillRun && !planCanInstall;

  let startLabel = t("desktop.installNow");
  if (phase === "failed") startLabel = t("desktop.retryInstall");
  if (phase === "cancelled") startLabel = t("desktop.resumeInstall");
  if (phase === "waitingForRestart") startLabel = t("desktop.continueInstall");

  return (
    <SectionCard
      title={launcherMode ? t("launcher.actionsTitle") : t("desktop.installerTitle")}
      description={launcherMode ? t("launcher.actionsHint") : t("desktop.installerDesc")}
      actions={snapshot?.installedVersion ? (
        <span className="desktop-runtime-pill ready">
          {snapshot.installedVersion}
        </span>
      ) : null}
    >
      {!launcherMode ? (
        <div
          className={`desktop-installer-status desktop-installer-${phase}`}
          role="status"
          aria-live="polite"
          aria-busy={active || commandBusy || automaticStartWillRun}
        >
        <div className="desktop-installer-heading">
          <div>
            <span>{t("desktop.currentStage")}</span>
            <strong>
              {automaticStartWillRun && phase === "idle"
                ? t("desktop.installPhase.confirmed")
                : t(installPhaseKey(phase))}
            </strong>
          </div>
          {percent !== null ? <strong>{percent}%</strong> : null}
        </div>

        <progress
          className="desktop-installer-progress"
          max={total && total > 0 ? total : 1}
          value={total && total > 0 ? Math.min(downloaded, total) : 0}
          aria-label={t("desktop.downloadProgress")}
        />
        <div className="desktop-installer-byte-row">
          <span>
            {total === null
              ? `${formatBytes(downloaded)} ${t("desktop.downloaded")}`
              : `${formatBytes(downloaded)} / ${formatBytes(total)}`}
          </span>
          {snapshot?.currentPart !== null && snapshot?.currentPart !== undefined &&
          snapshot.totalParts !== null ? (
            <span>
              {t("desktop.downloadPart")} {snapshot.currentPart} / {snapshot.totalParts}
            </span>
          ) : null}
        </div>

        <ol className="desktop-installer-phases" aria-label={t("desktop.installStages")}>
          {INSTALL_PROGRESS_PHASES.map((installPhase, index) => {
            const complete =
              phase === "completed" ||
              currentProgressIndex > index;
            const current = phase === installPhase;
            return (
              <li
                key={installPhase}
                className={complete
                  ? "complete"
                  : current
                    ? "current"
                    : "pending"}
              >
                <span aria-hidden="true">{complete ? "✓" : index + 1}</span>
                {t(installPhaseKey(installPhase))}
              </li>
            );
          })}
        </ol>

        {snapshot?.message ? <p className="desktop-installer-message">{snapshot.message}</p> : null}
        {snapshot?.targetRoot ? (
          <p className="desktop-installer-target">
            {t("desktop.target")}: <code>{snapshot.targetRoot}</code>
          </p>
        ) : null}
        </div>
      ) : null}

      {phase === "waitingForRestart" ? (
        <Alert tone="warning" title={t("desktop.restartRequired")}>
          {t("desktop.restartRequiredHint")}
        </Alert>
      ) : null}
      {!releaseManifestUrlAvailable && phase !== "completed" ? (
        <Alert tone="warning" title={t("desktop.runtimeReleaseUnavailable")}>
          {t("desktop.runtimeReleaseUnavailableHint")}
        </Alert>
      ) : null}
      {phase === "completed" ? (
        <Alert tone="success" title={t("desktop.installCompleted")}>
          {t("desktop.installCompletedHint")}
        </Alert>
      ) : null}
      {snapshot?.error ? (
        <Alert tone="warning" title={t("desktop.installFailed")}>
          <p><code>{snapshot.error.code}</code>: {snapshot.error.message}</p>
          <p>
            {snapshot.error.retryable || snapshot.resumable
              ? t("desktop.retryAvailable")
              : t("desktop.retryUnavailable")}
          </p>
        </Alert>
      ) : null}
      {commandError ? (
        <Alert tone="warning" title={t("desktop.installCommandFailed")}>
          <code>{commandError}</code>
        </Alert>
      ) : null}

      <div className="desktop-install-actions">
        {active ? (
          <button
            type="button"
            className="btn"
            disabled={commandBusy}
            onClick={onCancel}
          >
            {commandBusy
              ? t(launcherMode ? "launcher.pausing" : "desktop.cancelling")
              : t(launcherMode ? "launcher.pause" : "desktop.cancelInstall")}
          </button>
        ) : receiptCleanupPending ? (
          <>
            <button
              type="button"
              className="btn btn-primary"
              disabled={automaticDiscardBusy}
              onClick={onDiscardAutomatic}
            >
              {automaticDiscardBusy
                ? t("desktop.clearingTerminalInstallerRequest")
                : t("desktop.clearTerminalInstallerRequest")}
            </button>
            <span className="desktop-resume-hint">
              {t(receiptCleanupInstalled
                ? "desktop.receiptCleanupInstalledHint"
                : "desktop.receiptCleanupPendingHint")}
            </span>
          </>
        ) : phase === "waitingForRestart" ? (
          <>
            {restartContinuationPending ? (
              <button
                type="button"
                className="btn"
                disabled={automaticDiscardBusy}
                onClick={onDiscardAutomatic}
              >
                {automaticDiscardBusy
                  ? t("desktop.cancellingRestartContinuation")
                  : t("desktop.cancelRestartContinuation")}
              </button>
            ) : null}
            <span className="desktop-resume-hint">
              {t(restartContinuationPending
                ? "desktop.restartContinuationAutomaticHint"
                : "desktop.restartContinuationManualHint")}
            </span>
          </>
        ) : automaticStartPending ? (
          <>
            <button
              type="button"
              className="btn"
              disabled={automaticDiscardBusy}
              onClick={onDiscardAutomatic}
            >
              {automaticDiscardBusy
                ? t("desktop.cancellingAutomaticInstall")
                : t("desktop.cancelAutomaticInstall")}
            </button>
            <span className="desktop-resume-hint">
              {t(automaticStartUncertain
                ? "desktop.autoStartUncertainHint"
                : automaticStartNeedsFailClosedValidation
                  ? "desktop.autoStartFailClosedHint"
                  : "desktop.autoStartPendingHint")}
            </span>
          </>
        ) : phase === "completed" ? (
          <Link to={launcherMode ? "/dashboard" : "/jobs/new"} className="btn btn-primary">
            {launcherMode ? t("launcher.openWorkspace") : t("desktop.continue")}
          </Link>
        ) : phase !== "failed" || canRetry ? (
          <button
            type="button"
            className="btn btn-primary"
            disabled={commandBusy || !canInstall}
            onClick={onStart}
          >
            {commandBusy ? t("desktop.startingInstall") : startLabel}
          </button>
        ) : null}
        {snapshot?.resumable && phase !== "completed" ? (
          <span className="desktop-resume-hint">{t("desktop.resumeHint")}</span>
        ) : null}
      </div>
    </SectionCard>
  );
}

const INSTALL_PHASE_KEYS: Record<RuntimeInstallPhase, TranslationKey> = {
  idle: "desktop.installPhase.idle",
  queued: "desktop.installPhase.queued",
  verifyingManifest: "desktop.installPhase.verifyingManifest",
  downloading: "desktop.installPhase.downloading",
  verifyingArchive: "desktop.installPhase.verifyingArchive",
  importing: "desktop.installPhase.importing",
  starting: "desktop.installPhase.starting",
  healthChecking: "desktop.installPhase.healthChecking",
  waitingForRestart: "desktop.installPhase.waitingForRestart",
  completed: "desktop.installPhase.completed",
  failed: "desktop.installPhase.failed",
  cancelled: "desktop.installPhase.cancelled",
};

function installPhaseKey(phase: RuntimeInstallPhase): TranslationKey {
  return INSTALL_PHASE_KEYS[phase];
}

function PlanFact({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <span>{label}</span>
      {mono ? <code>{value}</code> : <strong>{value}</strong>}
    </div>
  );
}

function componentStateKey(state: RuntimeComponentState): TranslationKey {
  return `desktop.component.${state}`;
}

const COMPONENT_LABEL_KEYS: Partial<Record<string, TranslationKey>> = {
  "wsl-runtime": "desktop.componentLabel.wslRuntime",
  "host-ownership": "desktop.componentLabel.hostOwnership",
  "runtime-manifest": "desktop.componentLabel.manifest",
  "local-backend": "desktop.componentLabel.backend",
  px4: "desktop.componentLabel.px4",
  gazebo: "desktop.componentLabel.gazebo",
};

function translatedComponentLabel(
  t: (key: TranslationKey) => string,
  id: string,
  fallback: string,
): string {
  const key = COMPONENT_LABEL_KEYS[id];
  return key ? t(key) : fallback;
}

const STEP_TEXT_KEYS: Partial<
  Record<string, { title: TranslationKey; description: TranslationKey }>
> = {
  preflight: {
    title: "desktop.step.preflight.title",
    description: "desktop.step.preflight.description",
  },
  "enable-wsl": {
    title: "desktop.step.enableWsl.title",
    description: "desktop.step.enableWsl.description",
  },
  download: {
    title: "desktop.step.download.title",
    description: "desktop.step.download.description",
  },
  import: {
    title: "desktop.step.import.title",
    description: "desktop.step.import.description",
  },
  "smoke-test": {
    title: "desktop.step.smokeTest.title",
    description: "desktop.step.smokeTest.description",
  },
};

function translatedStepText(
  t: (key: TranslationKey) => string,
  id: string,
  field: "title" | "description",
  fallback: string,
): string {
  const key = STEP_TEXT_KEYS[id]?.[field];
  return key ? t(key) : fallback;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  try {
    const serialized = JSON.stringify(error);
    if (serialized) return serialized;
  } catch {
    // Fall through to a side-effect-free string conversion for circular values.
  }
  try {
    return String(error);
  } catch {
    return "Unknown desktop command error";
  }
}
