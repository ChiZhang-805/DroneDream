export type AutonomyAssetKind = "map" | "world" | "vehicle";
export type AutonomyConnectorAvailability =
  | "builtin"
  | "companion_required"
  | "plugin_required";
export type AutonomyExecutionBoundary =
  | "declarative_parser"
  | "isolated_local_companion"
  | "isolated_plugin";
export type AutonomyAssetMaturity =
  | "visual_only"
  | "physics_ready"
  | "simulation_ready"
  | "flight_ready"
  | "qualified";

export interface AutonomyAssetConnector {
  connector_id: string;
  name: string;
  source_application: string;
  source_formats: string[];
  asset_kinds: AutonomyAssetKind[];
  availability: AutonomyConnectorAvailability;
  execution_boundary: AutonomyExecutionBoundary;
  enabled: boolean;
  output_format: "ddpkg";
  maximum_import_maturity: AutonomyAssetMaturity;
}

export interface AutonomyAssetConnectorCatalog {
  schema_version: "dronedream.autonomy.asset-connector-catalog.v1";
  normalized_format: "ddpkg-v1";
  imported_code_execution: false;
  items: AutonomyAssetConnector[];
}

