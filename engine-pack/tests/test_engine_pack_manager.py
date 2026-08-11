from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


engine_pack = load("engine_pack_for_manager_tests", ROOT / "engine-pack/tools/engine_pack.py")
manager = load("engine_pack_manager", ROOT / "runtime/scripts/engine-pack-manager.py")


class EnginePackManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / "bundle"
        previous = engine_pack.source_date_epoch
        engine_pack.source_date_epoch = lambda _root, _commit: 1_722_000_000
        try:
            engine_pack.build(
                type(
                    "Args",
                    (),
                    {
                        "repository_root": str(ROOT),
                        "output_directory": str(self.output),
                        "source_commit": "2" * 40,
                        "edition_profile": engine_pack.DEFAULT_EDITION_PROFILE,
                    },
                )()
            )
        finally:
            engine_pack.source_date_epoch = previous
        pins = engine_pack.read_pins(ROOT / "runtime/pins.env")
        self.runtime_manifest = self.root / "runtime-manifest.json"
        self.runtime_manifest.write_text(
            json.dumps(
                {
                    "runtimeId": "c75ae324-c247-50b5-bd74-fa8325e9e616",
                    "version": pins["DRONEDREAM_RUNTIME_VERSION"],
                    "componentDetails": {
                        "px4": {"commit": pins["PX4_GIT_COMMIT"]},
                        "gazebo": {
                            "release": pins["GAZEBO_RELEASE"],
                            "packageVersion": pins["GAZEBO_METAPACKAGE_VERSION"],
                        },
                        "python": {"version": pins["PYTHON_VERSION"]},
                    },
                    "locks": {
                        "pythonRequirementsSha256": engine_pack.sha256_file(
                            ROOT / "runtime/locks/python-requirements.lock"
                        )
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def install(self) -> dict[str, object]:
        return manager.install_pack(
            descriptor_path=self.output / engine_pack.DESCRIPTOR_FILENAME,
            archive_path=self.output / engine_pack.ARCHIVE_FILENAME,
            runtime_manifest_path=self.runtime_manifest,
            engine_root=self.root / "engine",
            state_path=self.root / "state/engine-pack-state.json",
            manage_services=False,
        )

    def test_install_activates_versioned_slot_without_touching_user_data(self) -> None:
        user_data = self.root / "state/user-job.json"
        user_data.parent.mkdir()
        user_data.write_text("preserve-me", encoding="utf-8")
        receipt = self.install()
        current = self.root / "engine/current"
        self.assertTrue(current.is_symlink())
        self.assertTrue((current / "backend/app/main.py").is_file())
        self.assertTrue((current / "worker/drone_dream_worker/main.py").is_file())
        self.assertEqual(user_data.read_text(encoding="utf-8"), "preserve-me")
        self.assertEqual(receipt["sourceCommit"], "2" * 40)
        self.assertEqual(
            receipt["runtimeId"], "c75ae324-c247-50b5-bd74-fa8325e9e616"
        )

    def test_reinstall_of_same_pack_is_idempotent(self) -> None:
        first = self.install()
        first_target = (self.root / "engine/current").resolve()
        second = self.install()
        self.assertEqual(first["currentPackId"], second["currentPackId"])
        self.assertEqual((self.root / "engine/current").resolve(), first_target)
        self.assertEqual(first["activatedAt"], second["activatedAt"])
        self.assertEqual(first["activatedAt"], "2024-07-26T13:20:00+00:00")

    def test_incompatible_runtime_is_rejected_before_activation(self) -> None:
        payload = json.loads(self.runtime_manifest.read_text(encoding="utf-8"))
        payload["componentDetails"]["px4"]["commit"] = "0" * 40
        self.runtime_manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(manager.EnginePackInstallError, "different Runtime Base"):
            self.install()
        self.assertFalse((self.root / "engine/current").exists())

    def test_runtime_product_name_cannot_masquerade_as_build_identity(self) -> None:
        payload = json.loads(self.runtime_manifest.read_text(encoding="utf-8"))
        payload["runtimeId"] = "DroneDreamRuntime"
        self.runtime_manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(manager.EnginePackInstallError, "build identity"):
            self.install()
        self.assertFalse((self.root / "engine/current").exists())

    def test_existing_release_is_reverified_before_idempotent_activation(self) -> None:
        self.install()
        main = self.root / "engine/current/backend/app/main.py"
        main.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(manager.EnginePackInstallError, "failed verification"):
            self.install()

    def test_existing_release_rejects_unlisted_executable_source(self) -> None:
        self.install()
        unlisted = self.root / "engine/current/backend/sitecustomize.py"
        unlisted.write_text("raise RuntimeError('must never execute')\n", encoding="utf-8")

        with self.assertRaisesRegex(manager.EnginePackInstallError, "unlisted path"):
            self.install()

    def test_current_ordinary_file_is_rejected_and_preserved(self) -> None:
        engine_root = self.root / "engine"
        engine_root.mkdir(parents=True)
        current = engine_root / "current"
        current.write_text("preserve-me", encoding="utf-8")

        with self.assertRaisesRegex(manager.EnginePackInstallError, "managed symlink"):
            self.install()

        self.assertTrue(current.is_file())
        self.assertEqual(current.read_text(encoding="utf-8"), "preserve-me")

    def test_release_target_symlink_is_rejected(self) -> None:
        descriptor = json.loads(
            (self.output / engine_pack.DESCRIPTOR_FILENAME).read_text(encoding="utf-8")
        )
        release_id = descriptor["packId"].removeprefix("sha256:")
        releases = self.root / "engine/releases"
        releases.mkdir(parents=True)
        outside = self.root / "outside-release"
        outside.mkdir()
        (releases / release_id).symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(manager.EnginePackInstallError, "ordinary directory"):
            self.install()

    def test_current_release_outside_managed_root_is_rejected(self) -> None:
        engine_root = self.root / "engine"
        (engine_root / "releases").mkdir(parents=True)
        outside = self.root / ("a" * 64)
        outside.mkdir()
        (engine_root / "current").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(manager.EnginePackInstallError, "outside"):
            self.install()

    def test_active_experiment_blocks_update_before_services_are_stopped(self) -> None:
        database = self.root / "state/dronedream.db"
        database.parent.mkdir()
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            connection.execute("CREATE TABLE trials (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            connection.execute("INSERT INTO jobs VALUES ('job-1', 'RUNNING')")
            connection.execute("INSERT INTO trials VALUES ('trial-1', 'RUNNING')")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(manager.EnginePackInstallError, "active experiments"):
            manager.ensure_no_active_experiments(database)

    def test_completed_experiments_do_not_block_update(self) -> None:
        database = self.root / "state/dronedream.db"
        database.parent.mkdir()
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            connection.execute("CREATE TABLE trials (id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            connection.execute("INSERT INTO jobs VALUES ('job-1', 'COMPLETED')")
            connection.execute("INSERT INTO trials VALUES ('trial-1', 'COMPLETED')")
            connection.commit()
        finally:
            connection.close()
        manager.ensure_no_active_experiments(database)

    def test_systemctl_rejects_unapproved_actions_and_services(self) -> None:
        with self.assertRaisesRegex(manager.EnginePackInstallError, "action"):
            manager.run_systemctl("restart", manager.ENGINE_SERVICES)
        with self.assertRaisesRegex(manager.EnginePackInstallError, "service"):
            manager.run_systemctl("stop", ("unrelated.service",))

    def test_race_window_recheck_reopens_api_without_stopping_worker(self) -> None:
        self.install()
        events: list[tuple[str, tuple[str, ...]]] = []

        def record_systemctl(action: str, services: tuple[str, ...]) -> None:
            events.append((action, services))

        with (
            mock.patch.object(
                manager,
                "ensure_no_active_experiments",
                side_effect=[
                    None,
                    manager.EnginePackInstallError(
                        "Engine Pack update is waiting for active experiments to finish"
                    ),
                ],
            ),
            mock.patch.object(manager, "run_systemctl", side_effect=record_systemctl),
            self.assertRaisesRegex(manager.EnginePackInstallError, "active experiments"),
        ):
            manager.install_pack(
                descriptor_path=self.output / engine_pack.DESCRIPTOR_FILENAME,
                archive_path=self.output / engine_pack.ARCHIVE_FILENAME,
                runtime_manifest_path=self.runtime_manifest,
                engine_root=self.root / "engine",
                state_path=self.root / "state/engine-pack-state.json",
                manage_services=True,
            )

        self.assertEqual(
            events,
            [
                ("stop", ("dronedream-api.service",)),
                ("start", ("dronedream-api.service", "dronedream-worker.service")),
            ],
        )


if __name__ == "__main__":
    unittest.main()
