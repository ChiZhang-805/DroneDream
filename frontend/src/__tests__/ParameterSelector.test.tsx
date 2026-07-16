import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ParameterSelector } from "../components/ParameterSelector";
import {
  BUILTIN_PARAMETER_CATALOG,
  createParameterSelections,
} from "../features/experiment/parameterCatalog";
import { I18nProvider } from "../i18n/I18nProvider";

describe("ParameterSelector compact parameter table", () => {
  beforeEach(() => {
    window.localStorage.setItem("drone-dream:locale", "en");
  });

  it("keeps only tuning values, localized names and related parameters", () => {
    const source = BUILTIN_PARAMETER_CATALOG.parameters.find(
      (parameter) => parameter.name === "MPC_ACC_HOR",
    );
    expect(source).toBeDefined();
    const parameter = { ...source!, group: "motion_limits" };
    const selections = createParameterSelections([parameter], "advanced");
    selections.MPC_ACC_HOR = { ...selections.MPC_ACC_HOR, selected: true };
    const changeSpy = vi.fn();

    render(
      <I18nProvider>
        <ParameterSelector
          catalog={[parameter]}
          catalogSource="backend"
          mode="advanced"
          selections={selections}
          errors={{}}
          onChange={changeSpy}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole("heading", { name: "Motion limits" })).toBeVisible();
    expect(screen.getByText("MPC_ACC_HOR_MAX")).toBeVisible();
    expect(screen.queryByText(/Apply:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Absolute range/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Safety guidance/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/risk/i)).not.toBeInTheDocument();
    expect(screen.queryByText("search dimensions")).not.toBeInTheDocument();
    expect(screen.queryByText("planned trials")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reapply preset/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Tune MPC_ACC_HOR")).toHaveValue("include");
    fireEvent.change(screen.getByLabelText("Tune MPC_ACC_HOR"), {
      target: { value: "exclude" },
    });
    expect(changeSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        MPC_ACC_HOR: expect.objectContaining({ selected: false }),
      }),
    );
  });

  it("keeps the same editable tuning columns in basic mode", () => {
    const source = BUILTIN_PARAMETER_CATALOG.parameters.find(
      (parameter) => parameter.name === "MPC_XY_P",
    );
    expect(source).toBeDefined();
    const parameter = { ...source!, group: "xy_position_velocity" };
    const selections = createParameterSelections([parameter], "basic");
    const changeSpy = vi.fn();

    render(
      <I18nProvider>
        <ParameterSelector
          catalog={[parameter]}
          catalogSource="builtin"
          mode="basic"
          selections={selections}
          errors={{}}
          onChange={changeSpy}
        />
      </I18nProvider>,
    );

    expect(screen.getByLabelText("Tune MPC_XY_P")).toBeEnabled();
    expect(screen.getByLabelText("MPC_XY_P search minimum")).toBeInTheDocument();
    expect(screen.getByLabelText("MPC_XY_P search maximum")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Tune MPC_XY_P"), {
      target: { value: "exclude" },
    });
    expect(changeSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        MPC_XY_P: expect.objectContaining({ selected: false }),
      }),
    );
  });
});
