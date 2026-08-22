from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_agent_core_stage_carries_qualified_default_assets_into_the_installer() -> None:
    script = (ROOT / "desktop" / "scripts" / "stage-agent-core.ps1").read_text(encoding="utf-8-sig")
    for fragment in (
        '"default-assets\\index.json"',
        '"default-assets\\school-map.zip"',
        '"default-assets\\my-drone.zip"',
        '"default-assets\\school-map.ddpkg"',
        '"default-assets\\my-drone.ddpkg"',
        '@("runtime", "official-plugins", "default-assets")',
        "defaultAssetIndexSha256",
    ):
        assert fragment in script

    for edition in ("universal", "sim", "lab", "field", "autonomy"):
        config = json.loads(
            (ROOT / "desktop" / "src-tauri" / f"tauri.{edition}.conf.json").read_text(
                encoding="utf-8"
            )
        )
        resources = config["bundle"]["resources"]
        assert resources["agent-core-resources/default-assets"] == ("agent-core/default-assets")
