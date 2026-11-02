"""Wire-model graph and approval invariants must survive valid-looking payloads."""

import pytest

from app.autonomy.models import (
    MissionTaskGraph,
    RuntimeReplanApplyRequest,
    SimulationExecutionStartRequest,
)


def _node(identity, dependencies=()):
    """Construct schema-valid tasks so rejection tests exercise graph topology."""
    return dict(
        task_id=identity, label=identity, depends_on=list(dependencies),
        executor="mission_executive", risk="low", fallback="hold",
        expected_output="validated transition",
    )


def test_runtime_task_graph_rejects_multi_node_cycles():
    with pytest.raises(ValueError, match="acyclic"):
        MissionTaskGraph(nodes=[_node("first", ["second"]), _node("second", ["first"])])


def test_runtime_task_graph_rejects_repeated_dependency():
    with pytest.raises(ValueError, match="duplicate"):
        MissionTaskGraph(nodes=[_node("first"), _node("second", ["first", "first"])])


def test_runtime_task_graph_rejects_duplicate_active_nodes():
    with pytest.raises(ValueError, match="duplicate"):
        MissionTaskGraph(nodes=[_node("first")], active_node_ids=["first", "first"])


@pytest.mark.parametrize("wire_model", [RuntimeReplanApplyRequest, SimulationExecutionStartRequest])
def test_numeric_one_is_not_explicit_operator_approval(wire_model):
    common = dict(client_request_id="request-boundary", operator_confirmed=1)
    if wire_model is RuntimeReplanApplyRequest:
        payload = common | dict(
            interruption_id="interrupt-" + "a" * 24,
            expected_task_graph_revision=1,
            mission={"edition": "autonomy", "natural_language": "inspect the route"},
        )
    else:
        payload = common | dict(
            runtime_session_id="runtime-" + "a" * 24,
            contract_id="contract-boundary", planner_artifact_sha256="b" * 64,
        )
    with pytest.raises(ValueError):
        wire_model.model_validate(payload)


def test_valid_dag_can_share_a_dependency_without_becoming_a_cycle():
    graph = MissionTaskGraph(nodes=[
        _node("first"), _node("left", ["first"]), _node("right", ["first"]),
        _node("last", ["left", "right"]),
    ])
    assert len(graph.nodes) == 4
