import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DistributionSetupPanel } from "../components/DistributionSetupPanel";
import {
  DISTRIBUTION_SELECTION_STORAGE_KEY,
  parseDistributionSelectionDraft,
} from "../features/distribution/installationSelection";
import { I18nProvider } from "../i18n/I18nProvider";

function renderPanel(variant: "settings" | "setup" = "setup") {
  return render(
    <I18nProvider>
      <DistributionSetupPanel variant={variant} />
    </I18nProvider>,
  );
}

function nativeBlockedPlan() {
  return {
    schemaVersion: 1,
    kind: "dronedream-distribution-plan-validation",
    planVersion: "1.0.0",
    productDisplayVersion: "1.0.0",
    sourceCommit: "a".repeat(40),
    sourceTreeClean: true,
    planSha256: "b".repeat(64),
    selection: {
      schemaVersion: 1,
      editionId: "sim",
      region: "global",
      vehiclePackId: "px4-gazebo-x500-reference",
      controllerKey: null,
      optionalModules: [],
    },
    catalog: {
      registryManifestSha256: "c".repeat(64),
      capabilityPolicySha256: "d".repeat(64),
      editionManifestSha256: "e".repeat(64),
      vehiclePackManifestSha256: "f".repeat(64),
      vehiclePackPayloadSha256: "1".repeat(64),
      vehiclePackSignatureState: "missing",
      validationTier: "contract-only",
    },
    requiredModules: ["desktop-core", "runtime-simulation"],
    optionalModules: [],
    capabilities: {
      defaultDecision: "deny",
      frontendIsAuthority: false,
      enabledOrConditioned: ["simulation.execute"],
      denied: ["hardware.arm", "hardware.flight", "hardware.parameter.write"],
    },
    rollback: { status: "missing", reference: null },
    blockers: [
      "native-apply-not-implemented",
      "rollback-reference-required",
      "vehicle-pack-signature-not-verified",
      "vehicle-pack-unvalidated",
    ],
    canApply: false,
    executionAuthorized: false,
  };
}

describe("DistributionSetupPanel", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    delete window.__TAURI__;
  });

  afterEach(() => {
    window.localStorage.clear();
    delete window.__TAURI__;
  });

  it("starts with the simulation reference and exposes no install action", () => {
    const { container } = renderPanel();

    expect(screen.getByRole("radio", { name: /DroneDream Sim/ })).toBeChecked();
    expect(screen.getByRole("combobox", { name: /Vehicle Pack/ })).toHaveValue(
      "px4-gazebo-x500-reference",
    );
    expect(screen.getByText("This browser saves a draft only. It cannot install modules or control hardware."))
      .toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(container.querySelector("[data-can-apply='false']")).toBeTruthy();
    expect(container.querySelector("[data-brand-edition='sim']")).toBeTruthy();
  });

  it("normalizes edition and region changes and persists only the versioned draft", () => {
    renderPanel("settings");

    fireEvent.click(screen.getByRole("radio", { name: /DroneDream · FIELD/ }));
    fireEvent.change(screen.getByRole("combobox", { name: /Region/ }), {
      target: { value: "cn" },
    });

    expect(screen.getByRole("combobox", { name: /Vehicle Pack/ })).toHaveValue(
      "amovlab-mfp450-pixhawk6c",
    );
    expect(screen.getByRole("combobox", { name: /Flight controller/ })).toHaveValue(
      "Holybro::Pixhawk 6C",
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "qgroundcontrol external" }));

    const saved = JSON.parse(
      window.localStorage.getItem(DISTRIBUTION_SELECTION_STORAGE_KEY) ?? "null",
    );
    expect(parseDistributionSelectionDraft(saved)).toEqual({
      schemaVersion: 1,
      editionId: "field",
      region: "cn",
      vehiclePackId: "amovlab-mfp450-pixhawk6c",
      controllerKey: "Holybro::Pixhawk 6C",
      optionalModules: ["qgroundcontrol-external"],
    });
    expect(JSON.stringify(saved)).not.toMatch(/password|api.?key|secret/i);
    expect(document.querySelector(".distribution-setup-panel"))
      .toHaveAttribute("data-brand-edition", "field");
    expect(document.querySelector(".distribution-setup-panel"))
      .toHaveAttribute("data-can-apply", "false");
  });

  it("fails closed to a safe default when stored state is malformed", () => {
    window.localStorage.setItem(DISTRIBUTION_SELECTION_STORAGE_KEY, JSON.stringify({
      schemaVersion: 1,
      editionId: "lab",
      region: "global",
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerKey: "Holybro::Pixhawk 6C",
      optionalModules: [],
      hardwareAuthorized: true,
    }));

    renderPanel();

    expect(screen.getByRole("radio", { name: /DroneDream Sim/ })).toBeChecked();
    expect(screen.getByRole("combobox", { name: /Vehicle Pack/ })).toHaveValue(
      "px4-gazebo-x500-reference",
    );
  });

  it("renders independent Simplified Chinese copy", () => {
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    renderPanel();

    expect(screen.getByRole("heading", { name: "版本与机型包" })).toBeInTheDocument();
    expect(screen.getByText("网页只保存选择草稿，不能安装模块或控制真机。"))
      .toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /机型包/ })).toHaveValue(
      "px4-gazebo-x500-reference",
    );
  });

  it("keeps desktop selection behind the source-bound native plan boundary", async () => {
    const invoke = vi.fn(async () => nativeBlockedPlan());
    window.__TAURI__ = { core: { invoke } };
    const { container } = renderPanel("settings");

    expect(screen.getByText((_, element) => (
      element?.tagName === "P"
      && element.textContent?.startsWith(
        "Nothing is installed from this panel. Native verification must approve a future plan.",
      ) === true
    ))).toBeInTheDocument();
    await waitFor(() => {
      expect(container.querySelector("[data-native-plan-status='blocked']")).toBeTruthy();
    });
    expect(screen.getByText(/Native plan checked and safely blocked · aaaaaaaa · 4 blockers/))
      .toBeInTheDocument();
    expect(invoke).toHaveBeenCalledWith("validate_distribution_plan", {
      request: {
        selection: nativeBlockedPlan().selection,
        rollbackReference: null,
      },
    });
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("renders native contract failures as a fail-closed preview", async () => {
    window.__TAURI__ = {
      core: { invoke: vi.fn(async () => ({ ...nativeBlockedPlan(), canApply: true })) },
    };
    const { container } = renderPanel("settings");

    await waitFor(() => {
      expect(container.querySelector("[data-native-plan-status='failed']")).toBeTruthy();
    });
    expect(screen.getByText(/Native plan check failed closed/)).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });
});
