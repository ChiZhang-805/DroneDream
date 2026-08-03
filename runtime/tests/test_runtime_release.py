from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
SPEC = importlib.util.spec_from_file_location(
    "runtime_release", RUNTIME / "tools" / "runtime_release.py"
)
assert SPEC and SPEC.loader
runtime_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_release)

MANIFEST_SPEC = importlib.util.spec_from_file_location(
    "runtime_manifest_test", RUNTIME / "tools" / "runtime_manifest.py"
)
assert MANIFEST_SPEC and MANIFEST_SPEC.loader
runtime_manifest = importlib.util.module_from_spec(MANIFEST_SPEC)
MANIFEST_SPEC.loader.exec_module(runtime_manifest)


def _exact_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        name, separator, version = value.partition("==")
        if not separator or not name or not version:
            raise AssertionError(f"{path} contains a non-exact requirement: {value}")
        requirements[name.casefold()] = version
    return requirements


class RuntimeReleaseTests(unittest.TestCase):
    def test_release_tools_share_the_audited_runtime_versions(self) -> None:
        runtime_requirements = _exact_requirements(RUNTIME / "locks" / "python-requirements.lock")
        release_requirements = _exact_requirements(
            RUNTIME / "locks" / "release-tools-requirements.lock"
        )

        self.assertEqual(
            release_requirements,
            {name: runtime_requirements[name] for name in release_requirements},
        )

    def _inputs(self, directory: Path) -> tuple[Path, Path, Path]:
        checks = [
            {"name": name, "passed": True, "durationSeconds": 1}
            for name in (
                "component_versions",
                "python_imports",
                "valkey_ping",
                "api_worker_heartbeat",
                "real_cli_dry_run",
                "px4_gazebo_headless",
                "parameter_readback",
            )
        ]
        unpromoted_path = directory / "unpromoted.manifest.json"
        unpromoted = runtime_manifest.generate(
            RUNTIME / "pins.env",
            RUNTIME / "locks" / "python-requirements.lock",
            "a" * 40,
            unpromoted_path,
        )
        report = {
            "mode": "runtime-image",
            "runtimeId": unpromoted["runtimeId"],
            "imageId": "sha256:" + "b" * 64,
            "passed": True,
            "completedAt": "2026-07-12T01:02:03+00:00",
            "checks": checks,
        }
        report_path = directory / "smoke-report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        manifest = directory / "promoted.manifest.json"
        runtime_manifest.promote_smoke(
            unpromoted_path,
            report_path,
            manifest,
        )
        rootfs = directory / "DroneDreamRuntime-0.1.0-amd64.tar"
        manifest_bytes = manifest.read_bytes()
        with tarfile.open(rootfs, mode="w") as archive:
            member = tarfile.TarInfo(runtime_release.EMBEDDED_MANIFEST_MEMBER)
            member.size = len(manifest_bytes)
            archive.addfile(member, io.BytesIO(manifest_bytes))
            payload = b"a release rootfs split across many tiny test parts"
            payload_member = tarfile.TarInfo("opt/dronedream/payload.txt")
            payload_member.size = len(payload)
            archive.addfile(payload_member, io.BytesIO(payload))
        return rootfs, manifest, report_path

    def _package(self, directory: Path, **changes: object) -> tuple[Path, Path]:
        rootfs, promoted, report = self._inputs(directory)
        arguments = {
            "rootfs": rootfs,
            "runtime_manifest_path": promoted,
            "smoke_report_path": report,
            "output_directory": directory / "release",
            "base_url": (
                "https://github.com/ChiZhang-805/DroneDream/releases/download/runtime-v0.1.0-beta.1"
            ),
            "build_timestamp": "2026-07-12T00:00:00Z",
            "part_bytes": 1024,
            "minimum_free_bytes": runtime_release.DEFAULT_MINIMUM_FREE_BYTES,
        }
        arguments.update(changes)
        manifest_path = runtime_release.package_release(**arguments)
        return rootfs, manifest_path

    def _sign(self, directory: Path, manifest: Path) -> tuple[Path, Path, Path]:
        private_key = directory / "private-key.txt"
        keyring = directory / "trusted-keys.json"
        key_id = runtime_release.generate_key(private_key, keyring)
        self.assertRegex(key_id, r"^ed25519:[0-9a-f]{64}$")
        secret = private_key.read_text(encoding="ascii").strip()
        variable = "DRONEDREAM_TEST_RELEASE_PRIVATE_KEY"
        with _temporary_environment(variable, secret):
            signature = runtime_release.sign_manifest(manifest, variable, None)
        return signature, keyring, private_key

    def test_package_sign_verify_and_reassemble(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            rootfs, manifest_path = self._package(directory)
            manifest = runtime_release.load_json(manifest_path)
            self.assertEqual(manifest_path.read_bytes(), runtime_release.canonical_bytes(manifest))
            self.assertEqual(manifest["runtime"]["id"], "DroneDreamRuntime")
            self.assertEqual(manifest["requirements"]["targetPathHint"], "X:\\DroneDream")
            self.assertEqual(manifest["artifact"]["compression"], "none")
            self.assertGreater(len(manifest["artifact"]["parts"]), 1)
            self.assertTrue(
                all(part["sizeBytes"] < 2 * 1024**3 for part in manifest["artifact"]["parts"])
            )
            self.assertTrue(
                all(part["url"].startswith("https://") for part in manifest["artifact"]["parts"])
            )

            signature, keyring, private_key = self._sign(directory, manifest_path)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(private_key.stat().st_mode), 0o600)
            runtime_release.verify_release(manifest_path, signature, keyring, manifest_path.parent)
            output = directory / "reassembled.tar"
            runtime_release.reassemble_release(
                manifest_path,
                signature,
                keyring,
                manifest_path.parent,
                output,
            )
            self.assertEqual(output.read_bytes(), rootfs.read_bytes())

    def test_tampered_part_fails_before_reassembly_is_published(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, manifest_path = self._package(directory)
            signature, keyring, _ = self._sign(directory, manifest_path)
            manifest = runtime_release.load_json(manifest_path)
            first = manifest_path.parent / manifest["artifact"]["parts"][0]["filename"]
            first.write_bytes(b"tampered")
            output = directory / "must-not-exist.tar"
            with self.assertRaises(runtime_release.ReleaseError):
                runtime_release.reassemble_release(
                    manifest_path,
                    signature,
                    keyring,
                    manifest_path.parent,
                    output,
                )
            self.assertFalse(output.exists())
            self.assertFalse(any(directory.glob(".must-not-exist.tar.partial-*")))

    def test_signature_requires_trusted_key_and_exact_manifest_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, manifest_path = self._package(directory)
            signature, _, _ = self._sign(directory, manifest_path)
            empty_keyring = RUNTIME / "release-public-keys.json"
            with self.assertRaisesRegex(runtime_release.ReleaseError, "trusted keyring"):
                runtime_release.verify_signature(manifest_path, signature, empty_keyring)

            manifest = runtime_release.load_json(manifest_path)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            with self.assertRaisesRegex(runtime_release.ReleaseError, "not canonical"):
                runtime_release.verify_signature(manifest_path, signature, empty_keyring)

    def test_retired_key_is_structurally_valid_but_cannot_verify_new_release(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, manifest_path = self._package(directory)
            signature, keyring_path, _ = self._sign(directory, manifest_path)
            keyring = runtime_release.load_json(keyring_path)
            keyring["keys"][0]["status"] = "retired"
            keyring_path.write_text(json.dumps(keyring), encoding="utf-8")

            self.assertEqual(runtime_release.validate_keyring(keyring), {})
            with self.assertRaisesRegex(runtime_release.ReleaseError, "trusted keyring"):
                runtime_release.verify_signature(manifest_path, signature, keyring_path)

    def test_failed_or_mismatched_smoke_evidence_cannot_be_packaged(self) -> None:
        for mutation in ("failed", "mismatched"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as name:
                directory = Path(name)
                rootfs, promoted, report_path = self._inputs(directory)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                if mutation == "failed":
                    report["passed"] = False
                else:
                    report["runtimeId"] = "3cfd158f-94a8-5df6-8470-a28588c37c18"
                report_path.write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaises(runtime_release.ReleaseError):
                    runtime_release.package_release(
                        rootfs=rootfs,
                        runtime_manifest_path=promoted,
                        smoke_report_path=report_path,
                        output_directory=directory / "release",
                        base_url="https://example.test/releases/runtime-v0.1.0",
                        build_timestamp="2026-07-12T00:00:00Z",
                        part_bytes=7,
                    )
                self.assertFalse((directory / "release").exists())

    def test_smoke_completion_time_must_match_promoted_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            rootfs, promoted, report_path = self._inputs(directory)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["completedAt"] = "2026-07-12T02:03:04+00:00"
            report_path.write_text(json.dumps(report), encoding="utf-8")

            with self.assertRaisesRegex(runtime_release.ReleaseError, "completedAt"):
                runtime_release.package_release(
                    rootfs=rootfs,
                    runtime_manifest_path=promoted,
                    smoke_report_path=report_path,
                    output_directory=directory / "release",
                    base_url="https://example.test/runtime",
                    build_timestamp="2026-07-12T00:00:00Z",
                    part_bytes=1024,
                )
            self.assertFalse((directory / "release").exists())

    def test_new_file_write_failure_removes_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            output = Path(name) / "partial.json"
            with (
                mock.patch.object(runtime_release.os, "fsync", side_effect=OSError("disk full")),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                runtime_release._write_new(output, b"partial")
            self.assertFalse(output.exists())

    def test_signature_is_rolled_back_when_public_key_output_fails(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, manifest_path = self._package(directory)
            private_key = directory / "private-key.txt"
            initial_keyring = directory / "initial-keyring.json"
            runtime_release.generate_key(private_key, initial_keyring)
            variable = "DRONEDREAM_TEST_RELEASE_PRIVATE_KEY"
            public_output = directory / "existing-keyring.json"
            public_output.write_bytes(b"preserve-me")
            signature = Path(f"{manifest_path}{runtime_release.SIGNATURE_SUFFIX}")

            with (
                _temporary_environment(
                    variable, private_key.read_text(encoding="ascii").strip()
                ),
                self.assertRaisesRegex(runtime_release.ReleaseError, "refusing to overwrite"),
            ):
                runtime_release.sign_manifest(manifest_path, variable, public_output)

            self.assertFalse(signature.exists())
            self.assertEqual(public_output.read_bytes(), b"preserve-me")

    def test_package_rejects_rootfs_manifest_sidecar_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            rootfs, promoted, report = self._inputs(directory)
            mismatched = json.loads(promoted.read_text(encoding="utf-8"))
            mismatched["smokeReport"]["imageId"] = "sha256:" + "d" * 64
            mismatched_bytes = json.dumps(mismatched).encode("utf-8")
            with tarfile.open(rootfs, mode="w") as archive:
                member = tarfile.TarInfo(runtime_release.EMBEDDED_MANIFEST_MEMBER)
                member.size = len(mismatched_bytes)
                archive.addfile(member, io.BytesIO(mismatched_bytes))

            with self.assertRaisesRegex(
                runtime_release.ReleaseError,
                "does not match its promoted sidecar",
            ):
                runtime_release.package_release(
                    rootfs=rootfs,
                    runtime_manifest_path=promoted,
                    smoke_report_path=report,
                    output_directory=directory / "release",
                    base_url="https://example.test/runtime",
                    build_timestamp="2026-07-12T00:00:00Z",
                    part_bytes=1024,
                )
            self.assertFalse((directory / "release").exists())

    def test_validated_embedded_manifest_can_be_recovered_without_extracting_tar(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            _, promoted_path, _ = self._inputs(directory)
            content = promoted_path.read_bytes()
            rootfs = directory / "runtime.tar"
            with tarfile.open(rootfs, mode="w") as archive:
                member = tarfile.TarInfo(runtime_release.EMBEDDED_MANIFEST_MEMBER)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
                trap = tarfile.TarInfo("../../must-not-be-extracted.txt")
                trap_content = b"not extracted"
                trap.size = len(trap_content)
                archive.addfile(trap, io.BytesIO(trap_content))
            output = directory / "runtime.tar.manifest.json"
            runtime_release.extract_embedded_manifest(rootfs, output)
            self.assertEqual(output.read_bytes(), content)
            self.assertFalse((directory.parent / "must-not-be-extracted.txt").exists())

    def test_insecure_urls_and_two_gib_part_size_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            rootfs, promoted, report = self._inputs(directory)
            common = {
                "rootfs": rootfs,
                "runtime_manifest_path": promoted,
                "smoke_report_path": report,
                "output_directory": directory / "release",
                "build_timestamp": "2026-07-12T00:00:00Z",
            }
            with self.assertRaises(runtime_release.ReleaseError):
                runtime_release.package_release(
                    **common,
                    base_url="http://example.test/runtime",
                    part_bytes=1024,
                )
            with self.assertRaises(runtime_release.ReleaseError):
                runtime_release.package_release(
                    **common,
                    base_url="https://example.test/runtime",
                    part_bytes=2 * 1024**3,
                )

    def test_capacity_and_part_count_limits_fail_before_writing_output(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            rootfs, promoted, report = self._inputs(directory)
            rootfs.write_bytes(b"x" * (runtime_release.MAX_PARTS + 1))
            common = {
                "rootfs": rootfs,
                "runtime_manifest_path": promoted,
                "smoke_report_path": report,
                "output_directory": directory / "release",
                "base_url": "https://example.test/runtime",
                "build_timestamp": "2026-07-12T00:00:00Z",
            }
            with self.assertRaisesRegex(runtime_release.ReleaseError, "64-part"):
                runtime_release.package_release(**common, part_bytes=0 + 1)
            with self.assertRaisesRegex(runtime_release.ReleaseError, "52 GiB"):
                runtime_release.package_release(
                    **common,
                    part_bytes=7,
                    minimum_free_bytes=51 * 1024**3,
                )
            self.assertFalse((directory / "release").exists())

    def test_committed_schemas_and_trusted_keyring_are_safe(self) -> None:
        keyring_path = RUNTIME / "release-public-keys.json"
        keyring = runtime_release.load_json(keyring_path)
        trusted_keys = runtime_release.validate_keyring(keyring)
        self.assertEqual(len(trusted_keys), 1)
        key_id, public_key = next(iter(trusted_keys.items()))
        self.assertEqual(key_id, runtime_release.key_id_for_public_key(public_key))
        self.assertEqual(len(public_key), 32)
        self.assertNotIn("privateKey", json.dumps(keyring))
        manifest_schema = json.loads(
            (RUNTIME / "release-manifest.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest_schema["properties"]["schemaVersion"]["const"], 1)
        self.assertEqual(
            manifest_schema["properties"]["artifact"]["properties"]["compression"]["const"],
            "none",
        )
        self.assertEqual(
            manifest_schema["properties"]["requirements"]["properties"]["targetPathHint"]["const"],
            "X:\\DroneDream",
        )

    def test_beta_release_fixture_verifies_with_committed_trust_anchor(self) -> None:
        fixture = RUNTIME / "tests" / "fixtures" / "runtime-release.json"
        manifest = runtime_release.verify_signature(
            fixture,
            Path(f"{fixture}.sig"),
            RUNTIME / "release-public-keys.json",
        )
        self.assertEqual(
            manifest["runtime"]["buildId"],
            "5e15a7a5-f943-5c38-a284-1bdcc9cd528f",
        )
        self.assertEqual(
            manifest["artifact"]["sha256"],
            "e9e12774befaa7296e42fdb1f5f285c997fdd6d47a95b5dbbe38e2333799c3b6",
        )

    def test_canonical_bytes_match_shared_rust_vector(self) -> None:
        fixture = RUNTIME / "tests" / "fixtures" / "jcs-release-vector.input.json"
        expected = (
            (RUNTIME / "tests" / "fixtures" / "jcs-release-vector.sha256")
            .read_text(encoding="ascii")
            .strip()
        )
        payload = runtime_release.load_json(fixture)
        canonical = runtime_release.canonical_bytes(payload)
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), expected)
        self.assertNotIn(b"\n", canonical)


@contextlib.contextmanager
def _temporary_environment(name: str, value: str):
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


if __name__ == "__main__":
    unittest.main()
