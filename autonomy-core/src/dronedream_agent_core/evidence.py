"""Append-only hash-linked evidence records for a single mission run."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import EvidenceRecord
from .hashing import sha256_json

ZERO_HASH = "0" * 64


class EvidenceChain:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> list[EvidenceRecord]:
        if not self.path.exists():
            return []
        records = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(EvidenceRecord.model_validate_json(line))
        self.verify(records)
        return records

    def append(self, event_type: str, payload: dict[str, Any]) -> EvidenceRecord:
        records = self.read()
        previous = records[-1].record_sha256 if records else ZERO_HASH
        record = EvidenceRecord(
            sequence=len(records) + 1,
            created_at=datetime.now(UTC),
            event_type=event_type,
            artifact_sha256=sha256_json(payload),
            previous_record_sha256=previous,
            record_sha256=ZERO_HASH,
            payload=payload,
        )
        body = record.model_dump(mode="json", exclude={"record_sha256"})
        record.record_sha256 = sha256_json(body)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(record.model_dump_json() + "\n")
            handle.flush()
        return record

    @staticmethod
    def verify(records: list[EvidenceRecord]) -> None:
        previous = ZERO_HASH
        for expected_sequence, record in enumerate(records, start=1):
            if record.sequence != expected_sequence:
                raise ValueError("evidence sequence is discontinuous")
            if record.previous_record_sha256 != previous:
                raise ValueError("evidence previous hash does not match")
            body = record.model_dump(mode="json", exclude={"record_sha256"})
            if sha256_json(body) != record.record_sha256:
                raise ValueError("evidence record hash does not match content")
            if record.artifact_sha256 != sha256_json(record.payload):
                raise ValueError("evidence artifact hash does not match payload")
            previous = record.record_sha256

    def export_json(self) -> str:
        return json.dumps(
            [record.model_dump(mode="json") for record in self.read()],
            ensure_ascii=False,
            indent=2,
        )
