"""Run a complete, provenance-bound provider campaign for Harness routing."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from app.orchestration.decision_harness import (
    HARNESS_PROMPT_TEMPLATE_VERSION,
    build_decision_messages,
    decision_schema_for_snapshot,
    validate_harness_decision_response,
)
from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
)
from app.orchestration.harness_evaluation import (
    HarnessRoutingCorpusRole,
    HarnessRoutingEvalCase,
    HarnessRoutingGenerationConfig,
    HarnessRoutingPrediction,
    HarnessRoutingPredictionArtifact,
    assert_routing_result_flow,
    compile_routing_eval_snapshot,
    routing_corpus_sha256,
    routing_prompt_suite_sha256,
)


class HarnessRoutingCampaignError(RuntimeError):
    """A complete trustworthy campaign could not be produced."""


class HarnessRoutingClient(Protocol):
    def generate(self, *, model: str, system: str, user: str) -> dict[str, object]: ...


HarnessRoutingClientFactory = Callable[
    [dict[str, object]],
    HarnessRoutingClient,
]


def run_harness_routing_campaign(
    cases: tuple[HarnessRoutingEvalCase, ...],
    *,
    provider: str,
    model_snapshot: str,
    generation_config: HarnessRoutingGenerationConfig,
    client_factory: HarnessRoutingClientFactory,
    source_role: HarnessRoutingCorpusRole = "development",
) -> HarnessRoutingPredictionArtifact:
    """Run every case and return an artifact only after complete validation."""

    assert_routing_result_flow(source_role, "development_evidence")
    normalized_provider = provider.strip()
    normalized_model = model_snapshot.strip()
    if not normalized_provider:
        raise ValueError("provider is required")
    if not normalized_model:
        raise ValueError("model_snapshot is required")
    if not cases:
        raise ValueError("routing campaign requires at least one case")

    predictions: dict[str, HarnessRoutingPrediction] = {}
    for case in cases:
        snapshot = compile_routing_eval_snapshot(case)
        system, user = build_decision_messages(snapshot)
        schema = decision_schema_for_snapshot(snapshot)
        try:
            raw = client_factory(schema).generate(
                model=normalized_model,
                system=system,
                user=user,
            )
        except Exception as exc:
            raise HarnessRoutingCampaignError(
                f"provider request failed for case {case.case_id}: {type(exc).__name__}"
            ) from exc
        validated = validate_harness_decision_response(raw, snapshot)
        if validated is None:
            raise HarnessRoutingCampaignError(
                f"provider returned an invalid decision for case {case.case_id}"
            )
        tool_id, rationale = validated
        predictions[case.case_id] = HarnessRoutingPrediction(
            selected_tool=tool_id,
            rationale=rationale,
        )

    return HarnessRoutingPredictionArtifact(
        corpus_sha256=routing_corpus_sha256(cases),
        prompt_suite_sha256=routing_prompt_suite_sha256(cases),
        evidence_schema_version=HARNESS_EVIDENCE_SCHEMA_VERSION,
        tool_registry_version=HARNESS_TOOL_REGISTRY_VERSION,
        prompt_template_version=HARNESS_PROMPT_TEMPLATE_VERSION,
        provider=normalized_provider,
        model_snapshot=normalized_model,
        generation_config=generation_config,
        predictions=predictions,
    )


def write_frozen_routing_artifact(
    path: Path,
    artifact: BaseModel,
) -> None:
    """Atomically create a new artifact without replacing a prior freeze."""

    destination = path.resolve()
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"artifact parent directory does not exist: {destination.parent}")
    payload = (
        json.dumps(
            artifact.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


__all__ = [
    "HarnessRoutingCampaignError",
    "HarnessRoutingClient",
    "HarnessRoutingClientFactory",
    "run_harness_routing_campaign",
    "write_frozen_routing_artifact",
]
