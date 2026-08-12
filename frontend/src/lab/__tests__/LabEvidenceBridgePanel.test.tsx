import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { LabEvidenceBridgePanel } from "../LabEvidenceBridgePanel";
import fieldFixture from "../__fixtures__/field-harness-receipt.fake.json";
import simFixture from "../__fixtures__/sim-qualification-bridge.fake.json";

function renderPanel(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("drone-dream:locale", locale);
  return render(<I18nProvider><LabEvidenceBridgePanel /></I18nProvider>);
}

function fixtureFile(name: string, value: unknown): File {
  const source = JSON.stringify(value);
  const file = new File([source], name, { type: "application/json" });
  Object.defineProperty(file, "text", { value: async () => source });
  return file;
}

describe("Lab SIM / FIELD evidence bridge panel", () => {
  it("verifies both identities while keeping calibration and authority denied", async () => {
    const user = userEvent.setup();
    const { container } = renderPanel();

    const root = container.querySelector(".lab-evidence-bridge");
    expect(root).toHaveAttribute("data-presentation-only", "true");
    expect(root).toHaveAttribute("data-grants-hardware-authority", "false");

    await user.upload(
      screen.getByLabelText("Import SIM receipt"),
      fixtureFile("sim-qualified.fake.json", simFixture),
    );
    await user.upload(
      screen.getByLabelText("Import FIELD receipt"),
      fixtureFile("field-recorded.fake.json", fieldFixture),
    );

    expect(await screen.findByText("Candidate lineage matched · normalization required"))
      .toBeInTheDocument();
    expect(screen.getByText(/field-recorded\.fake\.json · Integrity verified/))
      .toBeInTheDocument();
    expect(screen.getByText("Recorded evidence passed")).toBeInTheDocument();
    expect(screen.getByText("Remaining gates · 5")).toBeInTheDocument();
    expect(root).toHaveAttribute("data-bridge-state", "normalization-required");
    expect(screen.getByText("Evidence import never grants hardware authority."))
      .toBeInTheDocument();
  });

  it("fails closed when the Field product source drifts", async () => {
    const user = userEvent.setup();
    renderPanel();
    const drifted = { ...fieldFixture, sourceCommit: "0".repeat(40) };

    await user.upload(
      screen.getByLabelText("Import FIELD receipt"),
      fixtureFile("field-drifted.json", drifted),
    );

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Evidence rejected")).toBeInTheDocument();
    expect(within(alert).getByText(/accepted product source/)).toBeInTheDocument();
    expect(screen.getByText("Waiting for both receipts")).toBeInTheDocument();
  });

  it("provides independently authored Chinese bridge copy", () => {
    renderPanel("zh-CN");

    expect(screen.getByRole("heading", { name: "SIM / FIELD 证据桥" }))
      .toBeInTheDocument();
    expect(screen.getByText("等待两侧 receipt")).toBeInTheDocument();
    expect(screen.getByText("导入证据绝不授予真机权限。")).toBeInTheDocument();
  });
});
