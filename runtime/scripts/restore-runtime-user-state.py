#!/usr/bin/env python3
"""Carry user state from the verified rollback export into a new Runtime Base."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

STATE_ROOTS = ("var/lib/dronedream", "home/dronedream")
RELEASE_STATE = "var/lib/dronedream/engine-pack-state.json"
GENERATED_AGENT_RUNTIME = "home/dronedream/.local/share/dronedream-autonomy"
ENVIRONMENT = "etc/dronedream/runtime.env"


def restore_user_state(
    archive_path: Path, root: Path, owner: tuple[int, int] | None = None
) -> dict:
    restored = 0
    secret_line = None
    with tarfile.open(archive_path, "r|*") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Runtime backup contains a non-relative path")
            name = path.as_posix()
            if name == ENVIRONMENT:
                if not member.isfile() or member.size > 1024 * 1024:
                    raise ValueError("Runtime backup environment is invalid")
                source = archive.extractfile(member)
                assert source is not None
                lines = source.read().decode("utf-8").splitlines()
                secrets = [line for line in lines if line.startswith("APP_SECRET_KEY=")]
                if len(secrets) != 1:
                    raise ValueError("Runtime backup must contain one application secret")
                secret_line = secrets[0]
            if name in (RELEASE_STATE, GENERATED_AGENT_RUNTIME) or name.startswith(
                GENERATED_AGENT_RUNTIME + "/"
            ):
                # The new Agent Core provisions this derived Python/ROS cache
                # from its bundled, version-bound runtime inputs.
                continue
            if not any(name == prefix or name.startswith(prefix + "/") for prefix in STATE_ROOTS):
                continue
            state_root = next(
                root / prefix
                for prefix in STATE_ROOTS
                if name == prefix or name.startswith(prefix + "/")
            )
            destination = root / name
            if not destination.resolve().is_relative_to(state_root.resolve()):
                raise ValueError("Runtime user state escapes its owned directory")
            if member.issym() or member.islnk():
                link = (destination.parent if member.issym() else root) / member.linkname
                if not link.resolve().is_relative_to(state_root.resolve()):
                    raise ValueError("Runtime user state link escapes its owned directory")
            # Python's data filter also rejects special devices.
            archive.extract(member, path=root, filter="data")
            if owner is not None:
                os.chown(root / name, *owner, follow_symlinks=False)
            restored += 1
    if secret_line is None:
        raise ValueError("Runtime backup is missing the application secret")
    environment = root / ENVIRONMENT
    lines = environment.read_text(encoding="utf-8").splitlines()
    updated = [line for line in lines if not line.startswith("APP_SECRET_KEY=")]
    updated.append(secret_line)
    # Keep new service paths and new Runtime identity; only the local signing
    # secret follows the existing account database.
    environment.write_text("\n".join(updated) + "\n", encoding="utf-8")
    return {"userStateRestored": True, "entries": restored}


def migrate_user_state(archive: Path, root: Path, owner: tuple[int, int] | None) -> dict:
    subprocess.run(
        ["/usr/bin/systemctl", "stop", "dronedream-api.service", "dronedream-worker.service"],
        check=True,
        timeout=60,
    )
    result = restore_user_state(archive, root, owner)
    subprocess.run(
        ["/usr/bin/systemctl", "start", "dronedream-api.service", "dronedream-worker.service"],
        check=True,
        timeout=60,
    )
    return result


if __name__ == "__main__":
    import pwd

    account = pwd.getpwnam("dronedream")
    print(
        json.dumps(
            migrate_user_state(Path(sys.argv[1]), Path("/"), (account.pw_uid, account.pw_gid))
        )
    )
