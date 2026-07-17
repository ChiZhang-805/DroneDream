import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { NewJob } from "../pages/NewJob";

function renderWizard(locale: "en" | "zh-CN") {
  window.localStorage.setItem("drone-dream:locale", locale);
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const result = render(
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <NewJob />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nProvider>,
  );
  const nameDialog = screen.getByRole("dialog");
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "numeric-range-study" },
  });
  fireEvent.submit(nameDialog);
  return result;
}

function control<T extends HTMLElement>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`Missing control: ${selector}`);
  return element;
}

function advance(count: number): void {
  for (let index = 0; index < count; index += 1) {
    fireEvent.click(control<HTMLButtonElement>(".wizard-actions .btn-primary"));
  }
}

describe("NewJob compact numeric range guidance", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("removes the single-option vehicle selector and puts ranges in controls", () => {
    renderWizard("en");

    expect(document.querySelector("#vehicle_type")).toBeNull();
    expect(control<HTMLInputElement>("#circle_radius_m")).toHaveAttribute("placeholder", "0–100");
    expect(document.querySelectorAll(".wizard-panel .form-hint")).toHaveLength(0);

    fireEvent.change(control<HTMLSelectElement>("#track_type"), { target: { value: "u_turn" } });
    expect(control<HTMLInputElement>("#u_turn_straight_length_m")).toHaveAttribute("placeholder", "0–200");
    expect(control<HTMLInputElement>("#u_turn_turn_radius_m")).toHaveAttribute("placeholder", "0–100");

    advance(3);
    expect(control<HTMLInputElement>("#max_iterations")).toHaveAttribute("placeholder", "1–100");
    expect(control<HTMLInputElement>("#target_rmse")).toHaveAttribute("placeholder", "0–100");
    expect(control<HTMLInputElement>("#min_pass_rate")).toHaveAttribute("placeholder", "0–1");
    expect(document.querySelectorAll(".wizard-panel .form-hint")).toHaveLength(0);
  });

  it("keeps the compact range-only treatment identical in Chinese", () => {
    renderWizard("zh-CN");

    expect(document.querySelector("#vehicle_type")).toBeNull();
    expect(control<HTMLInputElement>("#circle_radius_m")).toHaveAttribute("placeholder", "0–100");
    expect(document.querySelectorAll(".wizard-panel .form-hint")).toHaveLength(0);

    fireEvent.change(control<HTMLSelectElement>("#track_type"), { target: { value: "u_turn" } });
    expect(control<HTMLInputElement>("#u_turn_straight_length_m")).toHaveAttribute("placeholder", "0–200");
    expect(control<HTMLInputElement>("#u_turn_turn_radius_m")).toHaveAttribute("placeholder", "0–100");

    advance(3);
    expect(control<HTMLInputElement>("#max_iterations")).toHaveAttribute("placeholder", "1–100");
    expect(control<HTMLInputElement>("#min_pass_rate")).toHaveAttribute("placeholder", "0–1");
    expect(document.querySelectorAll(".wizard-panel .form-hint")).toHaveLength(0);
  });
});
