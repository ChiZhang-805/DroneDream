import { Boxes, Globe2, HardDrive, ShieldCheck } from "lucide-react";
import { useEffect, useId, useState } from "react";

import {
  isDesktopRuntime,
  validateDistributionPlan,
  type DistributionPlanValidation,
} from "../desktop/bridge";
import {
  controllerKey,
  DISTRIBUTION_CATALOG,
  localizedDistributionText,
  type DistributionLocale,
  type RegionId,
} from "../features/distribution/catalog";
import {
  buildDistributionInstallationPreview,
  DISTRIBUTION_SELECTION_STORAGE_KEY,
  normalizeDistributionSelection,
  parseDistributionSelectionDraft,
  type DistributionSelectionDraft,
  type DistributionSelectionIssueCode,
} from "../features/distribution/installationSelection";
import { useI18n } from "../i18n/I18nProvider";
import {
  SIM_EDITION,
  defaultSimDistributionSelection,
  lockDistributionSelectionToSim,
} from "../editions/sim/profile";

type DistributionSetupVariant = "settings" | "setup";

const COPY = {
  en: {
    title: "Simulation & Vehicle Pack",
    description: "Choose a region and a versioned simulation vehicle profile for DroneDream · SIM.",
    previewOnly: "Selection preview",
    edition: "Edition",
    region: "Region",
    global: "Global",
    cn: "Chinese mainland",
    vehicle: "Vehicle Pack",
    controller: "Flight controller",
    noController: "No physical controller",
    optionalModules: "Optional modules",
    requiredModules: "Included modules",
    download: "Estimated download",
    pendingSize: "Pending an exact build plan",
    validation: "Validation",
    availability: "Availability evidence",
    golden: "Validation priority",
    browserBoundary: "This browser saves a draft only. It cannot install modules or control hardware.",
    desktopBoundary: "Nothing is installed from this panel. Native verification must approve a future plan.",
    nativeChecking: "Native plan check in progress — no changes are being applied.",
    nativeBlocked: "Native plan checked and safely blocked",
    nativeError: "Native plan check failed closed — no changes were applied.",
    blockerCount: "blockers",
    noAction: "Preview saved locally · no installation started",
    issueTitle: "Why this selection cannot be applied yet",
    issue: {
      "vehicle-pack-required": "Select a Vehicle Pack.",
      "vehicle-pack-incompatible": "This Vehicle Pack does not support the selected edition or region.",
      "vehicle-pack-planned": "This Vehicle Pack is planned and has no validation receipt.",
      "vehicle-pack-unvalidated": "This Vehicle Pack is contract-only and has no signed validation receipt.",
      "controller-required": "Select a compatible flight controller.",
      "controller-incompatible": "The selected flight controller is not compatible with this pack and region.",
      "edition-contract-only": "This edition is contract-only and cannot authorize installation.",
      "download-estimate-pending": "Download size remains unknown until the exact build plan is frozen.",
      "native-plan-required": "A native, source-bound installation plan is not implemented yet.",
    },
  },
  "zh-CN": {
    title: "仿真与机型包",
    description: "为 DroneDream · SIM 选择使用地区和版本化仿真机型配置。",
    previewOnly: "仅选择预览",
    edition: "产品版本",
    region: "使用地区",
    global: "全球",
    cn: "中国大陆",
    vehicle: "机型包",
    controller: "飞行控制器",
    noController: "不使用真机控制器",
    optionalModules: "可选模块",
    requiredModules: "包含模块",
    download: "预计下载量",
    pendingSize: "等待精确构建计划",
    validation: "验证等级",
    availability: "供应证据",
    golden: "优先验证候选",
    browserBoundary: "网页只保存选择草稿，不能安装模块或控制真机。",
    desktopBoundary: "此面板不会开始安装；未来计划仍须通过原生端同源校验。",
    nativeChecking: "原生计划正在校验，不会应用任何变更。",
    nativeBlocked: "原生计划已校验并安全阻断",
    nativeError: "原生计划校验失败并已安全阻断，未应用任何变更。",
    blockerCount: "项阻断原因",
    noAction: "选择已保存在本机 · 未开始安装",
    issueTitle: "当前不能应用此选择的原因",
    issue: {
      "vehicle-pack-required": "请选择一个机型包。",
      "vehicle-pack-incompatible": "该机型包不支持当前版本或地区。",
      "vehicle-pack-planned": "该机型包仍在规划中，尚无验证回执。",
      "vehicle-pack-unvalidated": "该机型包仅完成合同，尚无签名验证回执。",
      "controller-required": "请选择兼容的飞行控制器。",
      "controller-incompatible": "所选飞控与当前机型包或地区不兼容。",
      "edition-contract-only": "该产品版本仅完成合同，不能授权安装。",
      "download-estimate-pending": "冻结精确构建计划前不会显示下载量。",
      "native-plan-required": "尚未实现与源码绑定的原生安装计划。",
    },
  },
} as const;

function initialSelection(locale: DistributionLocale): DistributionSelectionDraft {
  const fallback = defaultSimDistributionSelection(locale === "zh-CN" ? "cn" : "global");
  try {
    const saved = window.localStorage.getItem(DISTRIBUTION_SELECTION_STORAGE_KEY);
    if (!saved) return fallback;
    return lockDistributionSelectionToSim(
      parseDistributionSelectionDraft(JSON.parse(saved)),
    );
  } catch {
    return fallback;
  }
}

function moduleLabel(moduleId: string): string {
  return moduleId
    .split("-")
    .map((part) => part === "px4" ? "PX4" : part === "hitl" ? "HITL" : part)
    .join(" ");
}

export function DistributionSetupPanel({
  variant = "setup",
}: {
  variant?: DistributionSetupVariant;
}) {
  const { locale } = useI18n();
  const copy = COPY[locale];
  const id = useId();
  const [selection, setSelection] = useState<DistributionSelectionDraft>(() => (
    initialSelection(locale)
  ));
  const [nativePlanState, setNativePlanState] = useState<
    | { status: "browser" | "checking" | "failed" }
    | { status: "blocked"; plan: DistributionPlanValidation }
  >({ status: isDesktopRuntime() ? "checking" : "browser" });
  const preview = buildDistributionInstallationPreview(selection);
  const updateSelection = (next: DistributionSelectionDraft) => {
    setSelection(lockDistributionSelectionToSim(normalizeDistributionSelection(next)));
  };

  useEffect(() => {
    try {
      window.localStorage.setItem(
        DISTRIBUTION_SELECTION_STORAGE_KEY,
        JSON.stringify(selection),
      );
    } catch {
      // Storage is a convenience only. A blocked browser or private session
      // must never turn this preview into native authority or break rendering.
    }
  }, [selection]);

  useEffect(() => {
    if (!isDesktopRuntime()) {
      setNativePlanState({ status: "browser" });
      return undefined;
    }
    let active = true;
    setNativePlanState({ status: "checking" });
    void validateDistributionPlan({
      selection,
      rollbackReference: null,
    }).then((plan) => {
      if (active) setNativePlanState({ status: "blocked", plan });
    }).catch(() => {
      if (active) setNativePlanState({ status: "failed" });
    });
    return () => {
      active = false;
    };
  }, [selection]);

  const selectedPack = preview.selectedVehiclePack;
  const blockingIssues = preview.issues.filter((issue) => issue.severity === "blocking");
  const noticeIssues = preview.issues.filter((issue) => issue.severity === "notice");
  const localeKey = locale as DistributionLocale;

  return (
    <section
      className={`distribution-setup-panel distribution-setup-panel-${variant}`}
      aria-labelledby={`${id}-title`}
      data-can-apply="false"
      data-edition={selection.editionId}
      data-brand-edition="sim"
      data-capability-boundary="simulation-only"
      data-native-plan-status={nativePlanState.status}
    >
      <header className="distribution-setup-heading">
        <div>
          <span className="distribution-setup-eyebrow">
            <Boxes aria-hidden="true" />
            {copy.previewOnly}
          </span>
          <h3 id={`${id}-title`}>{copy.title}</h3>
          <p>{copy.description}</p>
        </div>
        <span className="distribution-version-badge">
          v{DISTRIBUTION_CATALOG.catalogVersion}
        </span>
      </header>

      <div className="distribution-sim-locked-edition" aria-label={copy.edition}>
        <span>
          <strong>
            {SIM_EDITION.productName}
          </strong>
          <small>
            {localizedDistributionText(preview.edition.description, localeKey)}
          </small>
        </span>
        <span>{SIM_EDITION.releaseState}</span>
      </div>

      <div className="distribution-selection-grid">
        <label htmlFor={`${id}-region`}>
          <span><Globe2 aria-hidden="true" />{copy.region}</span>
          <select
            id={`${id}-region`}
            value={selection.region}
            onChange={(event) => updateSelection({
              ...selection,
              region: event.target.value as RegionId,
            })}
          >
            <option value="global">{copy.global}</option>
            <option value="cn">{copy.cn}</option>
          </select>
        </label>
        <label htmlFor={`${id}-vehicle`}>
          <span><HardDrive aria-hidden="true" />{copy.vehicle}</span>
          <select
            id={`${id}-vehicle`}
            value={selection.vehiclePackId}
            onChange={(event) => updateSelection({
              ...selection,
              vehiclePackId: event.target.value,
              controllerKey: null,
            })}
          >
            {preview.compatibleVehiclePacks.map((pack) => (
              <option key={pack.packId} value={pack.packId}>
                {localizedDistributionText(pack.displayName, localeKey)}
              </option>
            ))}
          </select>
        </label>
        {selection.editionId !== "sim" ? (
          <label htmlFor={`${id}-controller`}>
            <span><ShieldCheck aria-hidden="true" />{copy.controller}</span>
            <select
              id={`${id}-controller`}
              value={selection.controllerKey ?? ""}
              disabled={preview.compatibleControllers.length === 0}
              onChange={(event) => updateSelection({
                ...selection,
                controllerKey: event.target.value || null,
              })}
            >
              <option value="">{copy.noController}</option>
              {preview.compatibleControllers.map((controller) => (
                <option key={controllerKey(controller)} value={controllerKey(controller)}>
                  {controller.vendor} {controller.model} · {controller.status}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      {preview.edition.optionalModules.length > 0 ? (
        <fieldset className="distribution-optional-modules">
          <legend>{copy.optionalModules}</legend>
          {preview.edition.optionalModules.map((moduleId) => (
            <label key={moduleId}>
              <input
                type="checkbox"
                checked={selection.optionalModules.includes(moduleId)}
                onChange={(event) => updateSelection({
                  ...selection,
                  optionalModules: event.target.checked
                    ? [...selection.optionalModules, moduleId]
                    : selection.optionalModules.filter((current) => current !== moduleId),
                })}
              />
              {moduleLabel(moduleId)}
            </label>
          ))}
        </fieldset>
      ) : null}

      <div className="distribution-preview-grid">
        <div>
          <span>{copy.validation}</span>
          <strong>{selectedPack?.validationStatus ?? "—"}</strong>
        </div>
        <div>
          <span>{copy.download}</span>
          <strong>{preview.downloadEstimateBytes === null ? copy.pendingSize : preview.downloadEstimateBytes}</strong>
        </div>
        <div>
          <span>{copy.availability}</span>
          <strong>{selectedPack?.productAvailability ?? "—"}</strong>
        </div>
        <div>
          <span>{copy.golden}</span>
          <strong>{selectedPack?.goldenCandidate ? "✓" : "—"}</strong>
        </div>
      </div>

      <details className="distribution-required-modules">
        <summary>{copy.requiredModules} · {preview.requiredModules.length}</summary>
        <div>
          {preview.requiredModules.map((moduleId) => (
            <span key={moduleId}>{moduleLabel(moduleId)}</span>
          ))}
        </div>
      </details>

      <div className="distribution-boundary-note" role="note">
        <ShieldCheck aria-hidden="true" />
        <p>
          {isDesktopRuntime() ? copy.desktopBoundary : copy.browserBoundary}
          {nativePlanState.status === "checking" ? ` ${copy.nativeChecking}` : null}
          {nativePlanState.status === "failed" ? ` ${copy.nativeError}` : null}
          {nativePlanState.status === "blocked" ? (
            <>
              {` ${copy.nativeBlocked} · ${nativePlanState.plan.sourceCommit.slice(0, 8)} · `}
              {nativePlanState.plan.blockers.length} {copy.blockerCount}
            </>
          ) : null}
        </p>
      </div>

      {blockingIssues.length + noticeIssues.length > 0 ? (
        <details className="distribution-issues">
          <summary>{copy.issueTitle} · {blockingIssues.length + noticeIssues.length}</summary>
          <ul>
            {[...blockingIssues, ...noticeIssues].map((issue) => (
              <li key={issue.code} data-severity={issue.severity}>
                {copy.issue[issue.code as DistributionSelectionIssueCode]}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <p className="distribution-no-action" role="status">{copy.noAction}</p>
    </section>
  );
}
