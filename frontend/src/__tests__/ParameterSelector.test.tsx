import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ParameterSelector } from "../components/ParameterSelector";
import {
  BUILTIN_PARAMETER_CATALOG,
  createParameterSelections,
} from "../features/experiment/parameterCatalog";
import { I18nProvider } from "../i18n/I18nProvider";

describe("ParameterSelector catalog guidance", () => {
  beforeEach(() => {
    window.localStorage.setItem("drone-dream:locale", "en");
  });

  it("renders apply policy, labelled choices and collapsed safety guidance", () => {
    const source = BUILTIN_PARAMETER_CATALOG.parameters.find(
      (parameter) => parameter.name === "MC_AIRMODE",
    );
    expect(source).toBeDefined();
    const parameter = {
      ...source!,
      group: "thrust_and_authority",
      preconditions: ["Verify actuator authority before flight."],
    };
    const selections = createParameterSelections([parameter], "advanced");
    selections.MC_AIRMODE = { ...selections.MC_AIRMODE, selected: true };

    render(
      <I18nProvider>
        <ParameterSelector
          catalog={[parameter]}
          catalogSource="backend"
          mode="advanced"
          selections={selections}
          estimatedTrials={8}
          errors={{}}
          onChange={vi.fn()}
          onApplyPreset={vi.fn()}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole("heading", { name: "Thrust and control authority" })).toBeVisible();
    expect(screen.getByText(/Apply: while disarmed/i)).toBeVisible();
    expect(screen.getByText(/0: Disabled.*2: Roll\/pitch\/yaw/i)).toBeVisible();

    fireEvent.click(screen.getByText("Safety guidance"));
    expect(screen.getByText(/Changing air-mode changes mixer authority/i)).toBeVisible();
    expect(screen.getByText("Verify actuator authority before flight.")).toBeVisible();
  });
});
