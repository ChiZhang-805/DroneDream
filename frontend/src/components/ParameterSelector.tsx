import { useMemo, useState } from "react";

import type { PX4ParameterDefinition, TuningMode } from "../types/api";
import {
  groupCatalog,
  type ParameterSelectionMap,
} from "../features/experiment/parameterCatalog";
import { useI18n } from "../i18n/I18nProvider";
import type { TranslationKey } from "../i18n/I18nProvider";

interface ParameterSelectorProps {
  catalog: PX4ParameterDefinition[];
  catalogSource?: "backend" | "builtin";
  mode: TuningMode;
  selections: ParameterSelectionMap;
  errors: Record<string, string>;
  onChange: (selections: ParameterSelectionMap) => void;
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

export function ParameterSelector({
  catalog,
  mode,
  selections,
  errors,
  onChange,
}: ParameterSelectorProps) {
  const { locale, t } = useI18n();
  const [query, setQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState("all");
  const [selectionFilter, setSelectionFilter] = useState<"all" | "selected" | "unselected">("all");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(
    () => {
      const firstSelectedGroup = catalog.find(
        (parameter) => selections[parameter.name]?.selected,
      )?.group;
      return new Set(firstSelectedGroup ? [firstSelectedGroup] : []);
    },
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
          (selectionFilter === "all" ||
            (selectionFilter === "selected" ? selection?.selected : !selection?.selected))
        );
      }),
    [catalog, groupFilter, locale, normalizedQuery, selectionFilter, selections],
  );
  const filtersActive = normalizedQuery !== "" || groupFilter !== "all" || selectionFilter !== "all";

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
                {GROUP_KEYS[group] ? t(GROUP_KEYS[group]) : t("parameter.group.other")}
              </option>
            ))}
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

      <div className="parameter-groups">
        {groupCatalog(filtered).map(([group, parameters]) => {
          const expanded = filtersActive || expandedGroups.has(group);
          const groupLabel = GROUP_KEYS[group] ? t(GROUP_KEYS[group]) : t("parameter.group.other");
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
                <button type="button" className="btn btn-ghost btn-small" aria-label={`${t("parameter.selectGroup")}: ${groupLabel}`} onClick={() => setGroupSelected(parameters, true)}>
                  {t("parameter.selectGroup")}
                </button>
                <button type="button" className="btn btn-ghost btn-small" aria-label={`${t("parameter.clearGroup")}: ${groupLabel}`} onClick={() => setGroupSelected(parameters, false)}>
                  {t("parameter.clearGroup")}
                </button>
              </div>
            </header>
            {expanded ? <div className="parameter-table-wrap">
              <table className="parameter-table">
                <thead>
                  <tr>
                    <th>{t("parameter.use")}</th>
                    <th>{t("parameter.parameter")}</th>
                    <th>{t("parameter.baseline")}</th>
                    <th>{t("parameter.minimum")}</th>
                    <th>{t("parameter.maximum")}</th>
                    <th>{t("parameter.with")}</th>
                  </tr>
                </thead>
                <tbody>
                  {parameters.map((parameter) => {
                    const selection = selections[parameter.name];
                    if (!selection) return null;
                    const parameterError = errors[parameter.name];
                    const localizedLabel = locale === "zh-CN"
                      ? parameter.localized_label?.["zh-CN"] ?? parameter.name
                      : parameter.localized_label?.en ?? parameter.name;
                    return (
                      <tr
                        key={parameter.name}
                        className={selection.selected ? "parameter-row-selected" : undefined}
                      >
                        <td>
                          <select
                            className="parameter-use-select"
                            aria-label={t("parameter.aria.tune", { name: parameter.name })}
                            value={selection.selected ? "include" : "exclude"}
                            onChange={(event) =>
                              patchSelection(parameter.name, { selected: event.target.value === "include" })
                            }
                          >
                            <option value="include">{t("parameter.include")}</option>
                            <option value="exclude">{t("parameter.exclude")}</option>
                          </select>
                        </td>
                        <td>
                          <code className="parameter-name">{parameter.name}</code>
                          <span className="parameter-label">{localizedLabel}</span>
                        </td>
                        <td>
                          <label className="sr-only" htmlFor={`parameter-${parameter.name}-baseline`}>
                            {t("parameter.aria.baseline", { name: parameter.name })}
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
                        <td>
                            <label className="sr-only" htmlFor={`parameter-${parameter.name}-min`}>
                              {t("parameter.aria.minimum", { name: parameter.name })}
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
                        <td>
                            <label className="sr-only" htmlFor={`parameter-${parameter.name}-max`}>
                              {t("parameter.aria.maximum", { name: parameter.name })}
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
                        <td>
                          {parameter.dependencies.length > 0 ? (
                            <span className="parameter-dependencies parameter-dependencies-prominent">{parameter.dependencies.join(", ")}</span>
                          ) : (
                            <span className="parameter-dependencies parameter-dependencies-empty">—</span>
                          )}
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
