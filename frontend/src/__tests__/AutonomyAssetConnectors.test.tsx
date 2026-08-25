import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import { AutonomyAssetConnectorPanel } from "../pages/AutonomyPlatform";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AUTONOMY external asset connectors", () => {
  it("separates built-in and isolated vehicle connectors in Chinese", async () => {
    vi.spyOn(apiClient, "listAutonomyAssetConnectors").mockResolvedValue({
      schema_version: "dronedream.autonomy.asset-connector-catalog.v1",
      normalized_format: "ddpkg-v1",
      imported_code_execution: false,
      items: [
        {
          connector_id: "ros2.urdf",
          name: "ROS 2 URDF",
          source_application: "ROS 2",
          source_formats: ["urdf"],
          asset_kinds: ["vehicle"],
          availability: "builtin",
          execution_boundary: "declarative_parser",
          enabled: true,
          output_format: "ddpkg",
          maximum_import_maturity: "physics_ready",
        },
        {
          connector_id: "blender.phobos",
          name: "Blender + Phobos",
          source_application: "Blender",
          source_formats: ["blend", "smurf"],
          asset_kinds: ["map", "world", "vehicle"],
          availability: "companion_required",
          execution_boundary: "isolated_local_companion",
          enabled: false,
          output_format: "ddpkg",
          maximum_import_maturity: "simulation_ready",
        },
      ],
    });

    render(<AutonomyAssetConnectorPanel kind="vehicle" chinese />);

    expect(await screen.findByText("ROS 2 URDF")).toBeVisible();
    expect(screen.getByText("内置可用")).toBeVisible();
    expect(screen.getByText("Blender + Phobos")).toBeVisible();
    expect(screen.getByText("需要本机配套程序")).toBeVisible();
  });

  it("filters map connectors and keeps the English surface English", async () => {
    vi.spyOn(apiClient, "listAutonomyAssetConnectors").mockResolvedValue({
      schema_version: "dronedream.autonomy.asset-connector-catalog.v1",
      normalized_format: "ddpkg-v1",
      imported_code_execution: false,
      items: [
        {
          connector_id: "gis.gdal",
          name: "GIS / DEM",
          source_application: "GDAL / QGIS",
          source_formats: ["geotiff", "dem"],
          asset_kinds: ["map", "world"],
          availability: "companion_required",
          execution_boundary: "isolated_local_companion",
          enabled: false,
          output_format: "ddpkg",
          maximum_import_maturity: "visual_only",
        },
        {
          connector_id: "ros2.urdf",
          name: "ROS 2 URDF",
          source_application: "ROS 2",
          source_formats: ["urdf"],
          asset_kinds: ["vehicle"],
          availability: "builtin",
          execution_boundary: "declarative_parser",
          enabled: true,
          output_format: "ddpkg",
          maximum_import_maturity: "physics_ready",
        },
      ],
    });

    render(<AutonomyAssetConnectorPanel kind="map" chinese={false} />);

    expect(await screen.findByText("GIS / DEM")).toBeVisible();
    expect(screen.getByText("Companion required")).toBeVisible();
    expect(screen.queryByText("ROS 2 URDF")).not.toBeInTheDocument();
    expect(screen.queryByText(/[\u3400-\u9fff]/u)).not.toBeInTheDocument();
  });
});
