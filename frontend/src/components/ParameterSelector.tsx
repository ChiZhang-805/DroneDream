import { useEffect, useMemo, useState } from "react";

import type {
  ParameterApplyPolicy,
  PX4ParameterDefinition,
  TuningMode,
} from "../types/api";
import {
  groupCatalog,
  type ParameterSelectionMap,
} from "../features/experiment/parameterCatalog";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";

interface ParameterSelectorProps {
  catalog: PX4ParameterDefinition[];
  catalogSource: "backend" | "builtin";
  mode: TuningMode;
  selections: ParameterSelectionMap;
  estimatedTrials: number;
  errors: Record<string, string>;
  onChange: (selections: ParameterSelectionMap) => void;
  onApplyPreset: (mode: TuningMode) => void;
}

const GROUP_KEYS: Record<string, TranslationKey> = {
  xy_position_velocity: "parameter.group.xy",
  z_position_velocity: "parameter.group.z",
  attitude: "parameter.group.attitude",
  angular_rate: "parameter.group.rate",
  motion_limits: "parameter.group.limits",
  thrust_and_authority: "parameter.group.thrust",
  filters: "parameter.group.filters",
};

const APPLY_POLICY_KEYS: Record<ParameterApplyPolicy, TranslationKey> = {
  live: "parameter.apply.live",
  disarmed: "parameter.apply.disarmed",
  reboot: "parameter.apply.reboot",
};

export function ParameterSelector({
  catalog,
  catalogSource,
  mode,
  selections,
  estimatedTrials,
  errors,
  onChange,
  onApplyPreset,
}: ParameterSelectorProps) {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState<"all" | PX4ParameterDefinition["risk"]>("all");
  const [selectionFilter, setSelectionFilter] = useState<"all" | "selected" | "unselected">("all");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    () => new Set(
      catalog
        .filter((parameter) => selections[parameter.name]?.selected)
        .map((parameter) => parameter.group),
    ),
  );
  const normalizedQuery = query.trim().toLowerCase();
  const groups = useMemo(
    () => [...new Set(catalog.map((parameter) => parameter.group))],
    [catalog],
  );
  const filtered = useMemo(
    () =>
      catalog.filter((parameter) => {
        const selection = selections[parameter.name];
        const searchText = [
          parameter.name,
          parameter.label,
          parameter.description,
          parameter.group,
          parameter.localized_label?.[locale],
          parameter.localized_description?.[locale],
          parameter.unit,
          parameter.control_loop,
          parameter.apply_policy,
          parameter.risk_note?.[locale],
          parameter.risk_note?.en,
          ...parameter.dependencies,
          ...(parameter.axes ?? []),
          ...(parameter.preconditions ?? []),
          ...(parameter.flight_modes ?? []),
          ...(parameter.choices ?? []).flatMap((choice) => [
            String(choice.value),
            choice.label[locale],
            choice.label.en,
          ]),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return (
          (normalizedQuery === "" || searchText.includes(normalizedQuery)) &&
          (groupFilter === "all" || parameter.group === groupFilter) &&
          (riskFilter === "all" || parameter.risk === riskFilter) &&
          (selectionFilter === "all" ||
            (selectionFilter === "selected" ? selection?.selected : !selection?.selected))
        );
      }),
    [catalog, groupFilter, locale, normalizedQuery, riskFilter, selectionFilter, selections],
  );
  const selectedNames = useMemo(
    () => new Set(Object.values(selections).filter((item) => item.selected).map((item) => item.name)),
    [selections],
  );
  const selectedCount = selectedNames.size;
  const selectedDefinitions = catalog.filter((parameter) => selectedNames.has(parameter.name));
  const highRiskCount = selectedDefinitions.filter((parameter) => parameter.risk === "high").length;
  const rebootCount = selectedDefinitions.filter((parameter) => parameter.requires_reboot).length;
  const outsideSafeCount = selectedDefinitions.filter((parameter) => {
    const selection = selections[parameter.name];
    return selection && (
      selection.search_min < parameter.safe_min || selection.search_max > parameter.safe_max
    );
  }).length;
  const missingDependencies = useMemo(() => {
    const missing = new Set<string>();
    for (const parameter of catalog) {
      if (!selectedNames.has(parameter.name)) continue;
      for (const dependency of parameter.dependencies) {
        if (selections[dependency] && !selectedNames.has(dependency)) missing.add(dependency);
      }
    }
    return [...missing];
  }, [catalog, selectedNames, selections]);
  const filtersActive = normalizedQuery !== "" || groupFilter !== "all" || riskFilter !== "all" || selectionFilter !== "all";

  useEffect(() => {
    const selectedGroups = catalog
      .filter((parameter) => selectedNames.has(parameter.name))
      .map((parameter) => parameter.group);
    setExpandedGroups((current) => {
      if (selectedGroups.every((group) => current.has(group))) return current;
      return new Set([...current, ...selectedGroups]);
    });
  }, [catalog, selectedNames]);

  function patchSelection(
    name: string,
    patch: Partial<ParameterSelectionMap[string]>,
  ): void {
    const current = selections[name];
    if (!current) return;
    onChange({ ...selections, [name]: { ...current, ...patch } });
  }

  function setGroupSelected(parameters: PX4ParameterDefinition[], selected: boolean): void {
    const next = { ...selections };
    for (const parameter of parameters) {
      if (next[parameter.name]) next[parameter.name] = { ...next[parameter.name], selected };
    }
    onChange(next);
  }

  function includeDependencies(): void {
    const next = { ...selections };
    const definitions = new Map(catalog.map((parameter) => [parameter.name, parameter]));
    const pending = [...selectedNames];
    const visited = new Set<string>();
    while (pending.length > 0) {
      const name = pending.pop();
      if (!name || visited.has(name)) continue;
      visited.add(name);
      for (const dependency of definitions.get(name)?.dependencies ?? []) {
        if (!next[dependency]) continue;
        next[dependency] = { ...next[dependency], selected: true };
        pending.push(dependency);
      }
    }
    onChange(next);
  }

  function restoreSafeRange(parameter: PX4ParameterDefinition): void {
    patchSelection(parameter.name, {
      baseline: parameter.default_value,
      search_min: parameter.safe_min,
      search_max: parameter.safe_max,
      scale: parameter.scale,
    });
  }

  function parseNumericInput(raw: string): number {
    return raw.trim() === "" ? Number.NaN : Number(raw);
  }

  function numericInputValue(value: number): number | "" {
    return Number.isFinite(value) ? value : "";
  }

  function toggleGroup(group: string): void {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });
  }

  return (
    <div className="parameter-selector">
      <div className="parameter-summary-bar">
        <div>
          <span className="parameter-summary-value">{selectedCount}</span>
          <span className="parameter-summary-label">{t("parameter.dimensions")}</span>
        </div>
        <div>
          <span className="parameter-summary-value">≈ {estimatedTrials}</span>
          <span className="parameter-summary-label">{t("parameter.plannedTrials")}</span>
        </div>
        <div>
          <span className={`catalog-source catalog-source-${catalogSource}`}>
            {catalogSource === "backend" ? t("parameter.backendCatalog") : t("parameter.builtinCatalog")}
          </span>
        </div>
      </div>

      <div className="parameter-selector-controls">
        <label className="parameter-search">
          <span>{t("parameter.find")}</span>
          <input
            id="parameter-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("parameter.placeholder")}
          />
        </label>
        <label className="parameter-filter">
          <span>{t("parameter.filterGroup")}</span>
          <select value={groupFilter} onChange={(event) => setGroupFilter(event.target.value)}>
            <option value="all">{t("parameter.allGroups")}</option>
            {groups.map((group) => (
              <option key={group} value={group}>
                {GROUP_KEYS[group] ? t(GROUP_KEYS[group]) : group}
              </option>
            ))}
          </select>
        </label>
        <label className="parameter-filter">
          <span>{t("parameter.filterRisk")}</span>
          <select
            value={riskFilter}
            onChange={(event) => setRiskFilter(event.target.value as typeof riskFilter)}
          >
            <option value="all">{t("parameter.allRisks")}</option>
            <option value="low">{t("parameter.riskLow")}</option>
            <option value="medium">{t("parameter.riskMedium")}</option>
            <option value="high">{t("parameter.riskHigh")}</option>
          </select>
        </label>
        <label className="parameter-filter">
          <span>{t("parameter.filterSelection")}</span>
          <select
            value={selectionFilter}
            onChange={(event) => setSelectionFilter(event.target.value as typeof selectionFilter)}
          >
            <option value="all">{t("parameter.allParameters")}</option>
            <option value="selected">{t("parameter.selectedOnly")}</option>
            <option value="unselected">{t("parameter.unselectedOnly")}</option>
          </select>
        </label>
        <button type="button" className="btn btn-ghost btn-small" onClick={() => onApplyPreset(mode)}>
          {t("parameter.reapply")} · {t(`wizard.mode.${mode}` as TranslationKey)}
        </button>
        {mode !== "basic" ? (
          <>
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setGroupSelected(filtered, true)}>
              {t("parameter.selectVisible")}
            </button>
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setGroupSelected(filtered, false)}>
              {t("parameter.clearVisible")}
            </button>
          </>
        ) : null}
      </div>

      {highRiskCount > 0 || rebootCount > 0 || outsideSafeCount > 0 ? (
        <div className="parameter-safety-summary" role="status">
          <strong>{t("parameter.safetyReview")}</strong>
          <span>
            {highRiskCount} {t("parameter.highRiskSelected")} · {rebootCount} {t("parameter.restartSelected")} · {outsideSafeCount} {t("parameter.outsideSafeSelected")}
          </span>
        </div>
      ) : null}
      {missingDependencies.length > 0 ? (
        <div className="parameter-dependency-summary" role="status">
          <span>
            {t("parameter.missingCompanions")}: <code>{missingDependencies.join(", ")}</code>
          </span>
          <button type="button" className="btn btn-ghost btn-small" onClick={includeDependencies}>
            {t("parameter.includeCompanions")}
          </button>
        </div>
      ) : null}

      {errors.parameters ? <div className="form-error" role="alert">{errors.parameters}</div> : null}

      <div className="parameter-groups">
        {groupCatalog(filtered).map(([group, parameters]) => {
          const expanded = filtersActive || expandedGroups.has(group);
          const groupLabel = GROUP_KEYS[group] ? t(GROUP_KEYS[group]) : group;
          return (
          <section key={group} className="parameter-group">
            <header className="parameter-group-header">
              <div>
                <h3>{groupLabel}</h3>
                <span>{parameters.filter((parameter) => selections[parameter.name]?.selected).length}/{parameters.length} {t("parameter.selected")}</span>
              </div>
              <div className="parameter-group-actions">
                <button
                  type="button"
                  className="btn btn-ghost btn-small"
                  aria-expanded={expanded}
                  aria-label={`${expanded ? t("parameter.collapseGroup") : t("parameter.expandGroup")}: ${groupLabel}`}
                  disabled={filtersActive}
                  onClick={() => toggleGroup(group)}
                >
                  {expanded ? t("parameter.collapseGroup") : t("parameter.expandGroup")}
                </button>
                {mode !== "basic" ? (
                  <>
                  <button type="button" className="btn btn-ghost btn-small" aria-label={`${t("parameter.selectGroup")}: ${groupLabel}`} onClick={() => setGroupSelected(parameters, true)}>
                    {t("parameter.selectGroup")}
                  </button>
                  <button type="button" className="btn btn-ghost btn-small" aria-label={`${t("parameter.clearGroup")}: ${groupLabel}`} onClick={() => setGroupSelected(parameters, false)}>
                    {t("parameter.clearGroup")}
                  </button>
                  </>
                ) : null}
              </div>
            </header>
            {expanded ? <div className="parameter-table-wrap">
              <table className="parameter-table">
                <thead>
                  <tr>
                    <th>{t("parameter.use")}</th>
                    <th>{t("parameter.parameter")}</th>
                    <th>{t("parameter.baseline")}</th>
                    {mode !== "basic" ? <th>{t("parameter.minimum")}</th> : null}
                    {mode !== "basic" ? <th>{t("parameter.maximum")}</th> : null}
                    <th>{t("parameter.risk")}</th>
                  </tr>
                </thead>
                <tbody>
                  {parameters.map((parameter) => {
                    const selection = selections[parameter.name];
                    if (!selection) return null;
                    const parameterError = errors[parameter.name];
                    const outsideSafeRange = selection.selected && (
                      selection.search_min < parameter.safe_min ||
                      selection.search_max > parameter.safe_max
                    );
                    const riskNote = parameter.risk_note?.[locale] ?? parameter.risk_note?.en;
                    const hasSafetyGuidance = Boolean(riskNote) || Boolean(parameter.preconditions?.length);
                    return (
                      <tr
                        key={parameter.name}
                        className={selection.selected ? "parameter-row-selected" : undefined}
                      >
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`Tune ${parameter.name}`}
                            checked={selection.selected}
                            disabled={mode === "basic"}
                            onChange={(event) =>
                              patchSelection(parameter.name, { selected: event.target.checked })
                            }
                          />
                        </td>
                        <td>
                          <code className="parameter-name">{parameter.name}</code>
                          <span className="parameter-label">{parameter.localized_label?.[locale] ?? parameter.label}</span>
                          <span className="parameter-description">{parameter.localized_description?.[locale] ?? parameter.description}</span>
                          <span className="parameter-bounds">
                            {t("parameter.absolute")}: {parameter.absolute_min}–{parameter.absolute_max}{parameter.unit ? ` ${parameter.unit}` : ""}
                            {parameter.requires_reboot ? ` · ${t("parameter.restart")}` : ""}
                          </span>
                          {parameter.apply_policy ? (
                            <span className="parameter-metadata">
                              <span className={`apply-policy-badge apply-policy-${parameter.apply_policy}`}>
                                {t("parameter.applyPolicy")}: {t(APPLY_POLICY_KEYS[parameter.apply_policy])}
                              </span>
                            </span>
                          ) : null}
                          {parameter.choices?.length ? (
                            <span className="parameter-choices">
                              {t("parameter.discreteChoices")}: {parameter.choices.map((choice) => (
                                `${choice.value}: ${choice.label[locale] ?? choice.label.en}`
                              )).join(" · ")}
                            </span>
                          ) : null}
                        </td>
                        <td>
                          <label className="sr-only" htmlFor={`parameter-${parameter.name}-baseline`}>
                            {parameter.name} baseline
                          </label>
                          <input
                            id={`parameter-${parameter.name}-baseline`}
                            type="number"
                            step={parameter.step}
                            min={parameter.absolute_min}
                            max={parameter.absolute_max}
                            value={numericInputValue(selection.baseline)}
                            disabled={!selection.selected}
                            onChange={(event) =>
                              patchSelection(parameter.name, { baseline: parseNumericInput(event.target.value) })
                            }
                          />
                        </td>
                        {mode !== "basic" ? (
                          <td>
                            <label className="sr-only" htmlFor={`parameter-${parameter.name}-min`}>
                              {parameter.name} search minimum
                            </label>
                            <input
                              id={`parameter-${parameter.name}-min`}
                              type="number"
                              step={parameter.step}
                              min={parameter.absolute_min}
                              max={parameter.absolute_max}
                              value={numericInputValue(selection.search_min)}
                              disabled={!selection.selected}
                              onChange={(event) =>
                                patchSelection(parameter.name, { search_min: parseNumericInput(event.target.value) })
                              }
                            />
                          </td>
                        ) : null}
                        {mode !== "basic" ? (
                          <td>
                            <label className="sr-only" htmlFor={`parameter-${parameter.name}-max`}>
                              {parameter.name} search maximum
                            </label>
                            <input
                              id={`parameter-${parameter.name}-max`}
                              type="number"
                              step={parameter.step}
                              min={parameter.absolute_min}
                              max={parameter.absolute_max}
                              value={numericInputValue(selection.search_max)}
                              disabled={!selection.selected}
                              onChange={(event) =>
                                patchSelection(parameter.name, { search_max: parseNumericInput(event.target.value) })
                              }
                            />
                          </td>
                        ) : null}
                        <td>
                          <span className={`risk-badge risk-${parameter.risk}`}>{parameter.risk}</span>
                          {parameter.dependencies.length > 0 ? (
                            <span className="parameter-dependencies">
                              {t("parameter.with")}: {parameter.dependencies.join(", ")}
                            </span>
                          ) : (
                            <span className="parameter-dependencies">{t("parameter.independent")}</span>
                          )}
                          {selection.selected && parameter.dependencies.some((name) => selections[name] && !selections[name].selected) ? (
                            <span className="parameter-dependency-missing">{t("parameter.companionNotSelected")}</span>
                          ) : null}
                          {outsideSafeRange ? (
                            <span className="parameter-dependency-missing">{t("parameter.outsideSafeRange")}</span>
                          ) : null}
                          {hasSafetyGuidance ? (
                            <details className="parameter-guidance">
                              <summary>{t("parameter.safetyGuidance")}</summary>
                              {riskNote ? <p>{riskNote}</p> : null}
                              {parameter.preconditions?.length ? (
                                <ul>
                                  {parameter.preconditions.map((precondition) => (
                                    <li key={precondition}>{precondition}</li>
                                  ))}
                                </ul>
                              ) : null}
                            </details>
                          ) : null}
                          {mode !== "basic" ? (
                            <button
                              type="button"
                              className="btn btn-ghost btn-small parameter-safe-reset"
                              disabled={!selection.selected}
                              onClick={() => restoreSafeRange(parameter)}
                            >
                              {t("parameter.restoreSafe")}
                            </button>
                          ) : null}
                          {parameterError ? <span className="form-error" role="alert">{parameterError}</span> : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div> : null}
          </section>
          );
        })}
      </div>
      {filtered.length === 0 ? <div className="insight-empty">{t("parameter.noMatches")}</div> : null}
    </div>
  );
}
