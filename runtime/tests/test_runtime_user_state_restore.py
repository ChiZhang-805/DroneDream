from __future__ import annotations

import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "runtime_user_state_restore",
    Path(__file__).resolve().parents[1] / "scripts/restore-runtime-user-state.py",
)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def _archive(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def test_preserves_user_data_without_restoring_old_runtime_code_or_pack_receipt(tmp_path: Path):
    root = tmp_path / "new"
    (root / "etc/dronedream").mkdir(parents=True)
    (root / "var/lib/dronedream").mkdir(parents=True)
    environment = root / tool.ENVIRONMENT
    environment.write_text(
        "APP_SECRET_KEY=new-secret\nDRONEDREAM_RUNTIME_ID=new-id\nPATH_TO_ENGINE=new-engine\n"
    )
    receipt = root / tool.RELEASE_STATE
    receipt.write_text("new-release")
    archive = tmp_path / "old.tar"
    _archive(
        archive,
        {
            "./var/lib/dronedream/dronedream.db": b"existing database",
            "./var/lib/dronedream/artifacts/job/result.json": b"existing evidence",
            "./home/dronedream/project/data.txt": b"user work",
            "./home/dronedream/.local/share/dronedream-autonomy/v0.1.0/venv/old.py": b"old",
            "./etc/dronedream/runtime.env": (
                b"APP_SECRET_KEY=old-secret\nDRONEDREAM_RUNTIME_ID=old-id\n"
            ),
            "./var/lib/dronedream/engine-pack-state.json": b"old-release",
            "./opt/dronedream/engine/current/code.py": b"old-code",
        },
    )
    assert tool.restore_user_state(archive, root)["userStateRestored"] is True
    assert (root / "var/lib/dronedream/dronedream.db").read_bytes() == b"existing database"
    assert (
        root / "var/lib/dronedream/artifacts/job/result.json"
    ).read_bytes() == b"existing evidence"
    assert (root / "home/dronedream/project/data.txt").read_bytes() == b"user work"
    assert receipt.read_text() == "new-release"
    assert not (root / "opt").exists()
    assert not (root / tool.GENERATED_AGENT_RUNTIME).exists()
    assert (
        environment.read_text()
        == "DRONEDREAM_RUNTIME_ID=new-id\nPATH_TO_ENGINE=new-engine\nAPP_SECRET_KEY=old-secret\n"
    )


def test_rejects_paths_outside_the_backup_root(tmp_path: Path):
    archive = tmp_path / "bad.tar"
    _archive(archive, {"var/lib/dronedream/../../../../escape": b"bad"})
    with pytest.raises(ValueError, match="non-relative"):
        tool.restore_user_state(archive, tmp_path / "new")
    assert not (tmp_path / "escape").exists()


def test_missing_authentication_state_does_not_silently_reset_accounts(tmp_path: Path):
    archive = tmp_path / "old.tar"
    _archive(archive, {"var/lib/dronedream/dronedream.db": b"accounts"})
    with pytest.raises(ValueError, match="missing the application secret"):
        tool.restore_user_state(archive, tmp_path / "new")


def test_user_home_link_cannot_overwrite_runtime_programs(tmp_path: Path):
    archive = tmp_path / "bad-link.tar"
    with tarfile.open(archive, "w") as output:
        member = tarfile.TarInfo("home/dronedream/programs")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../opt/dronedream"
        output.addfile(member)
    with pytest.raises(ValueError, match="link escapes"):
        tool.restore_user_state(archive, tmp_path / "new")


def test_services_restart_after_data_migration(tmp_path: Path, monkeypatch):
    root = tmp_path / "new"
    (root / "etc/dronedream").mkdir(parents=True)
    (root / tool.ENVIRONMENT).write_text("APP_SECRET_KEY=new-secret\n")
    archive = tmp_path / "old.tar"
    _archive(
        archive,
        {
            tool.ENVIRONMENT: b"APP_SECRET_KEY=old-secret\n",
            "var/lib/dronedream/dronedream.db": b"preserved database",
        },
    )
    actions = []

    def service_command(args, **kwargs):
        actions.append(args[1])
        if args[1] == "start":
            assert (root / "var/lib/dronedream/dronedream.db").read_bytes() == b"preserved database"
            assert "old-secret" in (root / tool.ENVIRONMENT).read_text()

    monkeypatch.setattr(tool.subprocess, "run", service_command)
    assert tool.migrate_user_state(archive, root, None)["userStateRestored"] is True
    assert actions == ["stop", "start"]
