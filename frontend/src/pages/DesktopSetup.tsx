import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Alert } from "../components/Alert";
import { Loading } from "../components/States";
import { SectionCard } from "../components/SectionCard";
import {
  cancelRuntimeInstall,
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
  RuntimeComponentState,
  RuntimeInstallPhase,
  RuntimeInstallPlan,
  RuntimeInstallSnapshot,
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "../desktop/bridge";
import { formatBytes } from "../desktop/format";
import {
  isOverallDesktopReady,
  isRuntimeConfirmedMissing,
  isRuntimeFullyReady,
  MINIMUM_MEMORY_BYTES,
} from "../desktop/readiness";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";

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

async function getSettledInstallPlan(drive: string) {
  try {
    return {
      status: "fulfilled" as const,
      value: await getRuntimeInstallPlan(runtimeTargetRoot(drive)),
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
  const desktopAvailable = isDesktopRuntime();
  const requestId = useRef(0);
  const selectedDriveRef = useRef("");
  const [state, setState] = useState<ProbeState>(() => ({
    ...INITIAL_STATE,
    loading: desktopAvailable,
  }));
  const [installState, setInstallState] = useState<InstallState>(
    INITIAL_INSTALL_STATE,
  );
  const [runtimeCommandError, setRuntimeCommandError] = useState<string | null>(null);
  const [runtimeCommandBusy, setRuntimeCommandBusy] = useState(false);
  const [selectedDrive, setSelectedDrive] = useState("");
  const releaseManifestUrl = configuredRuntimeReleaseManifestUrl();
  const installActive = isActiveInstall(installState.snapshot);
  const busy =
    state.loading ||
    state.planLoading ||
    installState.commandBusy ||
    runtimeCommandBusy ||
    installActive;
  const showInstallPlanner =
    state.prerequisitesFresh &&
    state.runtimeFresh &&
    isRuntimeConfirmedMissing(state.runtime);

  const refresh = useCallback(async () => {
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
    if (prerequisites.status === "fulfilled") {
      selectedDriveRef.current = nextDrive;
      setSelectedDrive(nextDrive);
    }
    const shouldRequestPlan =
      prerequisites.status === "fulfilled" &&
      runtime.status === "fulfilled" &&
      isRuntimeConfirmedMissing(runtime.value) &&
      fixedDisks.length > 0;

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

    const plan = await getSettledInstallPlan(nextDrive);
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
  }, [desktopAvailable]);

  const selectRuntimeDrive = useCallback(async (drive: string) => {
    if (
      !desktopAvailable ||
      !state.prerequisitesFresh ||
      !state.runtimeFresh ||
      state.runtime?.installed !== false
    ) return;
    const fixedDisks = fixedDiskOptions(state.prerequisites?.disks ?? []);
    if (!fixedDisks.some((disk) => disk.drive === drive)) return;

    const currentRequest = ++requestId.current;
    selectedDriveRef.current = drive;
    setSelectedDrive(drive);
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
    state.prerequisites,
    state.prerequisitesFresh,
    state.runtime,
    state.runtimeFresh,
  ]);

  const beginOrResumeInstall = useCallback(async () => {
    const targetRoot = installState.snapshot?.targetRoot ?? state.plan?.targetRoot;
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
    void refresh();
    return () => {
      requestId.current += 1;
    };
  }, [refresh]);

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
            onClick={() => void refresh()}
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
              disabled={busy}
              onChange={(drive) => void selectRuntimeDrive(drive)}
            />
          ) : null}
          {showInstallPlanner && state.planLoading ? (
            <Loading label={t("desktop.planUpdating")} />
          ) : null}
          {showInstallPlanner && state.plan ? (
            <InstallPlanOverview plan={state.plan} />
          ) : null}
          {showInstallPlanner && (state.plan || installState.snapshot) ? (
            <RuntimeInstallControls
              plan={state.plan}
              snapshot={installState.snapshot}
              commandError={installState.commandError}
              commandBusy={installState.commandBusy}
              releaseManifestUrlAvailable={releaseManifestUrl !== null}
              onStart={() => void beginOrResumeInstall()}
              onCancel={() => void cancelInstall()}
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

function InstallPlanOverview({ plan }: { plan: RuntimeInstallPlan }) {
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
        {t("desktop.noChanges")}
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

const INSTALL_PROGRESS_PHASES: RuntimeInstallPhase[] = [
  "verifyingManifest",
  "downloading",
  "verifyingArchive",
  "importing",
  "starting",
  "healthChecking",
];

function RuntimeInstallControls({
  plan,
  snapshot,
  commandError,
  commandBusy,
  releaseManifestUrlAvailable,
  onStart,
  onCancel,
}: {
  plan: RuntimeInstallPlan | null;
  snapshot: RuntimeInstallSnapshot | null;
  commandError: string | null;
  commandBusy: boolean;
  releaseManifestUrlAvailable: boolean;
  onStart: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const phase = snapshot?.phase ?? "idle";
  const active = isActiveInstall(snapshot);
  const canInstall = Boolean(
    plan?.canInstall &&
    plan.blockers.length === 0 &&
    releaseManifestUrlAvailable,
  );
  const canRetry =
    phase !== "failed" ||
    Boolean(snapshot?.resumable || snapshot?.error?.retryable);
  const total = snapshot?.bytesTotal ?? null;
  const downloaded = snapshot?.bytesDownloaded ?? 0;
  const percent = total && total > 0
    ? Math.min(100, Math.round((downloaded / total) * 100))
    : null;
  const currentProgressIndex = INSTALL_PROGRESS_PHASES.indexOf(phase);

  let startLabel = t("desktop.installNow");
  if (phase === "failed") startLabel = t("desktop.retryInstall");
  if (phase === "cancelled") startLabel = t("desktop.resumeInstall");
  if (phase === "waitingForRestart") startLabel = t("desktop.continueInstall");

  return (
    <SectionCard
      title={t("desktop.installerTitle")}
      description={t("desktop.installerDesc")}
      actions={snapshot?.installedVersion ? (
        <span className="desktop-runtime-pill ready">
          {snapshot.installedVersion}
        </span>
      ) : null}
    >
      <div
        className={`desktop-installer-status desktop-installer-${phase}`}
        role="status"
        aria-live="polite"
        aria-busy={active || commandBusy}
      >
        <div className="desktop-installer-heading">
          <div>
            <span>{t("desktop.currentStage")}</span>
            <strong>{t(installPhaseKey(phase))}</strong>
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
            {commandBusy ? t("desktop.cancelling") : t("desktop.cancelInstall")}
          </button>
        ) : phase === "completed" ? (
          <Link to="/jobs/new" className="btn btn-primary">
            {t("desktop.continue")}
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
