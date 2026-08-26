from __future__ import annotations

import json
from pathlib import Path

from dronedream_agent_core.assets import load_school_map_catalog


def _write_semantic(path: Path, *, include_pickup_binding: bool) -> None:
    bindings: dict[str, object] = {"mission_launch_waypoint": {"x": -42.25, "y": 15.3, "z": 7.95}}
    if include_pickup_binding:
        bindings["mission_pickup_waypoint"] = {"x": 48.5, "y": 1.25, "z": 1.35}
    path.write_text(
        json.dumps(
            {
                "schema_version": "dronedream.autonomy.school-map-semantic.v1",
                "coordinate_frame": "ENU",
                "compiler_scene_id": "school-map",
                "roads": {
                    "facility_anchors": {"takeout-pickup": [48.5, 1.5, 1.5]},
                    "segments": [],
                },
                "simulation_bindings": bindings,
            }
        ),
        encoding="utf-8",
    )


def test_pickup_binding_owns_natural_language_pickup_alias(tmp_path: Path) -> None:
    semantic_path = tmp_path / "semantic.json"
    _write_semantic(semantic_path, include_pickup_binding=True)

    catalog = load_school_map_catalog(semantic_path)
    alias_owners = [entity.entity_id for entity in catalog.entities if "外卖点" in entity.aliases]

    assert alias_owners == ["takeout-pickup-pad"]


def test_launch_binding_includes_natural_office_landing_phrases(tmp_path: Path) -> None:
    semantic_path = tmp_path / "semantic.json"
    _write_semantic(semantic_path, include_pickup_binding=True)

    catalog = load_school_map_catalog(semantic_path)
    launch = next(entity for entity in catalog.entities if entity.entity_id == "office-launch-pad")

    assert "办公室起降坪" in launch.aliases
    assert "三楼办公室起降坪" in launch.aliases


def test_facility_anchor_keeps_pickup_alias_without_action_binding(tmp_path: Path) -> None:
    semantic_path = tmp_path / "semantic.json"
    _write_semantic(semantic_path, include_pickup_binding=False)

    catalog = load_school_map_catalog(semantic_path)
    alias_owners = [entity.entity_id for entity in catalog.entities if "外卖点" in entity.aliases]

    assert alias_owners == ["takeout-pickup"]
