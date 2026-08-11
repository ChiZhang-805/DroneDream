import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { apiClient } from "../api/client";
import { editionLandingPath } from "../edition";
import { Alert } from "../components/Alert";
import { Loading } from "../components/States";
import { SectionCard } from "../components/SectionCard";
import { DistributionSetupPanel } from "../components/DistributionSetupPanel";
import {
  autoStartInstallerRuntime,
  beginBrowserAuth,
  clearBrowserAuthVault,
  restoreBrowserAuthVault,
  cancelBrowserAuth,
  cancelRuntimeInstall,
  discardInstallerRuntimeIntent,
  getInstallerRuntimeIntent,
  getRuntimeInstallProgress,
  getRuntimeInstallPlan,
  isDesktopRuntime,
  probeRuntimeStatus,
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
import { useOptionalAuth } from "../features/auth/AuthContext";
import { activateDesktopAuthSession } from "../features/auth/desktopAuthActivation";
import { adoptBrowserAuthSession } from "../features/auth/browserAuth";
import { browserAuthConfiguration } from "../features/auth/supabaseClient";
import { probeSystemPrerequisitesWithStartupGrace } from "../desktop/prerequisiteProbe";
import {
  isOverallDesktopReady,
  isRuntimeConfirmedMissing,
  isRuntimeFullyReady,
  MINIMUM_MEMORY_BYTES,
} from "../desktop/readiness";
import { useLauncherProgress } from "../desktop/launcherProgress";
import {
  runtimeSessionContractFailure,
  verifyRuntimeSessionContract,
} from "../desktop/runtimeSessionContract";
import {
  getDesktopStartupGateSession,
  setDesktopStartupGateState,
  subscribeDesktopStartupGate,
  verifyDesktopStartupGate,
} from "../desktop/startupGate";
import { useAppUpdaterState } from "../desktop/updaterContext";
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

interface LauncherFailureCopy {
  titleKey: TranslationKey;
  hintKey: TranslationKey;
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

function runtimeInstallPercent(
  downloaded: number,
  total: number | null,
): number | null {
  if (
    total === null ||
    !Number.isFinite(total) ||
    total <= 0 ||
    !Number.isFinite(downloaded)
  ) return null;
  return Math.max(0, Math.min(100, Math.round((downloaded / total) * 100)));
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

function runtimeHealthFailureCopy(code: string | undefined): LauncherFailureCopy | null {
  switch (code) {
    case "runtime_service_unhealthy":
      return {
        titleKey: "launcher.error.runtimeServiceTitle",
        hintKey: "launcher.error.runtimeServiceHint",
      };
    case "runtime_host_connectivity":
      return {
        titleKey: "launcher.error.hostConnectivityTitle",
        hintKey: "launcher.error.hostConnectivityHint",
      };
    case "runtime_health_unknown":
      return {
        titleKey: "launcher.error.healthUnknownTitle",
        hintKey: "launcher.error.healthUnknownHint",
      };
    default:
      return null;
  }
}

export function DesktopSetup() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const auth = useOptionalAuth();
  const updater = useAppUpdaterState();
  const startupGate = useSyncExternalStore(
    subscribeDesktopStartupGate,
    getDesktopStartupGateSession,
    getDesktopStartupGateSession,
  );
  const [searchParams] = useSearchParams();
  const runtimeAccess = useDesktopRuntimeAccess();
  const { refresh: refreshRuntimeAccess } = runtimeAccess;
  const desktopAvailable = isDesktopRuntime();
  const requestId = useRef(0);
  const installerIntentPromise = useRef<Promise<InstallerRuntimeIntent> | null>(null);
  const installerAutoStartPromise = useRef<
    Promise<InstallerRuntimeAutoStartResult> | null
  >(null);
  const installerDiscardRequested = useRef(false);
  const installerDiscardSucceeded = useRef(false);
  const componentMounted = useRef(false);
  const browserAuthActive = useRef(false);
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
  const [selectedDrive, setSelectedDrive] = useState("");
  const [installerAttempt, setInstallerAttempt] = useState(0);
  const [dismissedLauncherError, setDismissedLauncherError] = useState("");
  const [launcherErrorExpanded, setLauncherErrorExpanded] = useState(false);
  const [browserAuthStatus, setBrowserAuthStatus] = useState<
    "idle" | "waiting" | "adopting"
  >("idle");
  const [browserAuthCompletedForLaunch, setBrowserAuthCompletedForLaunch] =
    useState(false);
  const [browserAuthError, setBrowserAuthError] = useState<string | null>(null);
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
    installActive;
  const showInstallPlanner =
    state.prerequisitesFresh &&
    state.runtimeFresh &&
    isRuntimeConfirmedMissing(state.runtime);
  const localRuntimeReady =
    state.prerequisitesFresh &&
    state.runtimeFresh &&
    isOverallDesktopReady(state.prerequisites, state.runtime);
  const runtimeSessionFailure = runtimeSessionContractFailure(state.runtime);
  const runtimeSessionFailureKey: TranslationKey | null =
    runtimeSessionFailure === "runtime_session_api_missing"
      ? "launcher.runtimeSessionApiMissing"
      : runtimeSessionFailure === "runtime_session_api_unavailable"
        ? "launcher.runtimeSessionApiUnavailable"
        : null;
  const signedInAccount =
    auth?.configured && !auth.loading ? auth.account : null;
  const startupGateReady =
    !desktopAvailable ||
    (browserAuthCompletedForLaunch &&
      startupGate.status === "ready" &&
      Boolean(signedInAccount) &&
      startupGate.accountId === signedInAccount?.id);
  const updaterBusy =
    updater.status === "checking" ||
    updater.status === "downloading" ||
    updater.status === "installing" ||
    updater.status === "reconcilingEngine";
  const updaterBlocksWorkspace =
    updaterBusy ||
    updater.status === "available" ||
    updater.status === "engineError" ||
    updater.status === "runtimeBaseRequired";
  const localChecksReady =
    localRuntimeReady &&
    !state.loading &&
    !installerHandoffState.checking &&
    (!runtimeAccess.desktopRuntime ||
      (runtimeAccess.status === "ready" && !runtimeAccess.isChecking));
  const workspaceReady =
    localChecksReady &&
    browserAuthCompletedForLaunch &&
    Boolean(signedInAccount) &&
    startupGateReady &&
    !updaterBlocksWorkspace;
  const environmentChecking =
    state.loading ||
    installerHandoffState.checking ||
    runtimeAccess.isChecking ||
    runtimeAccess.status === "checking" ||
    runtimeAccess.status === "starting";
  const accountVerificationInProgress =
    browserAuthCompletedForLaunch &&
    Boolean(
      (auth?.configured && auth.loading) ||
      startupGate.status === "checking",
    );
  const postSignInBlocked =
    browserAuthCompletedForLaunch && startupGate.status === "blocked";
  const startupGateFailureKey: TranslationKey =
    startupGate.failureCode === "runtimeSessionApiMissing"
      ? "launcher.runtimeSessionApiMissing"
      : startupGate.failureCode === "accountIdentityMismatch"
        ? "launcher.accountIdentityMismatch"
        : "launcher.accountVerificationFailed";
  const environmentBlocked =
    localRuntimeReady && !localChecksReady && !environmentChecking;
  const launcherProgress = useLauncherProgress({
    enabled: Boolean(
      desktopAvailable &&
      state.runtimeFresh &&
      state.runtime?.installed,
    ),
    complete: localChecksReady && !updaterBlocksWorkspace,
    blocked: Boolean(
      runtimeSessionFailure ||
      (state.runtimeFresh && state.runtime?.installed && !environmentChecking &&
        !localRuntimeReady && runtimeAccess.status !== "starting"),
    ),
  });
  const launcherEnvironmentReady =
    localChecksReady && launcherProgress === 100;
  const installerHandoffNeedsAttention = Boolean(
    installerHandoffState.commandError ||
    installerHandoffState.autoStartUncertain ||
    installerHandoffState.result?.disposition === "invalid" ||
    installerHandoffState.intent?.status === "invalid" ||
    (installerHandoffState.discardResult &&
      !installerHandoffState.discardResult.discarded),
  );
  const launcherErrorDetails = [
    ...state.issues.map((issue) => `${issue.command}: ${issue.message}`),
    installState.commandError,
    installState.snapshot?.error
      ? `${installState.snapshot.error.code}: ${installState.snapshot.error.message}`
      : null,
    installerHandoffState.commandError,
    installerHandoffState.result?.disposition === "invalid"
      ? installerHandoffState.result.message ?? t("desktop.installerChoiceInvalidHint")
      : null,
    installerHandoffState.intent?.status === "invalid"
      ? installerHandoffState.intent.message ?? t("desktop.installerChoiceInvalidHint")
      : null,
    state.plan && (!state.plan.canInstall || state.plan.blockers.length > 0)
      ? state.plan.blockers.join("\n") || t("desktop.planBlocked")
      : null,
    showInstallPlanner &&
      !state.planLoading &&
      state.prerequisites &&
      fixedDiskOptions(state.prerequisites.disks).length === 0
      ? t("desktop.storageNoDisk")
      : null,
    state.runtimeFresh &&
      state.runtime?.installed &&
      state.runtime.running &&
      !isRuntimeFullyReady(state.runtime)
      ? runtimeSessionFailureKey
        ? t(runtimeSessionFailureKey)
        : state.runtime.diagnostics.join("\n") || t("desktop.runtimeNeedsRepair")
      : null,
    runtimeAccess.status === "startFailed"
      ? `${t("runtimeGate.startFailedTitle")}: ${t("runtimeGate.startFailedBody")}`
      : null,
    installState.snapshot?.phase === "completed" &&
      state.prerequisitesFresh &&
      state.runtimeFresh &&
      !localRuntimeReady
      ? t("desktop.installCompletionUnconfirmed")
      : null,
  ].filter((detail): detail is string => Boolean(detail));
  const runtimeInstallError = installState.snapshot?.error ?? null;
  const runtimeHealthCopy = runtimeHealthFailureCopy(runtimeInstallError?.code);
  const launcherErrorFingerprint = [
    ...launcherErrorDetails,
    runtimeInstallError?.diagnosticsPath,
  ].filter((detail): detail is string => Boolean(detail)).join("\n");
  const launcherErrorVisible = launcherErrorFingerprint.length > 0 &&
    dismissedLauncherError !== launcherErrorFingerprint;
  const requestedFeature = searchParams.get("required");
  const requestedFeatureLabel = requestedFeature === "experiment"
    ? t("runtimeGate.featureExperiment")
    : requestedFeature === "job"
      ? t("runtimeGate.featureJob")
      : null;

  useEffect(() => {
    componentMounted.current = true;
    return () => {
      componentMounted.current = false;
      if (browserAuthActive.current) {
        void cancelBrowserAuth().catch(() => undefined);
      }
    };
  }, []);

  useEffect(() => {
    if (!desktopAvailable || !runtimeAccess.snapshot) return;
    let disposed = false;
    const snapshot = runtimeAccess.snapshot;
    void verifyRuntimeSessionContract(snapshot.runtime).then((runtime) => {
      if (disposed) return;
      setState((current) => ({
        ...current,
        prerequisites: snapshot.prerequisites,
        runtime,
        prerequisitesFresh: true,
        runtimeFresh: true,
        loading: false,
        issues: replaceIssues(current.issues, ["prerequisites", "runtime"], []),
      }));
    }).catch((error) => {
      if (disposed) return;
      setState((current) => ({
        ...current,
        issues: replaceIssues(current.issues, ["runtime"], [
          probeIssue("runtime", "verify_runtime_session_contract", error),
        ]),
      }));
    });
    return () => {
      disposed = true;
    };
  }, [desktopAvailable, runtimeAccess.snapshot]);

  useEffect(() => {
    if (!desktopAvailable) return;
    // Account state is deliberately a second stage. It must never participate
    // in the environment percentage or run before the user selects the single
    // browser sign-in action shown at 100%.
    if (!localChecksReady || !browserAuthCompletedForLaunch) return;
    if (
      updater.status === "checking" ||
      updater.status === "downloading" ||
      updater.status === "installing" ||
      updater.status === "reconcilingEngine"
    ) {
      setDesktopStartupGateState("checking", {
        accountId: signedInAccount?.id ?? null,
      });
      return;
    }
    if (
      updater.status === "available" ||
      updater.status === "engineError" ||
      updater.status === "runtimeBaseRequired"
    ) {
      setDesktopStartupGateState("blocked", {
        accountId: signedInAccount?.id ?? null,
        error: updater.error ??
          `DroneDream ${updater.availableVersion ?? "update"} must be installed before entering the tuning workspace.`,
        failureCode: "updateRequired",
      });
      return;
    }
    if (!signedInAccount) return;
    void verifyDesktopStartupGate(
      signedInAccount.id,
      () => apiClient.verifyAuthenticatedSession(),
    );
  }, [
    browserAuthCompletedForLaunch,
    desktopAvailable,
    localChecksReady,
    signedInAccount,
    updater.availableVersion,
    updater.error,
    updater.status,
  ]);

  useEffect(() => {
    if (
      workspaceReady &&
      auth?.configured &&
      auth.account &&
      browserAuthStatus === "idle"
    ) {
      navigate(editionLandingPath(), { replace: true });
    }
  }, [
    auth?.account,
    auth?.configured,
    browserAuthStatus,
    navigate,
    workspaceReady,
  ]);

  const startBrowserSignIn = useCallback(async () => {
    if (!launcherEnvironmentReady || browserAuthStatus !== "idle") return;
    const configuration = browserAuthConfiguration();
    if (!configuration) {
      setBrowserAuthError(t("launcher.browserAuthNotConfigured"));
      return;
    }
    setBrowserAuthError(null);
    activateDesktopAuthSession();
    setBrowserAuthCompletedForLaunch(false);
    setDesktopStartupGateState("idle");
    setBrowserAuthStatus("waiting");
    browserAuthActive.current = true;
    let sessionIssued = false;
    try {
      const session = await restoreBrowserAuthVault() ?? await beginBrowserAuth({ locale });
      sessionIssued = true;
      if (!componentMounted.current) return;
      setBrowserAuthStatus("adopting");
      await adoptBrowserAuthSession(session);
      if (componentMounted.current) {
        setBrowserAuthCompletedForLaunch(true);
        setBrowserAuthStatus("idle");
      }
    } catch (error) {
      if (sessionIssued) {
        // Native persists only this edition's refresh grant before returning
        // the session. If the WebView refuses that session, do not leave a
        // credential that would be retried on the next explicit sign-in.
        await clearBrowserAuthVault().catch(() => false);
      }
      if (!componentMounted.current) return;
      setBrowserAuthStatus("idle");
      const message = error instanceof Error ? error.message : String(error);
      if (!/cancelled/iu.test(message)) {
        setBrowserAuthError(t("launcher.browserAuthFailed"));
      }
    } finally {
      browserAuthActive.current = false;
    }
  }, [browserAuthStatus, launcherEnvironmentReady, locale, t]);

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
      probeSystemPrerequisitesWithStartupGrace(),
      probeRuntimeStatus().then(verifyRuntimeSessionContract),
    ]);
    if (requestId.current !== currentRequest) return;

    // Keep the navigation/action gate in sync after every setup-page check.
    // The access provider coordinates exactly one automatic Runtime start;
    // stale local reports are never promoted into global readiness.
    void refreshRuntimeAccess({ autoStart: true });

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
          environmentProgress={launcherProgress}
          localReady={localChecksReady}
          ready={workspaceReady}
          checking={environmentChecking}
          gateBlocked={
            environmentBlocked ||
            runtimeSessionFailure !== null ||
            (localChecksReady &&
              (postSignInBlocked || updaterBlocksWorkspace))
          }
          accountRequired={
            launcherEnvironmentReady &&
            !workspaceReady &&
            !postSignInBlocked &&
            !updaterBlocksWorkspace
          }
          automaticStartPending={automaticStartPending}
          commandBusy={installState.commandBusy}
        />

        {postSignInBlocked &&
        !updaterBlocksWorkspace ? (
          <Alert tone="warning" title={t("launcher.accountVerificationBlocked")}>
            <p>{t(startupGateFailureKey)}</p>
          </Alert>
        ) : null}

        {runtimeSessionFailureKey ? (
          <Alert tone="warning" title={t("launcher.runtimeSessionApiTitle")}>
            <p>{t(runtimeSessionFailureKey)}</p>
          </Alert>
        ) : null}

        {updater.status === "available" ? (
          <div className="launcher-ready-actions">
            <button
              type="button"
              className="btn btn-primary launcher-primary-action"
              onClick={() => void updater.installAvailableUpdate()}
            >
              {updater.error
                ? t("updater.sidebarDeferred")
                : t("updater.available", {
                    version: updater.availableVersion ?? "",
                  })}
            </button>
          </div>
        ) : updater.status === "engineError" ? (
          <div className="launcher-ready-actions">
            <button
              type="button"
              className="btn btn-primary launcher-primary-action"
              onClick={() => void updater.reconcileEnginePack()}
            >
              {t("updater.sidebarRetry")}
            </button>
          </div>
        ) : updater.status === "runtimeBaseRequired" ? (
          <Alert tone="warning" title={t("launcher.runtimeSessionApiTitle")}>
            <p>{t("updater.runtimeBaseRequired")}</p>
          </Alert>
        ) : runtimeSessionFailureKey ? (
          <div className="launcher-ready-actions">
            <button
              type="button"
              className="btn btn-primary launcher-primary-action"
              onClick={() => void refresh()}
            >
              {t("launcher.retryChecks")}
            </button>
          </div>
        ) : launcherEnvironmentReady && !workspaceReady ? (
          <div className="launcher-ready-actions">
            <button
              type="button"
              className="btn btn-primary launcher-primary-action"
              disabled={
                browserAuthStatus !== "idle" ||
                accountVerificationInProgress
              }
              onClick={() => void startBrowserSignIn()}
            >
              {browserAuthStatus === "waiting"
                ? t("launcher.browserAuthWaiting")
                : browserAuthStatus === "adopting"
                  ? t("launcher.browserAuthAdopting")
                  : accountVerificationInProgress
                    ? t("launcher.browserAuthAdopting")
                  : t("launcher.signIn")}
            </button>
          </div>
        ) : workspaceReady ? null : localRuntimeReady &&
          (environmentChecking || !launcherEnvironmentReady) ? null : localRuntimeReady ? (
          <div className="launcher-ready-actions">
            <button
              type="button"
              className="btn btn-primary launcher-primary-action"
              onClick={() => void refreshRuntimeAccess()}
            >
              {t("launcher.retryChecks")}
            </button>
          </div>
        ) : (
          <>
            {installState.snapshot?.phase !== "completed" &&
            ((showInstallPlanner && state.plan) ||
              (installState.snapshot && installState.snapshot.phase !== "idle")) ? (
              !installActive ? (
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
              ) : null
            ) : null}
          </>
        )}

        {browserAuthError ? (
          <Alert tone="danger" title={t("launcher.browserAuthErrorTitle")}>
            <p>{browserAuthError}</p>
          </Alert>
        ) : null}

        {requestedFeatureLabel && !workspaceReady ? (
          <span className="sr-only">
            {t("runtimeGate.requestedFeature")}: {requestedFeatureLabel}
          </span>
        ) : null}

        <div hidden aria-hidden="true">
          {requestedFeatureLabel && !localRuntimeReady ? (
            <Alert tone="warning" title={t("runtimeGate.redirectTitle")}>
              <p>{t("runtimeGate.redirectBody")}</p>
              <p>{requestedFeatureLabel}</p>
            </Alert>
          ) : null}
          <InstallerHandoffNotice
            quietSuccess
            state={installerHandoffState}
            discardAvailable={installerHandoffDiscardAvailable}
            discardBusy={installerHandoffState.discarding}
            receiptCleanupRecovered={receiptCleanupRecovered}
            waitingForRestart={installState.snapshot?.phase === "waitingForRestart"}
            onRetry={retryInstallerHandoff}
            onDiscard={() => void discardAutomaticInstall()}
          />
          <ReadinessHero
            prerequisites={state.prerequisites}
            runtime={state.runtime}
            loading={state.loading}
            prerequisitesFresh={state.prerequisitesFresh}
            runtimeFresh={state.runtimeFresh}
          />
          {state.issues.length > 0 ? (
            <ul>
              {state.issues.map((issue) => (
                <li key={issue.source}>{issue.command}: {issue.message}</li>
              ))}
            </ul>
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
          {state.runtimeFresh && state.runtime?.installed ? (
            <InstalledRuntimeNotice report={state.runtime} />
          ) : null}
          {showInstallPlanner && state.plan ? (
            <InstallPlanOverview
              plan={state.plan}
              automaticInstallConfirmed={automaticStartScheduled}
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
              receiptCleanupInstalled={Boolean(installState.snapshot?.installedVersion)}
              restartContinuationPending={restartContinuationPending}
              releaseManifestUrlAvailable={releaseManifestUrl !== null || installerManagedInstall}
              onStart={() => void beginOrResumeInstall()}
              onCancel={() => void cancelInstall()}
              onDiscardAutomatic={() => void discardAutomaticInstall()}
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
        </div>

        {launcherErrorVisible ? (
          <LauncherErrorDialog
            title={t(runtimeHealthCopy?.titleKey ?? "launcher.errorTitle")}
            hint={t(runtimeHealthCopy?.hintKey ?? "launcher.errorHint")}
            details={launcherErrorDetails}
            diagnosticsPath={runtimeInstallError?.diagnosticsPath ?? null}
            expanded={launcherErrorExpanded}
            busy={busy}
            onToggleDetails={() => setLauncherErrorExpanded((current) => !current)}
            onRetry={() => {
              setLauncherErrorExpanded(false);
              setDismissedLauncherError("");
              if (installerHandoffNeedsAttention || automaticStartPending) {
                retryInstallerHandoff();
              } else {
                void refresh(
                  automaticStartPending
                    ? installerIntent?.targetRoot ?? undefined
                    : undefined,
                );
              }
            }}
            onCancelAutomatic={installerHandoffDiscardAvailable
              ? () => void discardAutomaticInstall()
              : undefined}
            onDismiss={() => {
              setLauncherErrorExpanded(false);
              setDismissedLauncherError(launcherErrorFingerprint);
            }}
          />
        ) : null}
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

      {!desktopAvailable ? <DistributionSetupPanel variant="setup" /> : null}

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
  quietSuccess = false,
  state,
  discardAvailable,
  discardBusy,
  receiptCleanupRecovered,
  waitingForRestart,
  onRetry,
  onDiscard,
}: {
  quietSuccess?: boolean;
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
    if (quietSuccess) {
      return <span className="sr-only">{t("desktop.installerChoiceChecking")}</span>;
    }
    return (
      <Alert tone="info" title={t("desktop.installerChoiceChecking")}>
        {t("desktop.installerChoiceCheckingHint")}
      </Alert>
    );
  }
  if (state.discardResult?.discarded) {
    if (quietSuccess) {
      return (
        <span className="sr-only">
          {t(receiptCleanupRecovered
            ? "desktop.receiptCleanupRecovered"
            : waitingForRestart
              ? "desktop.restartContinuationCancelled"
              : "desktop.autoInstallCancelled")}
        </span>
      );
    }
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
    if (quietSuccess) {
      return <span className="sr-only">{t("desktop.installerRuntimeAlreadyInstalled")}</span>;
    }
    return (
      <Alert tone="success" title={t("desktop.installerRuntimeAlreadyInstalled")}>
        {t("desktop.installerRuntimeAlreadyInstalledHint")}
      </Alert>
    );
  }
  if (result?.disposition === "resumed") {
    if (quietSuccess) {
      return <span className="sr-only">{t("desktop.autoInstallResumed")}</span>;
    }
    return (
      <Alert tone="success" title={t("desktop.autoInstallResumed")}>
        {t("desktop.autoInstallResumedHint")}
      </Alert>
    );
  }
  if (result?.disposition === "started") {
    if (quietSuccess) {
      return <span className="sr-only">{t("desktop.autoInstallStarted")}</span>;
    }
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
                <span>{translatedComponentDetail(t, component.detail) || component.version || "—"}</span>
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

function InstalledRuntimeNotice({ report }: { report: RuntimeStatusReport }) {
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

const LAUNCHER_STATUS_KEYS: Record<RuntimeInstallPhase, TranslationKey> = {
  idle: "launcher.status.idle",
  queued: "launcher.status.queued",
  verifyingManifest: "launcher.status.verifyingManifest",
  downloading: "launcher.status.downloading",
  verifyingArchive: "launcher.status.verifyingArchive",
  importing: "launcher.status.importing",
  waitingForRestart: "launcher.status.waitingForRestart",
  starting: "launcher.status.starting",
  healthChecking: "launcher.status.healthChecking",
  completed: "launcher.status.ready",
  failed: "launcher.status.failed",
  cancelled: "launcher.status.cancelled",
};

function RuntimeLauncherHero({
  snapshot,
  environmentProgress,
  localReady,
  ready,
  checking,
  gateBlocked,
  accountRequired,
  automaticStartPending,
  commandBusy,
}: {
  snapshot: RuntimeInstallSnapshot | null;
  environmentProgress: number;
  localReady: boolean;
  ready: boolean;
  checking: boolean;
  gateBlocked: boolean;
  accountRequired: boolean;
  automaticStartPending: boolean;
  commandBusy: boolean;
}) {
  const { t } = useI18n();
  const phase = snapshot?.phase ?? "idle";
  const active = isActiveInstall(snapshot);
  const total = snapshot?.bytesTotal ?? null;
  const downloaded = snapshot?.bytesDownloaded ?? 0;
  const measuredPercent = runtimeInstallPercent(downloaded, total);
  const percent = active
    ? Math.max(1, Math.min(measuredPercent ?? 1, 96))
    : environmentProgress;
  const status = ready
    ? t("launcher.status.ready")
    : commandBusy && active
      ? t("launcher.status.pausing")
      : commandBusy
        ? t("launcher.status.queued")
      : gateBlocked
        ? t("launcher.status.blocked")
      : accountRequired
        ? t("launcher.status.signIn")
      : localReady && environmentProgress < 100
        ? t("launcher.status.checking")
      : phase === "completed"
        ? t("launcher.status.healthChecking")
      : (checking || automaticStartPending) && phase === "idle"
        ? t("launcher.status.checking")
        : t(LAUNCHER_STATUS_KEYS[phase]);

  return (
    <div className={`launcher-hero launcher-hero-${localReady ? "ready" : phase}`}>
      <div className="launcher-hero-visual">
        <Suspense fallback={<DroneSceneLoadingFallback />}>
          <DroneLaunchScene active={active || localReady} progress={percent} />
        </Suspense>
      </div>

      <div className="launcher-progress-panel" role="status" aria-live="polite">
        <div
          className={`launcher-progress-track${percent === null && (active || checking) ? " indeterminate" : ""}`}
          role="progressbar"
          aria-label={t("launcher.progressLabel")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent ?? undefined}
        >
          <span style={{ width: `${percent ?? 0}%` }} />
        </div>
        <div className="launcher-progress-footer">
          <strong className="launcher-compact-status">{status}</strong>
          <span className="launcher-progress-percent">
            {percent === null ? "" : `${percent}%`}
          </span>
        </div>
      </div>
    </div>
  );
}

function LauncherErrorDialog({
  title,
  hint,
  details,
  diagnosticsPath,
  expanded,
  busy,
  onToggleDetails,
  onRetry,
  onCancelAutomatic,
  onDismiss,
}: {
  title: string;
  hint: string;
  details: string[];
  diagnosticsPath: string | null;
  expanded: boolean;
  busy: boolean;
  onToggleDetails: () => void;
  onRetry: () => void;
  onCancelAutomatic?: () => void;
  onDismiss: () => void;
}) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLElement>(null);
  const onDismissRef = useRef(onDismiss);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");

  useEffect(() => {
    onDismissRef.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    setCopyStatus("idle");
  }, [diagnosticsPath]);

  const copyDiagnosticsPath = useCallback(async () => {
    if (!diagnosticsPath) return;
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API unavailable");
      }
      await navigator.clipboard.writeText(diagnosticsPath);
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  }, [diagnosticsPath]);

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const focusFrame = requestAnimationFrame(() => {
      dialogRef.current?.querySelector<HTMLElement>("button:not(:disabled)")?.focus();
    });
    const handleKeyDown = (event: KeyboardEvent) => {
      const dialog = dialogRef.current;
      if (!dialog) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onDismissRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [...dialog.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), '
          + 'textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => !element.hasAttribute("hidden"));
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleKeyDown);
      if (previouslyFocused?.isConnected) previouslyFocused.focus();
    };
  }, []);

  return (
    <div className="launcher-error-backdrop" role="presentation">
      <section
        ref={dialogRef}
        className="launcher-error-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="launcher-error-title"
      >
        <div className="launcher-error-symbol" aria-hidden="true">!</div>
        <h2 id="launcher-error-title">{title}</h2>
        <p>{hint}</p>
        {diagnosticsPath ? (
          <div className="launcher-error-log-path">
            <span>{t("launcher.diagnosticsPath")}</span>
            <code>{diagnosticsPath}</code>
            <button
              type="button"
              className="btn"
              onClick={() => void copyDiagnosticsPath()}
            >
              {t("launcher.copyDiagnosticsPath")}
            </button>
            <span className="launcher-copy-status" role="status" aria-live="polite">
              {copyStatus === "copied"
                ? t("launcher.diagnosticsPathCopied")
                : copyStatus === "failed"
                  ? t("launcher.diagnosticsPathCopyFailed")
                  : ""}
            </span>
          </div>
        ) : null}
        {expanded ? (
          <pre className="launcher-error-details">{details.join("\n\n")}</pre>
        ) : null}
        <div className="launcher-error-actions">
          <button type="button" className="btn" onClick={onToggleDetails}>
            {expanded ? t("launcher.hideErrorDetails") : t("launcher.showErrorDetails")}
          </button>
          <button type="button" className="btn" onClick={onDismiss}>
            {t("launcher.dismissError")}
          </button>
          {onCancelAutomatic ? (
            <button type="button" className="btn" onClick={onCancelAutomatic}>
              {t("desktop.cancelAutomaticInstall")}
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={onRetry}
          >
            {busy ? t("desktop.checking") : t("launcher.retryError")}
          </button>
        </div>
      </section>
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
  const percent = runtimeInstallPercent(downloaded, total);
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

      {!launcherMode ? (
        <>
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
        </>
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
          <Link to={launcherMode ? editionLandingPath() : "/jobs/new"} className="btn btn-primary">
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
  "account-session-api": "desktop.componentLabel.accountSessionApi",
};

const COMPONENT_DETAIL_KEYS: Partial<Record<string, TranslationKey>> = {
  runtime_session_api_ready: "desktop.componentDetail.accountSessionApiReady",
  runtime_session_api_missing: "launcher.runtimeSessionApiMissing",
  runtime_session_api_unavailable: "launcher.runtimeSessionApiUnavailable",
};

function translatedComponentLabel(
  t: (key: TranslationKey) => string,
  id: string,
  fallback: string,
): string {
  const key = COMPONENT_LABEL_KEYS[id];
  return key ? t(key) : fallback;
}

function translatedComponentDetail(
  t: (key: TranslationKey) => string,
  detail: string | null | undefined,
): string | null | undefined {
  if (!detail) return detail;
  const key = COMPONENT_DETAIL_KEYS[detail];
  return key ? t(key) : detail;
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
