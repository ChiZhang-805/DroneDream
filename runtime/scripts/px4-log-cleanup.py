#!/usr/bin/env python3
"""Conservatively bound raw PX4 ULog storage in the packaged runtime."""

from __future__ import annotations

import json
import os
import stat
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

MANAGED_ROOT = Path("/opt/PX4-Autopilot/build/px4_sitl_default/rootfs/log")
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_AGE_SECONDS = 14 * 24 * 60 * 60
MIN_AGE_SECONDS = 60 * 60
KEEP_RECENT = 20


class CleanupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LogFile:
    path: Path
    relative_path: Path
    device: int
    inode: int
    size: int
    modified_ns: int

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode


@dataclass(slots=True)
class CleanupResult:
    status: str = "ok"
    root: str = str(MANAGED_ROOT)
    max_total_bytes: int = MAX_TOTAL_BYTES
    max_age_seconds: int = MAX_AGE_SECONDS
    min_age_seconds: int = MIN_AGE_SECONDS
    keep_recent: int = KEEP_RECENT
    scanned_files: int = 0
    bytes_before: int = 0
    protected_recent: int = 0
    protected_open: int = 0
    protected_young: int = 0
    selected_by_age: int = 0
    selected_by_capacity: int = 0
    deleted_files: int = 0
    deleted_bytes: int = 0
    bytes_after: int = 0
    capacity_excess_bytes: int = 0
    skipped_changed_or_open: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def secure_dirfd_supported() -> bool:
    """Return whether deletion can be confined with POSIX dirfd operations."""

    return (
        os.name == "posix"
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
    )


def _open_directory_chain(path: Path) -> int:
    if not secure_dirfd_supported():
        raise CleanupError("secure POSIX dirfd operations are unavailable; refusing cleanup")
    absolute = path.absolute()
    if not absolute.is_absolute():
        raise CleanupError("managed ULog root must be absolute")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open("/", flags)
    completed = False
    try:
        for component in absolute.parts[1:]:
            if component in {"", ".", ".."}:
                raise CleanupError("managed ULog root contains an unsafe component")
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        completed = True
        return descriptor
    finally:
        # Close every descriptor on errors *and* process-level interrupts. The
        # successfully returned directory descriptor becomes the caller's
        # responsibility.
        if not completed:
            os.close(descriptor)


def _scan_logs(root: Path) -> tuple[list[LogFile], list[str]]:
    if not root.exists():
        return [], []
    root_lstat = root.lstat()
    if not stat.S_ISDIR(root_lstat.st_mode) or stat.S_ISLNK(root_lstat.st_mode):
        raise CleanupError(f"managed ULog root is not a regular directory: {root}")
    root_resolved = root.resolve(strict=True)
    if root_resolved != root.absolute():
        raise CleanupError(f"managed ULog root must not traverse symlinks: {root}")

    logs: list[LogFile] = []
    errors: list[str] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        directory_names[:] = _safe_subdirectories(directory_path, directory_names, errors)

        for name in sorted(file_names):
            if not name.lower().endswith(".ulg"):
                continue
            candidate = directory_path / name
            inspected = _inspect_log(root, root_resolved, candidate, errors)
            if inspected is not None:
                logs.append(inspected)
    return logs, errors


def _safe_subdirectories(directory: Path, names: list[str], errors: list[str]) -> list[str]:
    safe: list[str] = []
    for name in sorted(names):
        candidate = directory / name
        try:
            candidate_stat = candidate.lstat()
            if stat.S_ISDIR(candidate_stat.st_mode) and not stat.S_ISLNK(candidate_stat.st_mode):
                safe.append(name)
        except OSError as exc:
            errors.append(f"could not inspect directory {candidate}: {exc}")
    return safe


def _inspect_log(
    root: Path,
    root_resolved: Path,
    candidate: Path,
    errors: list[str],
) -> LogFile | None:
    try:
        candidate_stat = candidate.lstat()
        if not stat.S_ISREG(candidate_stat.st_mode):
            return None
        if not candidate.resolve(strict=True).is_relative_to(root_resolved):
            errors.append(f"ULog escaped managed root: {candidate}")
            return None
        return LogFile(
            path=candidate,
            relative_path=candidate.relative_to(root),
            device=candidate_stat.st_dev,
            inode=candidate_stat.st_ino,
            size=candidate_stat.st_size,
            modified_ns=candidate_stat.st_mtime_ns,
        )
    except OSError as exc:
        errors.append(f"could not inspect ULog {candidate}: {exc}")
        return None


def _open_file_identities(proc_root: Path = Path("/proc")) -> set[tuple[int, int]]:
    identities: set[tuple[int, int]] = set()
    try:
        proc_details = proc_root.stat()
        if not stat.S_ISDIR(proc_details.st_mode):
            raise CleanupError("process file table is not a directory; refusing cleanup")
        processes = list(proc_root.iterdir())
    except OSError as exc:
        raise CleanupError("process file table is unavailable; refusing cleanup") from exc
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            entries = list((process / "fd").iterdir())
        except OSError:
            continue
        for descriptor in entries:
            try:
                descriptor_stat = descriptor.stat()
                if stat.S_ISREG(descriptor_stat.st_mode):
                    identities.add((descriptor_stat.st_dev, descriptor_stat.st_ino))
            except OSError:
                continue
    return identities


def _unlink_verified(
    root_fd: int,
    item: LogFile,
    *,
    current_ns: int,
    min_age_seconds: int,
) -> tuple[bool, str | None]:
    """Unlink one unchanged leaf relative to already confined directory FDs."""

    parts = item.relative_path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return False, "unsafe relative ULog path"
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    parent_fd = os.dup(root_fd)
    try:
        for component in parts[:-1]:
            child = os.open(component, flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = child
        leaf = parts[-1]
        current = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        unchanged = (
            stat.S_ISREG(current.st_mode)
            and current.st_dev == item.device
            and current.st_ino == item.inode
            and current.st_size == item.size
            and current.st_mtime_ns == item.modified_ns
        )
        old_enough = current_ns - current.st_mtime_ns >= min_age_seconds * 1_000_000_000
        if not unchanged or not old_enough:
            return False, None
        os.unlink(leaf, dir_fd=parent_fd)
        return True, None
    except OSError as exc:
        return False, str(exc)
    finally:
        os.close(parent_fd)


def _eligible_logs(
    logs: list[LogFile],
    *,
    current_ns: int,
    open_files: set[tuple[int, int]],
    keep_recent: int,
    min_age_seconds: int,
    result: CleanupResult,
) -> list[LogFile]:
    newest = sorted(logs, key=lambda item: (item.modified_ns, str(item.path)), reverse=True)
    recent = {item.identity for item in newest[:keep_recent]}
    result.protected_recent = len(recent)

    eligible: list[LogFile] = []
    minimum_age_ns = min_age_seconds * 1_000_000_000
    for item in sorted(logs, key=lambda value: (value.modified_ns, str(value.path))):
        if item.identity in recent:
            continue
        if item.identity in open_files:
            result.protected_open += 1
            continue
        if max(0, current_ns - item.modified_ns) < minimum_age_ns:
            result.protected_young += 1
            continue
        eligible.append(item)
    return eligible


def _select_logs(
    eligible: list[LogFile],
    *,
    current_ns: int,
    max_age_seconds: int,
    max_total_bytes: int,
    bytes_before: int,
    result: CleanupResult,
) -> dict[tuple[int, int], LogFile]:
    selected: dict[tuple[int, int], LogFile] = {}
    projected = bytes_before
    maximum_age_ns = max_age_seconds * 1_000_000_000
    if max_age_seconds > 0:
        for item in eligible:
            if current_ns - item.modified_ns < maximum_age_ns:
                continue
            selected[item.identity] = item
            projected -= item.size
            result.selected_by_age += 1

    if max_total_bytes <= 0 or projected <= max_total_bytes:
        return selected
    for item in eligible:
        if projected <= max_total_bytes:
            break
        if item.identity in selected:
            continue
        selected[item.identity] = item
        projected -= item.size
        result.selected_by_capacity += 1
    return selected


def _verify_opened_root(root: Path, root_fd: int) -> None:
    opened_root = os.fstat(root_fd)
    named_root = root.lstat()
    unchanged = (
        stat.S_ISDIR(named_root.st_mode)
        and not stat.S_ISLNK(named_root.st_mode)
        and opened_root.st_dev == named_root.st_dev
        and opened_root.st_ino == named_root.st_ino
    )
    if not unchanged:
        raise CleanupError("managed ULog root changed during cleanup")


def _delete_selected_logs(
    selected: dict[tuple[int, int], LogFile],
    *,
    root_fd: int,
    current_ns: int,
    min_age_seconds: int,
    open_files: set[tuple[int, int]],
    result: CleanupResult,
) -> None:
    for item in selected.values():
        if item.identity in open_files:
            result.skipped_changed_or_open += 1
            continue
        deleted, error = _unlink_verified(
            root_fd,
            item,
            current_ns=current_ns,
            min_age_seconds=min_age_seconds,
        )
        if deleted:
            result.deleted_files += 1
            result.deleted_bytes += item.size
            continue
        result.skipped_changed_or_open += 1
        if error is not None:
            result.errors.append(f"could not delete ULog {item.path}: {error}")


def cleanup_logs(
    root: Path = MANAGED_ROOT,
    *,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_age_seconds: int = MAX_AGE_SECONDS,
    min_age_seconds: int = MIN_AGE_SECONDS,
    keep_recent: int = KEEP_RECENT,
    now_ns: int | None = None,
    open_identities: set[tuple[int, int]] | None = None,
    _before_delete: Callable[[], None] | None = None,
) -> CleanupResult:
    if min(max_total_bytes, max_age_seconds, min_age_seconds, keep_recent) < 0:
        raise CleanupError("cleanup limits cannot be negative")
    if not secure_dirfd_supported():
        raise CleanupError("secure POSIX dirfd operations are unavailable; refusing cleanup")
    result = CleanupResult(
        root=str(root),
        max_total_bytes=max_total_bytes,
        max_age_seconds=max_age_seconds,
        min_age_seconds=min_age_seconds,
        keep_recent=keep_recent,
    )
    if not root.exists():
        result.status = "missing"
        return result

    logs, errors = _scan_logs(root)
    result.errors.extend(errors)
    result.scanned_files = len(logs)
    result.bytes_before = sum(item.size for item in logs)
    current_ns = now_ns if now_ns is not None else time.time_ns()
    open_files = open_identities if open_identities is not None else _open_file_identities()
    eligible = _eligible_logs(
        logs,
        current_ns=current_ns,
        open_files=open_files,
        keep_recent=keep_recent,
        min_age_seconds=min_age_seconds,
        result=result,
    )
    selected = _select_logs(
        eligible,
        current_ns=current_ns,
        max_age_seconds=max_age_seconds,
        max_total_bytes=max_total_bytes,
        bytes_before=result.bytes_before,
        result=result,
    )

    root_fd = _open_directory_chain(root)
    try:
        _verify_opened_root(root, root_fd)
        if _before_delete is not None:
            _before_delete()
        final_open_files = (
            open_identities if open_identities is not None else _open_file_identities()
        )
        _delete_selected_logs(
            selected,
            root_fd=root_fd,
            current_ns=current_ns,
            min_age_seconds=min_age_seconds,
            open_files=final_open_files,
            result=result,
        )
    finally:
        os.close(root_fd)

    result.bytes_after = max(0, result.bytes_before - result.deleted_bytes)
    if max_total_bytes > 0:
        result.capacity_excess_bytes = max(0, result.bytes_after - max_total_bytes)
    if result.errors:
        result.status = "partial"
    return result


def main() -> int:
    try:
        result = cleanup_logs()
    except (CleanupError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
