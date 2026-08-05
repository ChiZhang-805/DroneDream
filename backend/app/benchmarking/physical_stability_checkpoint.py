"""Immutable filesystem checkpoints for the P5 execution ledger.

The store publishes one canonical, content-addressed JSON file per ledger
transition.  It never maintains a mutable ``latest`` pointer and never replaces
an existing checkpoint.  Production callers must place the run directory as a
direct child of an explicitly supplied evidence root; tests use the same guard
with a temporary directory.
"""

from __future__ import annotations

import contextlib
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.benchmarking.contracts import (
    Identifier,
    Sha256Hex,
    canonical_json_bytes,
    canonical_sha256,
)
from app.benchmarking.physical_stability_execution import (
    PhysicalStabilityExecutionLedgerV1,
    PhysicalStabilityLedgerTransitionV1,
)

PHYSICAL_STABILITY_CHECKPOINT_SCHEMA_ID: Final[
    Literal["dronedream.physical-stability-checkpoint/v1"]
] = "dronedream.physical-stability-checkpoint/v1"

_RUN_DIRECTORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CHECKPOINT_PATTERN = re.compile(r"^(?P<sequence>[0-9]{4})-(?P<digest>[0-9a-f]{64})\.json$")
_MAX_CHECKPOINTS = 18


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _checkpoint_unsigned_payload(checkpoint: PhysicalStabilityCheckpointV1) -> dict[str, object]:
    payload = checkpoint.model_dump(mode="json", exclude_none=False)
    payload.pop("checkpoint_sha256", None)
    return payload


class PhysicalStabilityCheckpointV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-checkpoint/v1"] = (
        PHYSICAL_STABILITY_CHECKPOINT_SCHEMA_ID
    )
    sequence: Annotated[int, Field(ge=1, le=_MAX_CHECKPOINTS)]
    previous_checkpoint_sha256: Sha256Hex | None
    ledger_sha256: Sha256Hex
    transition_record_sha256: Sha256Hex
    ledger: PhysicalStabilityExecutionLedgerV1
    transition: PhysicalStabilityLedgerTransitionV1
    checkpoint_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_checkpoint(self) -> PhysicalStabilityCheckpointV1:
        if canonical_sha256(self.ledger) != self.ledger_sha256:
            raise ValueError("checkpoint ledger SHA does not recompute")
        if canonical_sha256(self.transition) != self.transition_record_sha256:
            raise ValueError("checkpoint transition record SHA does not recompute")
        if self.transition.after_ledger_sha256 != self.ledger_sha256:
            raise ValueError("checkpoint transition does not produce its stored ledger")
        if self.transition.authorization_id != self.ledger.authorization_id:
            raise ValueError("checkpoint transition and ledger authorization IDs differ")
        if canonical_sha256(_checkpoint_unsigned_payload(self)) != self.checkpoint_sha256:
            raise ValueError("checkpoint content SHA does not recompute")
        return self


def _new_checkpoint(
    ledger: PhysicalStabilityExecutionLedgerV1,
    transition: PhysicalStabilityLedgerTransitionV1,
    *,
    sequence: int,
    previous_checkpoint_sha256: str | None,
) -> PhysicalStabilityCheckpointV1:
    unsigned = {
        "schema_id": PHYSICAL_STABILITY_CHECKPOINT_SCHEMA_ID,
        "sequence": sequence,
        "previous_checkpoint_sha256": previous_checkpoint_sha256,
        "ledger_sha256": canonical_sha256(ledger),
        "transition_record_sha256": canonical_sha256(transition),
        "ledger": ledger.model_dump(mode="json", exclude_none=False),
        "transition": transition.model_dump(mode="json", exclude_none=False),
    }
    return PhysicalStabilityCheckpointV1(
        sequence=sequence,
        previous_checkpoint_sha256=previous_checkpoint_sha256,
        ledger_sha256=canonical_sha256(ledger),
        transition_record_sha256=canonical_sha256(transition),
        ledger=ledger,
        transition=transition,
        checkpoint_sha256=canonical_sha256(unsigned),
    )


def _require_ordinary_directory(path: Path, *, label: str) -> None:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise ValueError(f"{label} must be an ordinary directory")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Windows commonly refuses fsync on directory handles.  Each file was
        # already fsynced before its no-replace publication.
        if os.name != "nt":
            raise
    finally:
        os.close(descriptor)


class AtomicPhysicalStabilityCheckpointStore:
    """Append-only checkpoint store with startup verification and no replay magic."""

    def __init__(
        self,
        directory: Path,
        *,
        allowed_evidence_root: Path,
        initial_ledger_sha256: str,
        authorization_id: str,
    ) -> None:
        initial_binding = _InitialCheckpointBinding(
            initial_ledger_sha256=initial_ledger_sha256,
            authorization_id=authorization_id,
        )
        root = allowed_evidence_root.resolve(strict=True)
        _require_ordinary_directory(root, label="allowed evidence root")
        target = directory.resolve(strict=False)
        if target.parent != root or not _RUN_DIRECTORY_PATTERN.fullmatch(target.name):
            raise ValueError("checkpoint directory must be a named direct child of evidence root")
        if target.exists():
            _require_ordinary_directory(target, label="checkpoint directory")
        else:
            target.mkdir(mode=0o700)
            _fsync_directory(root)
        self._directory = target
        self._initial_ledger_sha256 = initial_binding.initial_ledger_sha256
        self._authorization_id = initial_binding.authorization_id

    @property
    def directory(self) -> Path:
        return self._directory

    def _checkpoint_paths(self) -> list[Path]:
        paths: list[tuple[int, Path]] = []
        for entry in self._directory.iterdir():
            if entry.name.startswith(".") and entry.name.endswith(".tmp"):
                if entry.is_symlink() or not entry.is_file():
                    raise ValueError("checkpoint temporary entry is not an ordinary file")
                continue
            match = _CHECKPOINT_PATTERN.fullmatch(entry.name)
            if match is None:
                raise ValueError(f"unexpected entry in checkpoint directory: {entry.name}")
            metadata = entry.lstat()
            if not stat.S_ISREG(metadata.st_mode) or entry.is_symlink() or metadata.st_nlink != 1:
                raise ValueError("checkpoint path must be a single-link ordinary file")
            paths.append((int(match.group("sequence")), entry))
        paths.sort(key=lambda item: item[0])
        return [path for _sequence, path in paths]

    def load_chain(self) -> tuple[PhysicalStabilityCheckpointV1, ...]:
        chain: list[PhysicalStabilityCheckpointV1] = []
        for expected_sequence, path in enumerate(self._checkpoint_paths(), start=1):
            match = _CHECKPOINT_PATTERN.fullmatch(path.name)
            assert match is not None
            if int(match.group("sequence")) != expected_sequence:
                raise ValueError("checkpoint sequence contains a gap or duplicate")
            raw = path.read_bytes()
            try:
                checkpoint = PhysicalStabilityCheckpointV1.model_validate_json(raw)
            except ValidationError as exc:
                raise ValueError("checkpoint is not valid UTF-8 JSON") from exc
            expected_bytes = canonical_json_bytes(checkpoint) + b"\n"
            if raw != expected_bytes:
                raise ValueError("checkpoint bytes are not in canonical immutable form")
            if checkpoint.sequence != expected_sequence:
                raise ValueError("checkpoint body sequence differs from its position")
            if match.group("digest") != checkpoint.checkpoint_sha256:
                raise ValueError("checkpoint filename digest differs from its content")
            previous = chain[-1] if chain else None
            if previous is None:
                if checkpoint.previous_checkpoint_sha256 is not None:
                    raise ValueError("first checkpoint cannot claim a predecessor")
                if checkpoint.transition.before_ledger_sha256 != self._initial_ledger_sha256:
                    raise ValueError("first checkpoint does not bind the authorized initial ledger")
                if checkpoint.transition.action != "dispatch_attempted":
                    raise ValueError("first checkpoint must reserve dispatch before external I/O")
            else:
                if checkpoint.previous_checkpoint_sha256 != previous.checkpoint_sha256:
                    raise ValueError("checkpoint predecessor hash does not continue the chain")
                if checkpoint.transition.before_ledger_sha256 != previous.ledger_sha256:
                    raise ValueError("checkpoint transition does not continue the prior ledger")
                if checkpoint.ledger.authorization_id != previous.ledger.authorization_id:
                    raise ValueError("checkpoint chain changed authorization identity")
            if checkpoint.ledger.authorization_id != self._authorization_id:
                raise ValueError("checkpoint does not bind the configured authorization")
            chain.append(checkpoint)
        return tuple(chain)

    def load_latest(self) -> PhysicalStabilityCheckpointV1 | None:
        chain = self.load_chain()
        return chain[-1] if chain else None

    def persist(
        self,
        ledger: PhysicalStabilityExecutionLedgerV1,
        transition: PhysicalStabilityLedgerTransitionV1,
    ) -> None:
        chain = self.load_chain()
        if len(chain) >= _MAX_CHECKPOINTS:
            raise ValueError("P5 checkpoint cap is exhausted")
        previous = chain[-1] if chain else None
        if previous is None and transition.before_ledger_sha256 != self._initial_ledger_sha256:
            raise ValueError("first checkpoint does not continue the authorized initial ledger")
        if ledger.authorization_id != self._authorization_id:
            raise ValueError("new checkpoint does not bind the configured authorization")
        if previous is not None and transition.before_ledger_sha256 != previous.ledger_sha256:
            raise ValueError("new checkpoint transition does not continue the durable ledger")
        if previous is not None and ledger.authorization_id != previous.ledger.authorization_id:
            raise ValueError("new checkpoint changed authorization identity")
        checkpoint = _new_checkpoint(
            ledger,
            transition,
            sequence=len(chain) + 1,
            previous_checkpoint_sha256=(
                previous.checkpoint_sha256 if previous is not None else None
            ),
        )
        filename = f"{checkpoint.sequence:04d}-{checkpoint.checkpoint_sha256}.json"
        destination = self._directory / filename
        temporary = self._directory / f".{filename}.{uuid.uuid4().hex}.tmp"
        payload = canonical_json_bytes(checkpoint) + b"\n"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)
            _fsync_directory(self._directory)
        except FileExistsError as exc:
            raise ValueError("refusing to overwrite an existing P5 checkpoint") from exc
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
        if destination.read_bytes() != payload:
            raise RuntimeError("published P5 checkpoint bytes failed immediate verification")


class _InitialCheckpointBinding(_StrictFrozen):
    initial_ledger_sha256: Sha256Hex
    authorization_id: Identifier


__all__ = [
    "PHYSICAL_STABILITY_CHECKPOINT_SCHEMA_ID",
    "AtomicPhysicalStabilityCheckpointStore",
    "PhysicalStabilityCheckpointV1",
]
