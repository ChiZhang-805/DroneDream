"""Tests for complete, frozen Harness provider routing campaigns."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.orchestration.harness_context import selectable_harness_tools
from app.orchestration.harness_evaluation import (
    HarnessRoutingGenerationConfig,
    compile_routing_eval_snapshot,
    load_routing_eval_cases,
    load_routing_prediction_artifact,
)
from app.orchestration.harness_routing_campaign import (
    HarnessRoutingCampaignError,
    run_harness_routing_campaign,
    write_frozen_routing_artifact,
)

CORPUS = Path(__file__).parent / "fixtures" / "harness_routing_eval_v1.jsonl"
BACKEND_ROOT = Path(__file__).parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
CAMPAIGN_SCRIPT = BACKEND_ROOT / "scripts" / "run_harness_routing_campaign.py"


class _FakeClient:
    def __init__(self, response: object) -> None:
        self.response = response

    def generate(
        self,
        *,
        model: str,
        system: str,
        user: str,
    ) -> dict[str, object]:
        del model, system, user
        if isinstance(self.response, Exception):
            raise self.response
        assert isinstance(self.response, dict)
        return self.response


def test_cli_preflight_binds_the_script_backend_without_credentials(
    tmp_path: Path,
) -> None:
    output = tmp_path / "would-be-online-artifact.json"
    environment = os.environ.copy()
    environment.pop("HARNESS_ROUTING_API_KEY", None)

    result = subprocess.run(
        [
            sys.executable,
            str(CAMPAIGN_SCRIPT),
            "--output",
            str(output),
            "--model-snapshot",
            "gpt-test-snapshot",
            "--preflight-only",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    preflight = json.loads(result.stdout)
    assert Path(preflight["backend_root"]) == BACKEND_ROOT.resolve()
    assert preflight["case_count"] == 24
    assert preflight["prompt_template_version"] == "1.7"
    assert preflight["output_exists"] is False
    assert not output.exists()


def test_campaign_runs_exact_prompts_and_creates_loadable_artifact(
    tmp_path: Path,
) -> None:
    cases = load_routing_eval_cases(CORPUS)
    schemas: list[dict[str, object]] = []
    case_index = 0

    def factory(schema: dict[str, object]) -> _FakeClient:
        nonlocal case_index
        schemas.append(schema)
        case = cases[case_index]
        case_index += 1
        selectable = set(selectable_harness_tools(compile_routing_eval_snapshot(case)))
        return _FakeClient(
            {
                "decision": {
                    "tool_id": next(
                        tool_id for tool_id in case.acceptable_tools if tool_id in selectable
                    ),
                    "rationale": "Frozen provider campaign decision.",
                }
            }
        )

    artifact = run_harness_routing_campaign(
        cases,
        provider="openai",
        model_snapshot="gpt-test-snapshot",
        generation_config=HarnessRoutingGenerationConfig(response_format="json_schema"),
        client_factory=factory,
    )
    output = tmp_path / "predictions.json"
    write_frozen_routing_artifact(output, artifact)
    loaded = load_routing_prediction_artifact(output, cases)

    assert loaded == artifact
    assert len(schemas) == len(cases)
    for case, schema in zip(cases, schemas, strict=True):
        enum = schema["properties"]["decision"]["properties"]["tool_id"]["enum"]
        assert tuple(enum) == selectable_harness_tools(compile_routing_eval_snapshot(case))
    assert json.loads(output.read_text(encoding="utf-8"))["predictions"]


def test_campaign_rejects_ineligible_decision_without_publishing(
    tmp_path: Path,
) -> None:
    cases = load_routing_eval_cases(CORPUS)[:1]

    with pytest.raises(HarnessRoutingCampaignError, match="invalid decision"):
        run_harness_routing_campaign(
            cases,
            provider="openai",
            model_snapshot="gpt-test-snapshot",
            generation_config=HarnessRoutingGenerationConfig(),
            client_factory=lambda _schema: _FakeClient(
                {
                    "decision": {
                        "tool_id": "turbo",
                        "rationale": "No trust-region evidence exists.",
                    }
                }
            ),
        )

    assert list(tmp_path.iterdir()) == []


def test_campaign_redacts_provider_errors() -> None:
    cases = load_routing_eval_cases(CORPUS)[:1]

    with pytest.raises(HarnessRoutingCampaignError) as exc_info:
        run_harness_routing_campaign(
            cases,
            provider="openai",
            model_snapshot="gpt-test-snapshot",
            generation_config=HarnessRoutingGenerationConfig(),
            client_factory=lambda _schema: _FakeClient(RuntimeError("provider-secret-body")),
        )

    assert "RuntimeError" in str(exc_info.value)
    assert "provider-secret-body" not in str(exc_info.value)


def test_frozen_writer_refuses_to_replace_existing_artifact(
    tmp_path: Path,
) -> None:
    cases = load_routing_eval_cases(CORPUS)[:1]
    case = cases[0]
    artifact = run_harness_routing_campaign(
        cases,
        provider="openai",
        model_snapshot="gpt-test-snapshot",
        generation_config=HarnessRoutingGenerationConfig(),
        client_factory=lambda _schema: _FakeClient(
            {
                "decision": {
                    "tool_id": case.acceptable_tools[0],
                    "rationale": "First frozen result.",
                }
            }
        ),
    )
    output = tmp_path / "predictions.json"
    output.write_text("keep-existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_frozen_routing_artifact(output, artifact)

    assert output.read_text(encoding="utf-8") == "keep-existing"
    assert not list(tmp_path.glob("*.tmp"))
