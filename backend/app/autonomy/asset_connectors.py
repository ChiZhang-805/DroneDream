"""Strict catalog for external simulation-asset authoring connectors.

DroneDream validates and qualifies imported assets; it is not a general CAD or
DCC modeler. Native projects therefore cross an isolated companion or plugin
boundary and become inert ``.ddpkg`` packages before core services admit them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AssetKind = Literal["map", "world", "vehicle"]
ConnectorAvailability = Literal["builtin", "companion_required", "plugin_required"]
ExecutionBoundary = Literal[
    "declarative_parser",
    "isolated_local_companion",
    "isolated_plugin",
]
AssetMaturity = Literal[
    "visual_only",
    "physics_ready",
    "simulation_ready",
    "flight_ready",
    "qualified",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AutonomyAssetConnector(StrictModel):
    connector_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=3, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    source_application: str = Field(min_length=1, max_length=160)
    source_formats: list[str] = Field(min_length=1, max_length=64)
    asset_kinds: list[AssetKind] = Field(min_length=1, max_length=3)
    availability: ConnectorAvailability
    execution_boundary: ExecutionBoundary
    enabled: bool
    output_format: Literal["ddpkg"] = "ddpkg"
    maximum_import_maturity: AssetMaturity

    @model_validator(mode="after")
    def validate_trust_boundary(self) -> AutonomyAssetConnector:
        if self.execution_boundary == "declarative_parser" and self.availability != "builtin":
            raise ValueError("only built-in connectors may parse inside the core process")
        if self.enabled and self.availability != "builtin":
            raise ValueError("optional connectors require a healthy installed companion or plugin")
        return self


class AutonomyAssetConnectorCatalog(StrictModel):
    schema_version: Literal["dronedream.autonomy.asset-connector-catalog.v1"] = (
        "dronedream.autonomy.asset-connector-catalog.v1"
    )
    normalized_format: Literal["ddpkg-v1"] = "ddpkg-v1"
    imported_code_execution: Literal[False] = False
    items: list[AutonomyAssetConnector]


_CONNECTORS = (
    AutonomyAssetConnector(
        connector_id="dronedream.ddpkg",
        name="DroneDream Package",
        source_application="DroneDream",
        source_formats=["ddpkg"],
        asset_kinds=["map", "world", "vehicle"],
        availability="builtin",
        execution_boundary="declarative_parser",
        enabled=True,
        maximum_import_maturity="qualified",
    ),
    AutonomyAssetConnector(
        connector_id="gazebo.sdf",
        name="Gazebo SDF",
        source_application="Gazebo Sim",
        source_formats=["sdf", "world", "gazebo-model"],
        asset_kinds=["map", "world", "vehicle"],
        availability="builtin",
        execution_boundary="declarative_parser",
        enabled=True,
        maximum_import_maturity="simulation_ready",
    ),
    AutonomyAssetConnector(
        connector_id="ros2.urdf",
        name="ROS 2 URDF",
        source_application="ROS 2",
        source_formats=["urdf", "urdf-package"],
        asset_kinds=["vehicle"],
        availability="builtin",
        execution_boundary="declarative_parser",
        enabled=True,
        maximum_import_maturity="physics_ready",
    ),
    AutonomyAssetConnector(
        connector_id="ros2.xacro",
        name="ROS 2 Xacro",
        source_application="ROS 2",
        source_formats=["xacro", "xacro-package"],
        asset_kinds=["vehicle"],
        availability="companion_required",
        execution_boundary="isolated_local_companion",
        enabled=False,
        maximum_import_maturity="physics_ready",
    ),
    AutonomyAssetConnector(
        connector_id="blender.phobos",
        name="Blender + Phobos",
        source_application="Blender",
        source_formats=["blend", "smurf"],
        asset_kinds=["map", "world", "vehicle"],
        availability="companion_required",
        execution_boundary="isolated_local_companion",
        enabled=False,
        maximum_import_maturity="simulation_ready",
    ),
    AutonomyAssetConnector(
        connector_id="solidworks.urdf",
        name="SOLIDWORKS",
        source_application="SOLIDWORKS",
        source_formats=["sldasm", "sldprt", "step"],
        asset_kinds=["vehicle"],
        availability="plugin_required",
        execution_boundary="isolated_plugin",
        enabled=False,
        maximum_import_maturity="physics_ready",
    ),
    AutonomyAssetConnector(
        connector_id="autodesk.fusion",
        name="Autodesk Fusion",
        source_application="Autodesk Fusion",
        source_formats=["f3d", "f3z", "step"],
        asset_kinds=["map", "vehicle"],
        availability="plugin_required",
        execution_boundary="isolated_plugin",
        enabled=False,
        maximum_import_maturity="physics_ready",
    ),
    AutonomyAssetConnector(
        connector_id="onshape.translation",
        name="Onshape",
        source_application="Onshape",
        source_formats=["onshape-document", "step"],
        asset_kinds=["map", "vehicle"],
        availability="plugin_required",
        execution_boundary="isolated_plugin",
        enabled=False,
        maximum_import_maturity="physics_ready",
    ),
    AutonomyAssetConnector(
        connector_id="freecad.robotics",
        name="FreeCAD",
        source_application="FreeCAD",
        source_formats=["fcstd", "step"],
        asset_kinds=["map", "vehicle"],
        availability="companion_required",
        execution_boundary="isolated_local_companion",
        enabled=False,
        maximum_import_maturity="physics_ready",
    ),
    AutonomyAssetConnector(
        connector_id="gis.gdal",
        name="GIS / DEM",
        source_application="GDAL / QGIS",
        source_formats=["geotiff", "dem", "osm", "citygml", "las", "laz"],
        asset_kinds=["map", "world"],
        availability="companion_required",
        execution_boundary="isolated_local_companion",
        enabled=False,
        maximum_import_maturity="visual_only",
    ),
)


def get_asset_connector_catalog() -> AutonomyAssetConnectorCatalog:
    return AutonomyAssetConnectorCatalog(items=[item.model_copy(deep=True) for item in _CONNECTORS])


__all__ = [
    "AutonomyAssetConnector",
    "AutonomyAssetConnectorCatalog",
    "get_asset_connector_catalog",
]

