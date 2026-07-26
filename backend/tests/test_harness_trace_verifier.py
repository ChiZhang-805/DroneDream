from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.orchestration.decision_harness import (
    HARNESS_DECISION_TRACE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
    build_decision_messages,
)
from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
    eligible_harness_tools,
    provider_tool_manifest,
)
from app.orchestration.harness_evaluation import (
    compile_routing_eval_snapshot,
    load_routing_eval_cases,
)
from scripts.verify_harness_decision_traces import (
    TraceInputError,
    load_trace_records,
    main,
    verify_trace_records,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_trace() -> dict[str, object]:
    corpus = Path(__file__).parent / "fixtures" / "harness_routing_eval_v1.jsonl"
    snapshot = compile_routing_eval_snapshot(load_routing_eval_cases(corpus)[0])
    evidence = snapshot.model_dump(mode="json", exclude_none=True)
    allowed_tools = eligible_harness_tools(snapshot)
    manifest = provider_tool_manifest(allowed_tools)
    system, user = build_decision_messages(snapshot, tool_manifest=manifest)
    return {
        "trace_schema_version": HARNESS_DECISION_TRACE_SCHEMA_VERSION,
        "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
        "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
        "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        "allowed_tools": list(allowed_tools),
        "evidence_snapshot": evidence,
        "evidence_sha256": _sha256(_canonical_json(evidence)),
        "tool_manifest": manifest,
        "tool_manifest_sha256": _sha256(_canonical_json(manifest)),
        "prompt_sha256": _sha256(f"{system}\n{user}"),
    }


def test_verifier_accepts_raw_trace_and_ignores_unrelated_event() -> None:
    trace = _valid_trace()
    report = verify_trace_records(
        [
            {
                "id": "evt_other",
                "job_id": "job_1",
                "event_type": "trial_completed",
                "payload_json": {},
            },
            trace,
        ]
    )

    assert report["record_count"] == 2
    assert report["trace_count"] == 1
    assert report["ignored_event_count"] == 1
    assert report["valid_trace_count"] == 1
    assert report["invalid_trace_count"] == 0
    assert report["all_traces_valid"] is True
    assert report["input_failures"] == []


def test_verifier_fails_closed_on_tampered_event_envelope() -> None:
    trace = _valid_trace()
    evidence = trace["evidence_snapshot"]
    assert isinstance(evidence, dict)
    budget = evidence["budget"]
    assert isinstance(budget, dict)
    budget["remaining_trials"] -= 1

    report = verify_trace_records(
        [
            {
                "id": "evt_tampered",
                "job_id": "job_1",
                "event_type": "harness_decision_started",
                "payload_json": trace,
            }
        ]
    )

    assert report["all_traces_valid"] is False
    assert report["invalid_trace_count"] == 1
    traces = report["traces"]
    assert isinstance(traces, list)
    result = traces[0]
    assert isinstance(result, dict)
    assert result["event_id"] == "evt_tampered"
    failures = result["failures"]
    assert isinstance(failures, list)
    assert "evidence_sha256_mismatch" in failures
    assert "prompt_sha256_mismatch" in failures


def test_verifier_rejects_export_without_decision_traces() -> None:
    report = verify_trace_records([{"event_type": "job_created", "payload_json": {}}])

    assert report["all_traces_valid"] is False
    assert report["input_failures"] == ["no_harness_decision_started_traces"]


def test_loader_supports_json_array_and_jsonl(tmp_path: Path) -> None:
    array_path = tmp_path / "traces.json"
    array_path.write_text(json.dumps([_valid_trace()]), encoding="utf-8")
    jsonl_path = tmp_path / "traces.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(item) for item in [_valid_trace(), _valid_trace()]),
        encoding="utf-8",
    )

    assert len(load_trace_records(array_path)) == 1
    assert len(load_trace_records(jsonl_path)) == 2


def test_loader_rejects_invalid_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    path.write_text('{"event_type":"job_created"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(TraceInputError, match="line 2"):
        load_trace_records(path)


def test_cli_exit_code_is_machine_gateable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    valid_path = tmp_path / "valid.json"
    valid_path.write_text(json.dumps(_valid_trace()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verify_harness_decision_traces.py", str(valid_path)],
    )
    assert main() == 0
    valid_output = json.loads(capsys.readouterr().out)
    assert valid_output["all_traces_valid"] is True

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["verify_harness_decision_traces.py", str(invalid_path)],
    )
    assert main() == 1
    invalid_output = json.loads(capsys.readouterr().out)
    assert invalid_output["all_traces_valid"] is False
