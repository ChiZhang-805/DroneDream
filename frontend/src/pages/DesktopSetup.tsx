import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Alert } from "../components/Alert";
import { Loading } from "../components/States";
import { SectionCard } from "../components/SectionCard";
import {
  getRuntimeInstallPlan,
  isDesktopRuntime,
  probeRuntimeStatus,
  probeSystemPrerequisites,
} from "../desktop/bridge";
import type {
  DiskInfo,
  RuntimeComponentState,
  RuntimeInstallPlan,
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "../desktop/bridge";
import { formatBytes } from "../desktop/format";
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

const GIB = 1024 ** 3;
// Windows reserves a small part of a nominal 16 GB installation for hardware.
// Treat 15 GiB of reported physical memory as a 16 GB-class machine.
const MINIMUM_MEMORY_BYTES = 15 * GIB;

function fixedDiskOptions(disks: DiskInfo[]): DiskInfo[] {
  // The prerequisite command returns only DriveType=3 disks. Keep the UI
  // constrained to well-formed local drive roots from that trusted report.
  const unique = new Map<string, DiskInfo>();
  for (const disk of disks) {
    const drive = disk.drive.trim().toUpperCase();
    if (!/^[A-Z]:$/.test(drive) || unique.has(drive)) continue;
    unique.set(drive, { ...disk, drive });
  }
  return [...unique.values()].sort((left, right) => right.freeBytes - left.freeBytes);
}

function chooseRuntimeDrive(disks: DiskInfo[], currentDrive: string): string {
  const normalizedCurrent = currentDrive.trim().toUpperCase();
  return disks.some((disk) => disk.drive === normalizedCurrent)
    ? normalizedCurrent
    : disks[0]?.drive ?? "";
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

function runtimeIsReady(report: RuntimeStatusReport | null): boolean {
  const requiredComponents = report?.components.filter((component) => component.required) ?? [];
  return Boolean(
    report?.ready &&
    report.installed &&
    report.running &&
    requiredComponents.length > 0 &&
    requiredComponents.every((component) => component.status === "ready"),
  );
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
  const [selectedDrive, setSelectedDrive] = useState("");
  const busy = state.loading || state.planLoading;
  const showInstallPlanner =
    state.prerequisitesFresh &&
    state.runtimeFresh &&
    state.runtime?.installed === false;

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
    const nextDrive = prerequisites.status === "fulfilled"
      ? chooseRuntimeDrive(fixedDisks, selectedDriveRef.current)
      : selectedDriveRef.current;
    if (prerequisites.status === "fulfilled") {
      selectedDriveRef.current = nextDrive;
      setSelectedDrive(nextDrive);
    }
    const shouldRequestPlan =
      prerequisites.status === "fulfilled" &&
      runtime.status === "fulfilled" &&
      !runtime.value.installed &&
      fixedDisks.length > 0 &&
      Boolean(nextDrive);

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
    const plan = await getSettledInstallPlan(nextDrive);
    if (requestId.current !== currentRequest) return;

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
          {state.runtimeFresh && state.runtime?.installed ? (
            <InstalledRuntimeNotice report={state.runtime} />
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
    prerequisites?.supported === true &&
    runtimeFresh &&
    runtimeIsReady(runtime);
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
  const ready = !stale && runtimeIsReady(report);
  return (
    <SectionCard
      title={t("desktop.runtimeTitle")}
      description={t("desktop.runtimeDesc")}
      actions={
        stale ? (
          <StaleResultBadge />
        ) : (
          <span className={`desktop-runtime-pill ${ready ? "ready" : "pending"}`}>
            {ready ? t("desktop.ready") : t("desktop.needsAction")}
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

function InstalledRuntimeNotice({ report }: { report: RuntimeStatusReport }) {
  const { t } = useI18n();
  const ready = runtimeIsReady(report);
  return (
    <Alert
      tone={ready ? "success" : "warning"}
      title={ready
        ? t("desktop.runtimeAlreadyReady")
        : t("desktop.runtimeNeedsRepair")}
    >
      {t("desktop.installedStorageHint")}
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
