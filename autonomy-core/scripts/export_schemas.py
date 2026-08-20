"""Export deterministic JSON Schemas for every cross-process contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from dronedream_agent_core.contracts import (
    CoveragePattern,
    CoveragePlanRequest,
    FlightPlan,
    GraphRoute,
    IntentArtifact,
    MissionContract,
    MissionLifecycleBinding,
    MissionRequest,
    ModelCallRecord,
    PlannerContribution,
    PlannerValidation,
    PlanRevisionRecord,
    PluginInvocationPlan,
    PreparedMission,
    Px4GazeboRunEvidence,
    Px4Track,
    Px4TrackRequest,
    RouteAlternativeCandidate,
    RouteAlternativeDecision,
    RouteAlternativeSet,
    RouteClearanceReport,
    RouteQuery,
    RuntimeAmendmentDirective,
    RuntimeAuthorizedCommand,
    RuntimeCheckpointDecision,
    RuntimeCheckpointRequest,
    RuntimeCommandAdoption,
    RuntimeControlSession,
    RuntimeHoldAcknowledgement,
    RuntimeInterruptionDecision,
    RuntimeMessageClassification,
    RuntimeOperatorControlCommand,
    RuntimeOperatorTakeoverAdoption,
    RuntimeOperatorTakeoverGrant,
    RuntimeReplacementTrack,
    RuntimeUserMessage,
    SemanticPlan,
    SimulationWorkflowResult,
    TaskGraphArtifact,
    TaskThread,
    ToolReceipt,
)
from dronedream_agent_core.plugin_contracts import (
    CapabilityBrokerReceipt,
    PluginLifecycleReceipt,
    PluginManifest,
    PluginSnapshot,
)

CONTRACTS = (
    MissionRequest,
    IntentArtifact,
    MissionContract,
    TaskGraphArtifact,
    SemanticPlan,
    PlannerContribution,
    PlannerValidation,
    FlightPlan,
    RouteQuery,
    GraphRoute,
    RouteClearanceReport,
    RouteAlternativeCandidate,
    RouteAlternativeSet,
    RouteAlternativeDecision,
    CoveragePlanRequest,
    CoveragePattern,
    Px4TrackRequest,
    Px4Track,
    RuntimeCheckpointRequest,
    RuntimeCheckpointDecision,
    TaskThread,
    PlanRevisionRecord,
    MissionLifecycleBinding,
    PluginManifest,
    PluginSnapshot,
    PluginLifecycleReceipt,
    CapabilityBrokerReceipt,
    PluginInvocationPlan,
    RuntimeControlSession,
    RuntimeUserMessage,
    RuntimeHoldAcknowledgement,
    RuntimeMessageClassification,
    RuntimeAmendmentDirective,
    RuntimeInterruptionDecision,
    RuntimeAuthorizedCommand,
    RuntimeCommandAdoption,
    RuntimeOperatorTakeoverGrant,
    RuntimeOperatorControlCommand,
    RuntimeOperatorTakeoverAdoption,
    RuntimeReplacementTrack,
    ModelCallRecord,
    ToolReceipt,
    PreparedMission,
    Px4GazeboRunEvidence,
    SimulationWorkflowResult,
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def expected_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    index_entries: list[dict[str, str]] = []
    for contract in CONTRACTS:
        filename = f"{contract.__name__}.schema.json"
        payload = _json_bytes(contract.model_json_schema())
        files[filename] = payload
        index_entries.append(
            {
                "contract": contract.__name__,
                "file": filename,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    files["index.json"] = _json_bytes(
        {
            "schema_version": "dronedream.schema-index.v1",
            "contracts": index_entries,
        }
    )
    return files


def export(output_dir: Path, *, check: bool) -> int:
    expected = expected_files()
    mismatches: list[str] = []
    if check:
        for filename, payload in expected.items():
            path = output_dir / filename
            if not path.is_file() or path.read_bytes() != payload:
                mismatches.append(filename)
        if output_dir.is_dir():
            expected_names = set(expected)
            for path in output_dir.glob("*.json"):
                if path.name not in expected_names:
                    mismatches.append(f"unexpected:{path.name}")
        if mismatches:
            print("Schema export is stale: " + ", ".join(sorted(mismatches)))
            return 1
        print(f"SCHEMAS_CURRENT count={len(CONTRACTS)} directory={output_dir}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.glob("*.json"):
        if path.name not in expected:
            path.unlink()
    for filename, payload in expected.items():
        (output_dir / filename).write_bytes(payload)
    print(f"SCHEMAS_EXPORTED count={len(CONTRACTS)} directory={output_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "schemas",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return export(args.output_dir, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
