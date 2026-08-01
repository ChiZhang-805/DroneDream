from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "engine-pack" / "tools" / "engine_pack.py"
SPEC = importlib.util.spec_from_file_location("engine_pack_tool", TOOL_PATH)
assert SPEC and SPEC.loader
engine_pack: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine_pack
SPEC.loader.exec_module(engine_pack)


class EnginePackTests(unittest.TestCase):
    def build(self, output: Path) -> None:
        commit = "1" * 40
        previous = engine_pack.source_date_epoch
        engine_pack.source_date_epoch = lambda _root, _commit: 1_722_000_000
        try:
            result = engine_pack.build(
                type(
                    "Args",
                    (),
                    {
                        "repository_root": str(ROOT),
                        "output_directory": str(output),
                        "source_commit": commit,
                    },
                )()
            )
        finally:
            engine_pack.source_date_epoch = previous
        self.assertEqual(result, 0)

    def verify(self, output: Path) -> None:
        result = engine_pack.verify(
            type(
                "Args",
                (),
                {
                    "descriptor": str(output / engine_pack.DESCRIPTOR_FILENAME),
                    "archive": str(output / engine_pack.ARCHIVE_FILENAME),
                },
            )()
        )
        self.assertEqual(result, 0)

    def test_build_is_deterministic_and_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first"
            second = Path(temporary) / "second"
            self.build(first)
            self.build(second)
            self.assertEqual(
                (first / engine_pack.ARCHIVE_FILENAME).read_bytes(),
                (second / engine_pack.ARCHIVE_FILENAME).read_bytes(),
            )
            self.assertEqual(
                (first / engine_pack.DESCRIPTOR_FILENAME).read_bytes(),
                (second / engine_pack.DESCRIPTOR_FILENAME).read_bytes(),
            )
            self.verify(first)

    def test_pack_contains_only_production_application_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build(output)
            with tarfile.open(output / engine_pack.ARCHIVE_FILENAME, mode="r:gz") as archive:
                names = [member.name for member in archive.getmembers()]
            self.assertIn("payload/backend/app/main.py", names)
            self.assertIn("payload/worker/drone_dream_worker/main.py", names)
            self.assertIn("payload/scripts/simulators/px4_gazebo_runner.py", names)
            self.assertFalse(any("/tests/" in name for name in names))
            self.assertFalse(any(name.startswith("payload/frontend/") for name in names))
            self.assertFalse(any(name.startswith("payload/runtime/") for name in names))

    def test_manifest_binds_runtime_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build(output)
            manifest = json.loads(
                (output / engine_pack.MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            compatibility = manifest["runtimeCompatibility"]
            self.assertEqual(compatibility["runtimeId"], "DroneDreamRuntime")
            self.assertRegex(compatibility["px4Commit"], r"^[0-9a-f]{40}$")
            self.assertRegex(compatibility["dependencyLockSha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(manifest["source"]["gitCommit"], "1" * 40)

    def test_archive_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build(output)
            archive = output / engine_pack.ARCHIVE_FILENAME
            archive.write_bytes(archive.read_bytes() + b"tampered")
            with self.assertRaisesRegex(engine_pack.EnginePackError, "size does not match"):
                self.verify(output)

    def test_duplicate_or_traversal_manifest_paths_are_rejected(self) -> None:
        record = {"path": "../escape", "sizeBytes": 1, "sha256": "0" * 64}
        manifest = {
            "schemaVersion": 1,
            "kind": engine_pack.KIND,
            "packId": "sha256:" + "0" * 64,
            "engineApiVersion": 1,
            "source": {"gitCommit": "1" * 40, "sourceDateEpoch": 1},
            "runtimeCompatibility": {},
            "files": [record],
        }
        with self.assertRaisesRegex(engine_pack.EnginePackError, "unsafe archive member"):
            engine_pack.validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
