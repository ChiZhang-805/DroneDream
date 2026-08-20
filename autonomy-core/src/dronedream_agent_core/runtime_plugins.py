"""Snapshot-bound plugin helpers shared by the live execution sidecars."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .contracts import PreparedMission
from .extensions import ExtensionRegistry
from .plugin_api import build_discovered_extension_registry
from .plugin_contracts import PluginHookReceipt

_RECEIPT_LOCK = threading.Lock()


def runtime_extension_registry(prepared: PreparedMission) -> ExtensionRegistry:
    """Resolve only implementations frozen into the prepared mission snapshot."""

    return build_discovered_extension_registry(prepared.plugin_snapshot)


def augment_runtime_prompt(
    registry: ExtensionRegistry,
    *,
    role: str,
    instructions: str,
) -> tuple[str, list[PluginHookReceipt]]:
    value, receipts = registry.invoke_pipeline(
        "models.prompt-packs",
        "augment_prompt",
        instructions,
        role=role,
    )
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("RUNTIME_PROMPT_PIPELINE_INVALID")
    return value, receipts


def validate_runtime_model_output(
    registry: ExtensionRegistry,
    *,
    role: str,
    expected_schema: str,
    artifact: object,
    record: object,
) -> list[PluginHookReceipt]:
    """Run the same immutable structured-output guards used during preparation."""

    artifact_value = artifact.model_dump(mode="json")  # type: ignore[attr-defined]
    record_value = record.model_dump(mode="json")  # type: ignore[attr-defined]
    envelope = {"artifact": artifact_value, "record": record_value}
    guarded, receipts = registry.invoke_pipeline(
        "models.structured-output-guards",
        "validate_output",
        envelope,
        role=role,
        expected_schema=expected_schema,
    )
    if guarded != envelope:
        raise RuntimeError("PLUGIN_MODEL_OUTPUT_MUTATION_FORBIDDEN")
    return receipts


def append_hook_receipts(path: Path, receipts: list[PluginHookReceipt]) -> None:
    """Durably append hash-bound hook receipts from concurrent runtime sidecars."""

    if not receipts:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "".join(
        json.dumps(receipt.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        for receipt in receipts
    )
    with _RECEIPT_LOCK, path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered)
        stream.flush()


def require_plugin_acceptance(
    outputs: list[Any],
    *,
    gate_prefix: str,
) -> tuple[dict[str, bool], list[dict[str, object]]]:
    """Convert independent plugin verdicts into deterministic, non-relaxable gates."""

    gates: dict[str, bool] = {}
    normalized: list[dict[str, object]] = []
    for index, output in enumerate(outputs, start=1):
        if not isinstance(output, dict):
            gates[f"{gate_prefix}_{index:02d}"] = False
            normalized.append(
                {
                    "accepted": False,
                    "issue_codes": ["PLUGIN_VERDICT_NOT_OBJECT"],
                }
            )
            continue
        accepted = output.get("accepted") is True
        identity = str(
            output.get("detector")
            or output.get("validator")
            or output.get("evaluation")
            or f"{index:02d}"
        )
        safe_identity = "".join(
            character if character.isalnum() else "_" for character in identity.casefold()
        ).strip("_")
        suffix_value = safe_identity or f"{index:02d}"
        key = f"{gate_prefix}_{suffix_value}"
        suffix = 2
        original = key
        while key in gates:
            key = f"{original}_{suffix}"
            suffix += 1
        gates[key] = accepted
        normalized.append({str(key): value for key, value in output.items()})
    return gates, normalized
