"""Returned scene descriptions must not mutate the server's planning registry."""

from __future__ import annotations

import pytest

from app.autonomy import catalog


@pytest.mark.parametrize("listing", (False, True))
def test_scene_consumers_receive_independent_nested_objects(listing: bool) -> None:
    original = catalog.SCENES["school-campus-v1"].model_copy(deep=True)
    try:
        scene = catalog.list_scenes()[0] if listing else catalog.get_scene("school-campus-v1")
        assert scene is not None
        scene.tags.append("consumer-local-tag")
        scene.objects[0].center.x += 5
        scene.reference_path[0].speed_limit_mps = 9
        assert catalog.SCENES["school-campus-v1"] == original
    finally:
        # Restore even against the old buggy implementation so other tests do
        # not inherit this deliberate ownership-boundary probe.
        catalog.SCENES["school-campus-v1"] = original


def test_unregistered_scene_has_no_implicit_fallback() -> None:
    assert catalog.get_scene("fixture-missing-scene") is None
    assert catalog.get_bundled_map_manifest("fixture-missing-scene") is None
