from __future__ import annotations

import configparser
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
SPEC = importlib.util.spec_from_file_location(
    "runtime_manifest", RUNTIME / "tools" / "runtime_manifest.py"
)
assert SPEC and SPEC.loader
runtime_manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_manifest)

CLEANUP_SPEC = importlib.util.spec_from_file_location(
    "px4_log_cleanup", RUNTIME / "scripts" / "px4-log-cleanup.py"
)
assert CLEANUP_SPEC and CLEANUP_SPEC.loader
px4_log_cleanup = importlib.util.module_from_spec(CLEANUP_SPEC)
sys.modules[CLEANUP_SPEC.name] = px4_log_cleanup
CLEANUP_SPEC.loader.exec_module(px4_log_cleanup)


class RuntimeManifestContractTests(unittest.TestCase):
    def _generate(self, directory: Path) -> tuple[dict, Path]:
        output = directory / "runtime-manifest.json"
        manifest = runtime_manifest.generate(
            RUNTIME / "pins.env",
            RUNTIME / "locks" / "python-requirements.lock",
            "a" * 40,
            output,
        )
        return manifest, output

    def test_generated_manifest_matches_desktop_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = self._generate(Path(directory))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(
            set(manifest["components"]) & {"backend", "px4", "gazebo"},
            {"backend", "px4", "gazebo"},
        )
        self.assertTrue(
            all(isinstance(value, str) for value in manifest["components"].values())
        )
        self.assertEqual(
            manifest["smokeTests"],
            {"px4Sitl": False, "gazebo": False, "parameterReadback": False},
        )
        runtime_manifest.validate_manifest(manifest)
        with self.assertRaises(runtime_manifest.ManifestError):
            runtime_manifest.validate_manifest(manifest, require_smoke_passed=True)

    def test_promotion_is_atomic_and_requires_every_real_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            manifest, manifest_path = self._generate(temp)
            report = {
                "mode": "runtime-image",
                "runtimeId": manifest["runtimeId"],
                "imageId": "sha256:test-only",
                "passed": True,
                "completedAt": "2026-07-11T00:00:00+00:00",
                "checks": [
                    {"name": name, "passed": True}
                    for name in sorted(runtime_manifest.REQUIRED_SMOKE_CHECKS)
                ],
            }
            report_path = temp / "report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            promoted_path = temp / "promoted.json"
            runtime_manifest.promote_smoke(manifest_path, report_path, promoted_path)
            promoted = json.loads(promoted_path.read_text(encoding="utf-8"))
            self.assertEqual(
                promoted["smokeTests"],
                {"px4Sitl": True, "gazebo": True, "parameterReadback": True},
            )
            runtime_manifest.validate_manifest(promoted, require_smoke_passed=True)

            report["checks"].pop()
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(runtime_manifest.ManifestError):
                runtime_manifest.promote_smoke(
                    manifest_path, report_path, promoted_path
                )

    def test_template_keeps_desktop_fields(self) -> None:
        template = json.loads((RUNTIME / "runtime-manifest.template.json").read_text())
        schema = json.loads((RUNTIME / "manifest.schema.json").read_text())
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)
        self.assertEqual(template["schemaVersion"], 1)
        self.assertEqual(set(template["components"]), {"backend", "px4", "gazebo"})
        self.assertEqual(
            set(template["smokeTests"]), {"px4Sitl", "gazebo", "parameterReadback"}
        )

    def test_contract_tracks_desktop_reader(self) -> None:
        desktop = (ROOT / "desktop" / "src-tauri" / "src" / "runtime.rs").read_text(
            encoding="utf-8"
        )
        for fragment in (
            'const RUNTIME_MANIFEST: &str = "/opt/dronedream/runtime-manifest.json";',
            "const BACKEND_PORT: u16 = 8000;",
            "schema_version: u32,",
            "version: String,",
            "components: BTreeMap<String, String>,",
            "px4_sitl: bool,",
            "gazebo: bool,",
            "parameter_readback: bool,",
        ):
            self.assertIn(fragment, desktop)


class ThirdPartyNoticeContractTests(unittest.TestCase):
    def test_notice_is_included_in_the_exported_rootfs_source_tree(self) -> None:
        notice = RUNTIME / "THIRD_PARTY_NOTICES.md"
        self.assertTrue(notice.is_file())
        self.assertTrue((RUNTIME / "licenses" / "valkey-COPYING").is_file())

        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        dockerignore = (RUNTIME / "Dockerfile.dockerignore").read_text(encoding="utf-8")
        self.assertIn("COPY . /opt/dronedream/source", dockerfile)
        self.assertIn("!LICENSE", dockerignore)
        self.assertIn("!runtime/**", dockerignore)
        self.assertNotIn("runtime/THIRD_PARTY_NOTICES.md", dockerignore)
        self.assertIn("/usr/share/doc/valkey/COPYING", dockerfile)
        self.assertIn("/usr/share/doc/dronedream-runtime/LICENSE", dockerfile)
        self.assertIn(
            "/usr/share/doc/dronedream-runtime/THIRD_PARTY_NOTICES.md",
            dockerfile,
        )
        self.assertIn("runtime/licenses/valkey-COPYING", dockerfile)

    def test_notice_tracks_current_primary_runtime_pins(self) -> None:
        notice = (RUNTIME / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        pins = runtime_manifest.load_pins(RUNTIME / "pins.env")
        for name in (
            "DRONEDREAM_RUNTIME_VERSION",
            "UBUNTU_VERSION",
            "PX4_VERSION",
            "PX4_GIT_COMMIT",
            "GAZEBO_RELEASE",
            "GAZEBO_METAPACKAGE_VERSION",
            "VALKEY_VERSION",
            "VALKEY_GIT_COMMIT",
        ):
            self.assertIn(pins[name], notice, name)
        self.assertIn("/usr/share/doc/*/copyright", notice)
        self.assertIn("/usr/share/doc/valkey/COPYING", notice)


@unittest.skipUnless(
    px4_log_cleanup.secure_dirfd_supported(),
    "secure ULog deletion is intentionally POSIX/WSL only",
)
class Px4LogCleanupTests(unittest.TestCase):
    NOW_NS = 2_000_000_000_000_000_000

    def _log(self, root: Path, name: str, *, size: int, age_seconds: int) -> Path:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        modified = self.NOW_NS - age_seconds * 1_000_000_000
        os.utime(path, ns=(modified, modified))
        return path

    def test_open_and_recent_logs_are_never_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            old = self._log(root, "old.ulg", size=100, age_seconds=7200)
            recent = self._log(root, "recent.ulg", size=50, age_seconds=10)
            identity = (old.stat().st_dev, old.stat().st_ino)
            protected = px4_log_cleanup.cleanup_logs(
                root,
                max_total_bytes=1,
                max_age_seconds=60,
                min_age_seconds=0,
                keep_recent=1,
                now_ns=self.NOW_NS,
                open_identities={identity},
            )
            self.assertEqual(protected.deleted_files, 0)
            self.assertEqual(protected.protected_open, 1)
            self.assertTrue(old.exists())
            self.assertTrue(recent.exists())

            cleaned = px4_log_cleanup.cleanup_logs(
                root,
                max_total_bytes=1,
                max_age_seconds=60,
                min_age_seconds=0,
                keep_recent=1,
                now_ns=self.NOW_NS,
                open_identities=set(),
            )
            self.assertEqual(cleaned.deleted_files, 1)
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertEqual(cleaned.capacity_excess_bytes, 49)

    def test_capacity_removes_oldest_eligible_ulogs_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first = self._log(root, "first.ulg", size=100, age_seconds=5000)
            second = self._log(root, "second.ulg", size=100, age_seconds=4000)
            newest = self._log(root, "newest.ulg", size=100, age_seconds=3000)
            note = self._log(root, "do-not-delete.txt", size=100, age_seconds=6000)
            result = px4_log_cleanup.cleanup_logs(
                root,
                max_total_bytes=150,
                max_age_seconds=0,
                min_age_seconds=0,
                keep_recent=1,
                now_ns=self.NOW_NS,
                open_identities=set(),
            )
            self.assertEqual(result.selected_by_capacity, 2)
            self.assertEqual(result.deleted_files, 2)
            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(newest.exists())
            self.assertTrue(note.exists())

    def test_symlinked_ulog_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "logs"
            root.mkdir()
            outside = self._log(base, "outside.ulg", size=100, age_seconds=7200)
            link = root / "linked.ulg"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            result = px4_log_cleanup.cleanup_logs(
                root,
                max_total_bytes=1,
                max_age_seconds=1,
                min_age_seconds=0,
                keep_recent=0,
                now_ns=self.NOW_NS,
                open_identities=set(),
            )
            self.assertEqual(result.scanned_files, 0)
            self.assertTrue(link.is_symlink())
            self.assertTrue(outside.exists())

    def test_parent_directory_symlink_replacement_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "managed"
            day = root / "day"
            original = self._log(day, "flight.ulg", size=100, age_seconds=7200)
            outside = base / "outside"
            outside_log = self._log(outside, "flight.ulg", size=100, age_seconds=7200)

            def replace_parent() -> None:
                day.rename(root / "day-original")
                day.symlink_to(outside, target_is_directory=True)

            result = px4_log_cleanup.cleanup_logs(
                root,
                max_total_bytes=1,
                max_age_seconds=1,
                min_age_seconds=0,
                keep_recent=0,
                now_ns=self.NOW_NS,
                open_identities=set(),
                _before_delete=replace_parent,
            )
            self.assertEqual(result.deleted_files, 0)
            self.assertGreaterEqual(result.skipped_changed_or_open, 1)
            self.assertTrue((root / "day-original" / original.name).exists())
            self.assertTrue(outside_log.exists())


class SystemdContractTests(unittest.TestCase):
    EXPECTED_EXECUTABLES = {
        "dronedream-runtime-init.service": ["/usr/lib/dronedream/runtime-init.sh"],
        "valkey.service": ["/usr/local/bin/valkey-server", "/bin/kill"],
        "dronedream-api.service": [
            "/opt/dronedream/venv/bin/alembic",
            "/opt/dronedream/venv/bin/uvicorn",
        ],
        "dronedream-worker.service": ["/opt/dronedream/venv/bin/drone-dream-worker"],
        "dronedream-px4-log-cleanup.service": ["/opt/dronedream/venv/bin/python"],
    }

    def test_unit_executables_and_non_root_services(self) -> None:
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        for filename, expected in self.EXPECTED_EXECUTABLES.items():
            text = (RUNTIME / "systemd" / filename).read_text(encoding="utf-8")
            actual = [
                line.split("=", 1)[1].split()[0]
                for line in text.splitlines()
                if line.startswith(("ExecStart=", "ExecStartPre=", "ExecStop="))
            ]
            self.assertEqual(actual, expected, filename)
            for executable in expected:
                if executable != "/bin/kill":
                    self.assertIn(executable, dockerfile, filename)
            if filename != "dronedream-runtime-init.service":
                self.assertRegex(text, r"(?m)^User=(?!root$).+$")
        api = (RUNTIME / "systemd" / "dronedream-api.service").read_text()
        self.assertIn("--port 8000", api)

    def test_context_excludes_large_desktop_build_outputs(self) -> None:
        ignore = (RUNTIME / "Dockerfile.dockerignore").read_text(encoding="utf-8")
        self.assertIn("**/target/**", ignore)
        self.assertIn("**/.env", ignore)
        self.assertNotIn("!desktop/", ignore)

    def test_px4_setup_runs_as_root_and_only_build_runs_unprivileged(self) -> None:
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        setup = dockerfile.index("bash Tools/setup/ubuntu.sh --no-nuttx")
        unprivileged = dockerfile.index("USER dronedream")
        build = dockerfile.index('make px4_sitl_default -j"${PX4_BUILD_JOBS}"')
        self.assertLess(setup, unprivileged)
        self.assertLess(unprivileged, build)
        self.assertNotIn("NOPASSWD", dockerfile)

    def test_smoke_uses_the_worker_sandbox_without_root_shortcuts(self) -> None:
        worker = (RUNTIME / "systemd" / "dronedream-worker.service").read_text(
            encoding="utf-8"
        )
        smoke = (RUNTIME / "smoke-image.sh").read_text(encoding="utf-8")
        keys = {
            "User",
            "Group",
            "NoNewPrivileges",
            "PrivateTmp",
            "ProtectSystem",
            "ProtectHome",
            "ReadWritePaths",
        }
        worker_properties = {
            key: value
            for line in worker.splitlines()
            if "=" in line
            for key, value in [line.split("=", 1)]
            if key in keys
        }
        block = re.search(r"sandbox_properties=\(\n(?P<body>.*?)\n\)", smoke, re.DOTALL)
        self.assertIsNotNone(block)
        smoke_properties = dict(
            item.split("=", 1)
            for item in re.findall(
                r'^\s+"([A-Za-z]+=[^"]+)"$', block["body"], re.MULTILINE
            )
        )
        self.assertEqual(smoke_properties, worker_properties)
        self.assertIn("/usr/bin/systemd-run", smoke)
        self.assertIn("--working-directory=/opt/dronedream/source", smoke)
        self.assertNotIn(
            'docker exec "$container" /usr/lib/dronedream/runtime-check.sh', smoke
        )
        self.assertIn("/var/lib/dronedream/runtime-smoke", smoke)
        self.assertNotIn("/tmp/dronedream-runtime-smoke", smoke)

    def test_journal_limits_are_packaged_and_disk_conservative(self) -> None:
        parser = configparser.ConfigParser()
        config_path = RUNTIME / "config" / "journald-dronedream.conf"
        parser.read(config_path, encoding="utf-8")
        journal = parser["Journal"]
        self.assertEqual(journal["Storage"], "persistent")
        self.assertEqual(journal["SystemMaxUse"], "512M")
        self.assertEqual(journal["RuntimeMaxUse"], "256M")
        self.assertEqual(journal["MaxRetentionSec"], "14day")
        self.assertEqual(journal["SystemKeepFree"], "20G")
        self.assertEqual(journal["RuntimeKeepFree"], "128M")
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "journald-dronedream.conf /etc/systemd/journald.conf.d/60-dronedream-runtime.conf",
            dockerfile,
        )
        self.assertIn("/var/log/journal", dockerfile)

    def test_px4_ulog_cleanup_limits_and_timer_are_packaged(self) -> None:
        self.assertEqual(px4_log_cleanup.MAX_TOTAL_BYTES, 4 * 1024 * 1024 * 1024)
        self.assertEqual(px4_log_cleanup.MAX_AGE_SECONDS, 14 * 24 * 60 * 60)
        self.assertEqual(px4_log_cleanup.MIN_AGE_SECONDS, 60 * 60)
        self.assertEqual(px4_log_cleanup.KEEP_RECENT, 20)
        timer = (RUNTIME / "systemd" / "dronedream-px4-log-cleanup.timer").read_text(
            encoding="utf-8"
        )
        self.assertIn("OnUnitActiveSec=1h", timer)
        self.assertIn("Persistent=true", timer)
        service = (
            RUNTIME / "systemd" / "dronedream-px4-log-cleanup.service"
        ).read_text(encoding="utf-8")
        self.assertIn("User=dronedream", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn(
            "ReadWritePaths=/opt/PX4-Autopilot/build/px4_sitl_default/rootfs/log",
            service,
        )
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("dronedream-px4-log-cleanup.timer", dockerfile)
        source = (RUNTIME / "scripts" / "px4-log-cleanup.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("os.O_DIRECTORY", source)
        self.assertIn("os.O_NOFOLLOW", source)
        self.assertIn("os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)", source)
        self.assertIn("os.unlink(leaf, dir_fd=parent_fd)", source)
        self.assertNotIn("item.path.unlink", source)

    def test_unsupported_ulog_dirfd_platform_fails_closed(self) -> None:
        if px4_log_cleanup.secure_dirfd_supported():
            self.skipTest("secure POSIX dirfd support is available")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(px4_log_cleanup.CleanupError):
                px4_log_cleanup.cleanup_logs(Path(directory))


if __name__ == "__main__":
    unittest.main()
