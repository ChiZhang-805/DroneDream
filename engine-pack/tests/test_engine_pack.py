from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "engine-pack" / "tools" / "engine_pack.py"
SPEC = importlib.util.spec_from_file_location("engine_pack_tool", TOOL_PATH)
assert SPEC and SPEC.loader
engine_pack: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine_pack
SPEC.loader.exec_module(engine_pack)


class EnginePackTests(unittest.TestCase):
    def test_runtime_distribution_contract_whitelist_is_exact_and_hashed(self) -> None:
        files = engine_pack.production_files(ROOT)
        distribution_files = {
            path for path, _source in files if path.startswith("distribution/")
        }
        expected_distribution = {
            path
            for path in engine_pack.RUNTIME_DISTRIBUTION_PATHS
            if path.startswith("distribution/")
        }
        self.assertEqual(distribution_files, expected_distribution)
        self.assertFalse(
            any(
                path.startswith(
                    (
                        "distribution/build-planning/",
                        "distribution/build-plans/",
                        "distribution/tests/",
                    )
                )
                for path in distribution_files
            )
        )
        records = {record["path"]: record for record in engine_pack.file_records(files)}
        for relative in engine_pack.RUNTIME_DISTRIBUTION_PATHS:
            self.assertIn(relative, records)
            self.assertEqual(records[relative]["sha256"], engine_pack.sha256_file(ROOT / relative))

        runtime_spec = importlib.util.spec_from_file_location(
            "engine_pack_runtime_safety_gate_contract_test",
            ROOT / "runtime/scripts/edition-safety-gate.py",
        )
        assert runtime_spec and runtime_spec.loader
        runtime_gate = importlib.util.module_from_spec(runtime_spec)
        sys.modules[runtime_spec.name] = runtime_gate
        runtime_spec.loader.exec_module(runtime_gate)
        self.assertEqual(
            engine_pack.RUNTIME_DISTRIBUTION_PATHS,
            runtime_gate.RUNTIME_DISTRIBUTION_PATHS,
        )

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

    def test_build_refuses_to_replace_an_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            sentinel = output / engine_pack.MANIFEST_FILENAME
            sentinel.write_bytes(b"preserve me")

            with self.assertRaisesRegex(
                engine_pack.EnginePackError,
                "output directory must be absent or empty",
            ):
                self.build(output)

            self.assertEqual(sentinel.read_bytes(), b"preserve me")

    def test_source_timestamp_rejects_invalid_commit_before_invoking_git(self) -> None:
        with (
            mock.patch.dict(engine_pack.os.environ, {}, clear=True),
            mock.patch.object(engine_pack.shutil, "which") as which,
            self.assertRaisesRegex(engine_pack.EnginePackError, "full lowercase Git SHA"),
        ):
            engine_pack.source_date_epoch(ROOT, "--help")
        which.assert_not_called()

    def test_source_timestamp_fails_closed_when_git_is_unavailable(self) -> None:
        with (
            mock.patch.dict(engine_pack.os.environ, {}, clear=True),
            mock.patch.object(engine_pack.shutil, "which", return_value=None),
            self.assertRaisesRegex(engine_pack.EnginePackError, "git is required"),
        ):
            engine_pack.source_date_epoch(ROOT, "1" * 40)

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
            self.assertEqual(
                [name for name in names if name.startswith("payload/runtime/")],
                ["payload/runtime/THIRD_PARTY_NOTICES.md"],
            )

    def test_manifest_binds_runtime_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build(output)
            manifest = json.loads(
                (output / engine_pack.MANIFEST_FILENAME).read_text(encoding="utf-8")
            )
            compatibility = manifest["runtimeCompatibility"]
            self.assertEqual(compatibility["runtimeProductId"], "DroneDreamRuntime")
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
        pins = engine_pack.read_pins(ROOT / "runtime" / "pins.env")
        record = {"path": "../escape", "sizeBytes": 1, "sha256": "0" * 64}
        manifest = {
            "schemaVersion": 1,
            "kind": engine_pack.KIND,
            "packId": "sha256:" + "0" * 64,
            "engineApiVersion": 1,
            "source": {"gitCommit": "1" * 40, "sourceDateEpoch": 1},
            "runtimeCompatibility": {
                "runtimeProductId": "DroneDreamRuntime",
                "runtimeVersion": pins["DRONEDREAM_RUNTIME_VERSION"],
                "pythonVersion": pins["PYTHON_VERSION"],
                "px4Commit": pins["PX4_GIT_COMMIT"],
                "gazeboVersion": (f"{pins['GAZEBO_RELEASE']}@{pins['GAZEBO_METAPACKAGE_VERSION']}"),
                "dependencyLockSha256": engine_pack.sha256_file(
                    ROOT / "runtime" / "locks" / "python-requirements.lock"
                ),
            },
            "files": [record],
        }
        with self.assertRaisesRegex(engine_pack.EnginePackError, "unsafe archive member"):
            engine_pack.validate_manifest(manifest)

    def test_descriptor_cannot_redirect_the_manifest_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build(output)
            descriptor_path = output / engine_pack.DESCRIPTOR_FILENAME
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            descriptor["manifest"]["filename"] = "../outside.json"
            descriptor_path.write_bytes(engine_pack.canonical_json(descriptor))

            with self.assertRaisesRegex(engine_pack.EnginePackError, "filename does not match"):
                self.verify(output)

    def test_sidecar_manifest_must_match_the_embedded_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build(output)
            manifest_path = output / engine_pack.MANIFEST_FILENAME
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")

            with self.assertRaisesRegex(engine_pack.EnginePackError, "size does not match"):
                self.verify(output)

    def test_descriptor_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            self.build(output)
            descriptor_path = output / engine_pack.DESCRIPTOR_FILENAME
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            descriptor["unexpected"] = True
            descriptor_path.write_bytes(engine_pack.canonical_json(descriptor))

            with self.assertRaisesRegex(engine_pack.EnginePackError, "fields do not match"):
                self.verify(output)


if __name__ == "__main__":
    unittest.main()
