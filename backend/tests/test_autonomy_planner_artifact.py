from __future__ import annotations

import asyncio
import copy

import pytest

import app.autonomy.planner_artifact as planner_artifact_module
from app.autonomy.models import AutonomyCompileRequest
from app.autonomy.planner_artifact import (
    PlannerArtifactVerificationError,
    validate_planner_artifact_response,
    verify_planner_artifact_binding,
)

RUN_ID = "11111111-1111-4111-8111-111111111111"
OWNER_ID = "22222222-2222-4222-8222-222222222222"
ARTIFACT_SHA256 = "d" * 64


def _mission() -> AutonomyCompileRequest:
    return AutonomyCompileRequest.model_validate(
        {
            "edition": "sim",
            "execution_target": "simulation",
            "natural_language": "Fly from the office to the takeout pickup and return.",
            "scene_id": "school-campus-v1",
            "asset_context": {
                "harness_context_sha256": "a" * 64,
                "aircraft": {
                    "kind": "aircraft",
                    "asset_id": "aircraft-my-drone",
                    "name": "My Drone",
                    "version": 1,
                    "status": "validated-unsigned",
                    "content_hash": "b" * 64,
                    "qualification_receipt_id": "vehicle-receipt",
                    "capabilities": {},
                },
                "map_pack": {
                    "kind": "map",
                    "asset_id": "map-school",
                    "name": "School Map",
                    "version": 1,
                    "status": "qualified",
                    "content_hash": "c" * 64,
                    "qualification_receipt_id": "map-receipt",
                    "capabilities": {},
                },
                "planner_binding": {
                    "run_id": RUN_ID,
                    "provider": "openai",
                    "model": "gpt-5.2",
                    "artifact_sha256": ARTIFACT_SHA256,
                    "goal": "Collect takeout and return to the office.",
                    "aircraft_id": "aircraft-my-drone",
                    "aircraft_version": 1,
                    "map_id": "map-school",
                    "map_version": 1,
                    "context_sha256": "a" * 64,
                    "task_graph": {
                        "nodes": [
                            {
                                "node_id": "takeoff",
                                "action": "takeoff",
                                "target": "office-drone-launch-pad",
                                "depends_on": [],
                                "success_evidence": ["airborne telemetry"],
                            },
                            {
                                "node_id": "pickup",
                                "action": "pickup",
                                "target": "takeout-pickup",
                                "depends_on": ["takeoff"],
                                "success_evidence": ["payload attached"],
                            },
                            {
                                "node_id": "return",
                                "action": "return",
                                "target": "office-drone-launch-pad",
                                "depends_on": ["pickup"],
                                "success_evidence": ["office reached"],
                            },
                            {
                                "node_id": "land",
                                "action": "land",
                                "target": "office-drone-launch-pad",
                                "depends_on": ["return"],
                                "success_evidence": ["landed telemetry"],
                            },
                        ]
                    },
                },
            },
        }
    )


def _issued_envelope(mission: AutonomyCompileRequest) -> dict[str, object]:
    planner = mission.asset_context.planner_binding  # type: ignore[union-attr]
    return {
        "data": {
            "run_id": planner.run_id,
            "owner_user_id": OWNER_ID,
            "edition": mission.edition,
            "provider": planner.provider,
            "model": planner.model,
            "state": "completed",
            "stage": "completed",
            "result_json": {
                "run_id": planner.run_id,
                "artifact_kind": "autonomy_mission_plan",
                "artifact_sha256": planner.artifact_sha256,
                "artifact_payload": {
                    "schema_version": "dronedream.autonomy.planner-response.v1",
                    "status": "draft",
                    "goal": planner.goal,
                    "asset_bindings": {
                        "aircraft_id": planner.aircraft_id,
                        "aircraft_version": planner.aircraft_version,
                        "map_id": planner.map_id,
                        "map_version": planner.map_version,
                        "context_sha256": planner.context_sha256,
                    },
                    "task_graph": planner.task_graph.model_dump(mode="json"),
                    "safety_policy": {"actuator_authority": False},
                },
            },
        }
    }


def test_accepts_exact_owner_scoped_server_issued_artifact() -> None:
    mission = _mission()
    validate_planner_artifact_response(mission, OWNER_ID, _issued_envelope(mission))


def test_authenticated_verifier_returns_an_immutable_server_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission = _mission()
    captured: dict[str, str] = {}

    def fake_fetch(run_id: str, authorization: str, _settings) -> dict[str, object]:
        captured.update(run_id=run_id, authorization=authorization)
        return _issued_envelope(mission)

    monkeypatch.setattr(planner_artifact_module, "_fetch_run", fake_fetch)

    receipt = asyncio.run(
        verify_planner_artifact_binding(mission, "bearer signed-user-token", OWNER_ID)
    )

    assert captured == {"run_id": RUN_ID, "authorization": "Bearer signed-user-token"}
    assert receipt.owner_subject == OWNER_ID
    assert receipt.artifact_sha256 == ARTIFACT_SHA256


def test_verifier_rejects_a_missing_owner_bearer_before_network_access() -> None:
    with pytest.raises(PlannerArtifactVerificationError) as rejected:
        asyncio.run(verify_planner_artifact_binding(_mission(), None, OWNER_ID))

    assert rejected.value.code == "AUTONOMY_PLANNER_IDENTITY_REQUIRED"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("data", "owner_user_id"), "another-owner"),
        (("data", "state"), "processing"),
        (("data", "result_json", "artifact_sha256"), "e" * 64),
        (
            ("data", "result_json", "artifact_payload", "task_graph", "nodes", 1, "target"),
            "forged-pickup",
        ),
    ],
)
def test_rejects_fabricated_or_cross_owner_planner_receipts(
    path: tuple[str | int, ...],
    value: object,
) -> None:
    mission = _mission()
    envelope = copy.deepcopy(_issued_envelope(mission))
    cursor: object = envelope
    for key in path[:-1]:
        cursor = cursor[key]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]

    with pytest.raises(PlannerArtifactVerificationError) as rejected:
        validate_planner_artifact_response(mission, OWNER_ID, envelope)

    assert rejected.value.code == "AUTONOMY_PLANNER_ARTIFACT_MISMATCH"
    assert rejected.value.status_code == 403
