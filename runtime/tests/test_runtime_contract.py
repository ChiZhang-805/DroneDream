from __future__ import annotations

import configparser
import importlib.util
import json
import os
import re
import sys
import tempfile
import tomllib
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
        self.assertTrue(all(isinstance(value, str) for value in manifest["components"].values()))
        self.assertEqual(
            manifest["smokeTests"],
            {"px4Sitl": False, "gazebo": False, "parameterReadback": False},
        )
        runtime_manifest.validate_manifest(manifest)
        with self.assertRaises(runtime_manifest.ManifestError):
            runtime_manifest.validate_manifest(manifest, require_smoke_passed=True)

    def test_python_component_pins_match_the_exact_lock(self) -> None:
        pins = runtime_manifest.load_pins(RUNTIME / "pins.env")
        packages = runtime_manifest.validate_python_lock(
            RUNTIME / "locks" / "python-requirements.lock"
        )
        runtime_manifest.validate_pin_lock_versions(pins, packages)
        packages["mavsdk"] = "0.0.0"
        with self.assertRaisesRegex(runtime_manifest.ManifestError, "MAVSDK_VERSION"):
            runtime_manifest.validate_pin_lock_versions(pins, packages)

    def test_source_package_versions_match_runtime_pins(self) -> None:
        pins = runtime_manifest.load_pins(RUNTIME / "pins.env")
        backend = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
        worker = tomllib.loads((ROOT / "worker" / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(backend["project"]["version"], pins["BACKEND_VERSION"])
        self.assertEqual(worker["project"]["version"], pins["WORKER_VERSION"])

    def test_runtime_test_entrypoints_use_the_pinned_pytest_contract(self) -> None:
        workflows = (
            ROOT / ".github" / "workflows" / "runtime-contract.yml",
            ROOT / ".github" / "workflows" / "quality-gate.yml",
            ROOT / ".github" / "workflows" / "runtime-release.yml",
        )
        for workflow in workflows:
            content = workflow.read_text(encoding="utf-8")
            with self.subTest(workflow=workflow.name):
                self.assertIn('"pytest==9.1.1"', content)
                self.assertIn("python -m pytest runtime/tests -q", content)
                self.assertNotIn("unittest discover -s runtime/tests", content)

        check_script_path = ROOT / "scripts" / "check-runtime.sh"
        if check_script_path.exists():
            check_script = check_script_path.read_text(encoding="utf-8")
            self.assertIn("pytest==9.1.1", check_script)
            self.assertIn('"$RUNTIME_PYTHON" -m pytest runtime/tests -q', check_script)
            self.assertNotIn("unittest discover -s runtime/tests", check_script)

        readme = (RUNTIME / "README.md").read_text(encoding="utf-8")
        self.assertIn("python -m pytest runtime/tests -q", readme)
        self.assertNotIn("unittest discover -s runtime/tests", readme)

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
                    {"name": name, "passed": True, "durationSeconds": 1}
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
                runtime_manifest.promote_smoke(manifest_path, report_path, promoted_path)

    def test_manifest_validation_fails_cleanly_for_malformed_shapes(self) -> None:
        for malformed in (None, [], "manifest", 1):
            with (
                self.subTest(malformed=malformed),
                self.assertRaisesRegex(
                    runtime_manifest.ManifestError, "runtime manifest must be an object"
                ),
            ):
                runtime_manifest.validate_manifest(malformed)

        with tempfile.TemporaryDirectory() as directory:
            manifest, _ = self._generate(Path(directory))
            manifest["unsupported"] = True
            with self.assertRaisesRegex(runtime_manifest.ManifestError, "unsupported"):
                runtime_manifest.validate_manifest(manifest)

    def test_promotion_rejects_incomplete_or_duplicated_smoke_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            manifest, manifest_path = self._generate(temp)
            checks = [
                {"name": name, "passed": True, "durationSeconds": 1}
                for name in sorted(runtime_manifest.REQUIRED_SMOKE_CHECKS)
            ]
            report = {
                "mode": "runtime-image",
                "runtimeId": manifest["runtimeId"],
                "imageId": "sha256:test-only",
                "passed": True,
                "completedAt": "2026-07-11T00:00:00+00:00",
                "checks": checks,
            }
            report_path = temp / "report.json"
            output_path = temp / "promoted.json"

            for mutation in (
                "missing_timestamp",
                "duplicate_check",
                "negative_duration",
            ):
                candidate = json.loads(json.dumps(report))
                if mutation == "missing_timestamp":
                    candidate.pop("completedAt")
                elif mutation == "duplicate_check":
                    candidate["checks"].append(dict(candidate["checks"][0]))
                else:
                    candidate["checks"][0]["durationSeconds"] = -1
                report_path.write_text(json.dumps(candidate), encoding="utf-8")
                with (
                    self.subTest(mutation=mutation),
                    self.assertRaises(runtime_manifest.ManifestError),
                ):
                    runtime_manifest.promote_smoke(manifest_path, report_path, output_path)

    def test_template_keeps_desktop_fields(self) -> None:
        template = json.loads((RUNTIME / "runtime-manifest.template.json").read_text())
        schema = json.loads((RUNTIME / "manifest.schema.json").read_text())
        self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)
        self.assertEqual(set(schema["required"]), set(template))
        self.assertEqual(template["schemaVersion"], 1)
        self.assertEqual(set(template["components"]), {"backend", "px4", "gazebo"})
        self.assertEqual(set(template["smokeTests"]), {"px4Sitl", "gazebo", "parameterReadback"})

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

    def test_services_execute_the_atomically_activated_engine_pack(self) -> None:
        api = (RUNTIME / "systemd" / "dronedream-api.service").read_text(encoding="utf-8")
        worker = (RUNTIME / "systemd" / "dronedream-worker.service").read_text(encoding="utf-8")
        for service in (api, worker):
            self.assertIn("/opt/dronedream/engine/current", service)
            self.assertNotIn("WorkingDirectory=/opt/dronedream/source", service)
        self.assertIn("engine/current/backend/alembic.ini", api)
        self.assertIn("ExecStart=/opt/dronedream/venv/bin/drone-dream-worker", worker)

    def test_runtime_auth_template_is_fail_closed_and_injected_at_build(self) -> None:
        template = (RUNTIME / "config" / "runtime.env.default").read_text(encoding="utf-8")
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        build = (RUNTIME / "build-rootfs.sh").read_text(encoding="utf-8")
        self.assertIn("AUTH_MODE=oidc_jwt", template)
        self.assertIn("DESKTOP_BRIDGE_REQUIRED=true", template)
        for placeholder in (
            "__OIDC_ISSUER__",
            "__OIDC_JWKS_URL__",
            "__MODEL_GATEWAY_BASE_URL__",
        ):
            self.assertIn(placeholder, template)
            self.assertIn(placeholder, dockerfile)
        self.assertIn("VITE_SUPABASE_URL", build)
        self.assertIn("/auth/v1/.well-known/jwks.json", build)
        self.assertIn("/functions/v1/model-gateway", build)


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


class RuntimeReleaseImmutabilityContractTests(unittest.TestCase):
    def test_release_workflow_guards_existing_remote_tag(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "runtime-release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn(
            'git ls-remote --exit-code --tags origin "refs/tags/$RELEASE_TAG"',
            workflow,
        )
        self.assertIn('if [[ "$tag_status" -ne 2 ]]', workflow)

    def test_rootfs_export_refuses_every_existing_release_artifact(self) -> None:
        script = (RUNTIME / "export-rootfs.sh").read_text(encoding="utf-8")
        self.assertIn(
            'for artifact in "$output" "$partial" "$output.sha256" "$output.manifest.json"',
            script,
        )
        self.assertIn('if [[ -e "$artifact" || -L "$artifact" ]]', script)
        # The only deletion is cleanup of the just-created partial when it
        # breaches the hard size cap; pre-existing partials are never removed.
        self.assertEqual(script.count('rm -f "$partial"'), 1)


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

    def test_runtime_services_use_a_consistent_systemd_sandbox(self) -> None:
        common = {
            "UMask=0027",
            "NoNewPrivileges=true",
            "PrivateTmp=true",
            "ProtectSystem=strict",
            "ProtectKernelTunables=true",
            "ProtectKernelModules=true",
            "ProtectControlGroups=true",
            "LockPersonality=true",
            "RestrictSUIDSGID=true",
        }
        for filename in self.EXPECTED_EXECUTABLES:
            text = (RUNTIME / "systemd" / filename).read_text(encoding="utf-8")
            for directive in common:
                self.assertIn(directive, text, filename)
        init = (RUNTIME / "systemd" / "dronedream-runtime-init.service").read_text(encoding="utf-8")
        self.assertIn(
            "ReadWritePaths=/etc/dronedream /var/lib/dronedream /var/lib/valkey",
            init,
        )
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "install -d -m 0750 -o root -g dronedream /etc/dronedream",
            dockerfile,
        )
        self.assertGreater(
            dockerfile.index("ARG DRONEDREAM_SOURCE_COMMIT"),
            dockerfile.index("COPY . /opt/dronedream/source"),
        )

    def test_runtime_seeds_a_verified_bootable_engine_pack_before_enabling_services(self) -> None:
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        build_script = (RUNTIME / "build-rootfs.sh").read_text(encoding="utf-8")
        self.assertIn(
            'source_date_epoch=$(git -C "$root" show -s --format=%ct "$source_commit")',
            build_script,
        )
        self.assertIn('--build-arg "DRONEDREAM_SOURCE_DATE_EPOCH=$source_date_epoch"', build_script)
        self.assertIn("ARG DRONEDREAM_SOURCE_DATE_EPOCH", dockerfile)
        self.assertIn("/opt/dronedream/source/engine-pack/tools/engine_pack.py", dockerfile)
        self.assertIn("/usr/lib/dronedream/engine-pack-manager.py", dockerfile)
        self.assertIn("--no-services", dockerfile)
        for required in (
            "test -L /opt/dronedream/engine/current",
            "test -s /opt/dronedream/engine/current/engine-pack-manifest.json",
            "test -d /opt/dronedream/engine/current/backend/app",
            "test -d /opt/dronedream/engine/current/worker/drone_dream_worker",
        ):
            self.assertIn(required, dockerfile)
        self.assertLess(
            dockerfile.index("test -L /opt/dronedream/engine/current"),
            dockerfile.index("systemctl enable dronedream-runtime-init.service"),
        )

    def test_runtime_diagnostic_tools_are_packaged_and_verified(self) -> None:
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"\biproute2\b")
        for executable in (
            "/usr/bin/curl",
            "/usr/bin/timeout",
            "/usr/bin/head",
            "/usr/bin/systemctl",
            "/usr/bin/journalctl",
            "/usr/bin/ss",
            "/usr/bin/ip",
        ):
            self.assertIn(f"test -x {executable}", dockerfile, executable)

    def test_generic_wsl_image_cannot_block_on_interactive_firstboot(self) -> None:
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("printf 'uninitialized\\n' >/etc/machine-id", dockerfile)
        self.assertIn(": >/etc/machine-id", dockerfile)
        self.assertIn("rm -f /var/lib/dbus/machine-id", dockerfile)
        self.assertIn("ln -s /etc/machine-id /var/lib/dbus/machine-id", dockerfile)
        self.assertIn(
            "ln -sfn /dev/null /etc/systemd/system/systemd-firstboot.service",
            dockerfile,
        )

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

    def test_build_checks_and_forwards_every_reported_component_version(self) -> None:
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        build_script = (RUNTIME / "build-rootfs.sh").read_text(encoding="utf-8")
        for name in (
            "PX4_GIT_URL",
            "PX4_GIT_COMMIT",
            "GAZEBO_METAPACKAGE_VERSION",
            "VALKEY_VERSION",
            "VALKEY_GIT_URL",
            "VALKEY_GIT_COMMIT",
            "PYTHON_VERSION",
            "BACKEND_VERSION",
            "WORKER_VERSION",
            "MAVSDK_VERSION",
            "PYULOG_VERSION",
        ):
            self.assertIn(f'--build-arg "{name}=${name}"', build_script, name)
            self.assertIn(f"ARG {name}=", dockerfile, name)
        self.assertIn('grep -F "v=${VALKEY_VERSION} "', dockerfile)
        self.assertIn('m.version("drone-dream-backend")', dockerfile)
        self.assertIn('m.version("drone-dream-worker")', dockerfile)
        self.assertIn('m.version("mavsdk")', dockerfile)
        self.assertIn('m.version("pyulog")', dockerfile)
        self.assertIn('= "${GAZEBO_METAPACKAGE_VERSION}"', dockerfile)

    def test_smoke_uses_the_worker_sandbox_without_root_shortcuts(self) -> None:
        worker = (RUNTIME / "systemd" / "dronedream-worker.service").read_text(encoding="utf-8")
        smoke = (RUNTIME / "smoke-image.sh").read_text(encoding="utf-8")
        keys = {
            "User",
            "Group",
            "UMask",
            "NoNewPrivileges",
            "PrivateTmp",
            "ProtectSystem",
            "ProtectHome",
            "ProtectKernelTunables",
            "ProtectKernelModules",
            "ProtectControlGroups",
            "LockPersonality",
            "RestrictSUIDSGID",
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
            for item in re.findall(r'^\s+"([A-Za-z]+=[^"]+)"$', block["body"], re.MULTILINE)
        )
        self.assertEqual(smoke_properties, worker_properties)
        self.assertIn("/usr/bin/systemd-run", smoke)
        self.assertIn("--working-directory=/opt/dronedream/source", smoke)
        self.assertNotIn('docker exec "$container" /usr/lib/dronedream/runtime-check.sh', smoke)
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
        service = (RUNTIME / "systemd" / "dronedream-px4-log-cleanup.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("User=dronedream", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn(
            "ReadWritePaths=/opt/PX4-Autopilot/build/px4_sitl_default/rootfs/log",
            service,
        )
        dockerfile = (RUNTIME / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("dronedream-px4-log-cleanup.timer", dockerfile)
        source = (RUNTIME / "scripts" / "px4-log-cleanup.py").read_text(encoding="utf-8")
        self.assertIn("os.O_DIRECTORY", source)
        self.assertIn("os.O_NOFOLLOW", source)
        self.assertIn("os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)", source)
        self.assertIn("os.unlink(leaf, dir_fd=parent_fd)", source)
        self.assertNotIn("item.path.unlink", source)

    def test_unsupported_ulog_dirfd_platform_fails_closed(self) -> None:
        if px4_log_cleanup.secure_dirfd_supported():
            self.skipTest("secure POSIX dirfd support is available")
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(px4_log_cleanup.CleanupError),
        ):
            px4_log_cleanup.cleanup_logs(Path(directory))


if __name__ == "__main__":
    unittest.main()
