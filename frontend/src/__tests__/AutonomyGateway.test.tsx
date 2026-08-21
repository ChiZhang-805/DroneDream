import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import type { AutonomyAssetConnectorCatalog } from "../features/autonomy/assetConnectors";
import { I18nProvider } from "../i18n/I18nProvider";
import { AutonomyGateway } from "../pages/AutonomyGateway";

const catalog: AutonomyAssetConnectorCatalog = {
  schema_version: "dronedream.autonomy.asset-connector-catalog.v1",
  normalized_format: "ddpkg-v1",
  imported_code_execution: false,
  items: [
    {
      connector_id: "gazebo.sdf",
      name: "Gazebo SDF",
      source_application: "Gazebo Sim",
      source_formats: ["sdf", "world"],
      asset_kinds: ["map", "world", "vehicle"],
      availability: "builtin",
      execution_boundary: "declarative_parser",
      enabled: true,
      output_format: "ddpkg",
      maximum_import_maturity: "simulation_ready",
    },
    {
      connector_id: "blender.phobos",
      name: "Blender + Phobos",
      source_application: "Blender",
      source_formats: ["blend"],
      asset_kinds: ["vehicle"],
      availability: "companion_required",
      execution_boundary: "isolated_local_companion",
      enabled: false,
      output_format: "ddpkg",
      maximum_import_maturity: "simulation_ready",
    },
  ],
};

describe("AutonomyGateway", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("separates built-in and isolated connector boundaries", async () => {
    vi.spyOn(apiClient, "getAutonomyAssetConnectors").mockResolvedValue(catalog);
    window.localStorage.setItem("drone-dream:locale", "en");

    render(
      <I18nProvider>
        <MemoryRouter>
          <AutonomyGateway />
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(await screen.findByText("Gazebo SDF")).toBeVisible();
    expect(screen.getByText("Blender + Phobos")).toBeVisible();
    expect(screen.getByText("Imported code never runs by default")).toBeVisible();
    expect(screen.getByRole("link", { name: /new task/i }))
      .toHaveAttribute("href", "/assistant?workspace=autonomy");
    expect(screen.getAllByText("Simulation ready")).toHaveLength(2);
  });

  it("keeps the Chinese surface Chinese except for product and format names", async () => {
    vi.spyOn(apiClient, "getAutonomyAssetConnectors").mockResolvedValue(catalog);
    window.localStorage.setItem("drone-dream:locale", "zh-CN");

    render(
      <I18nProvider>
        <MemoryRouter>
          <AutonomyGateway />
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(await screen.findByText("可直接导入")).toBeVisible();
    expect(screen.getByText("桥接器与插件")).toBeVisible();
    expect(screen.getByText("导入代码默认不执行")).toBeVisible();
    expect(screen.getByText("需要本地桥接器")).toBeVisible();
  });
});
