import { useMemo, useState } from "react";

import type {
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
  filters: "parameter.group.filters",
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
  const normalizedQuery = query.trim().toLowerCase();
  const filtered = useMemo(
    () =>
      catalog.filter((parameter) =>
        normalizedQuery === ""
          ? true
          : `${parameter.name} ${parameter.label} ${parameter.group}`
              .toLowerCase()
              .includes(normalizedQuery),
      ),
    [catalog, normalizedQuery],
  );
  const selectedCount = Object.values(selections).filter((item) => item.selected).length;

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

      {errors.parameters ? <div className="form-error" role="alert">{errors.parameters}</div> : null}

      <div className="parameter-groups">
        {groupCatalog(filtered).map(([group, parameters]) => (
          <section key={group} className="parameter-group">
            <header className="parameter-group-header">
              <h3>{GROUP_KEYS[group] ? t(GROUP_KEYS[group]) : group}</h3>
              <span>{parameters.filter((parameter) => selections[parameter.name]?.selected).length}/{parameters.length} {t("parameter.selected")}</span>
            </header>
            <div className="parameter-table-wrap">
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
                            value={selection.baseline}
                            disabled={!selection.selected}
                            onChange={(event) =>
                              patchSelection(parameter.name, { baseline: Number(event.target.value) })
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
                              value={selection.search_min}
                              disabled={!selection.selected}
                              onChange={(event) =>
                                patchSelection(parameter.name, { search_min: Number(event.target.value) })
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
                              value={selection.search_max}
                              disabled={!selection.selected}
                              onChange={(event) =>
                                patchSelection(parameter.name, { search_max: Number(event.target.value) })
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
                          {parameterError ? <span className="form-error" role="alert">{parameterError}</span> : null}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
      {filtered.length === 0 ? <div className="insight-empty">{t("parameter.noMatches")}</div> : null}
    </div>
  );
}
