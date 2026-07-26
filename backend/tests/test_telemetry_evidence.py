from __future__ import annotations

from copy import deepcopy

import pytest

from app.simulator.artifact_schema import validate_telemetry_payload
from app.simulator.telemetry_evidence import (
    TELEMETRY_SCHEMA_V2,
    TelemetrySemanticContractError,
    compile_telemetry_semantic_contract,
    verify_telemetry_semantic_contract,
)


def _samples() -> list[dict[str, float]]:
    return [
        {
            "t": round(index * 0.1, 6),
            "x": round(index * 0.05, 6),
            "y": 0.0,
            "z": 3.0,
            "vx": 0.5,
            "vy": 0.0,
            "vz": 0.0,
            "yaw": 0.0,
        }
        for index in range(20)
    ]


def _payload() -> dict[str, object]:
    samples = _samples()
    contract = compile_telemetry_semantic_contract(
        samples=samples,
        source_bytes=b"raw-telemetry-source",
        source_kind="launcher_json",
        extraction_revision="test-normalizer-1.0",
        synthetic=False,
    )
    return {
        "schema_version": TELEMETRY_SCHEMA_V2,
        "samples": samples,
        "meta": {"source": "test"},
        "semantic_contract": contract.model_dump(mode="json"),
    }


def test_telemetry_v2_contract_round_trips_and_is_content_addressed() -> None:
    payload = _payload()

    verified = verify_telemetry_semantic_contract(payload)

    assert verified is not None
    assert verified.position_unit == "m"
    assert verified.velocity_unit == "m/s"
    assert verified.attitude_unit == "rad"
    assert verified.time_unit == "s"
    assert verified.coordinate_frame == (
        "dronedream_local_cartesian_z_up"
    )
    assert verified.sampling.sample_count == 20
    assert verified.sampling.duration_s == pytest.approx(1.9)
    assert validate_telemetry_payload(payload) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "sample",
        "unit",
        "sampling",
        "source_digest",
    ],
)
def test_telemetry_v2_rejects_sample_or_contract_mutation(
    mutation: str,
) -> None:
    payload = deepcopy(_payload())
    contract = payload["semantic_contract"]
    assert isinstance(contract, dict)
    if mutation == "sample":
        samples = payload["samples"]
        assert isinstance(samples, list)
        sample = samples[3]
        assert isinstance(sample, dict)
        sample["x"] = 999.0
    elif mutation == "unit":
        contract["position_unit"] = "cm"
    elif mutation == "sampling":
        sampling = contract["sampling"]
        assert isinstance(sampling, dict)
        sampling["max_gap_s"] = 0.0
    else:
        contract["source_sha256"] = "sha256:" + "0" * 64

    assert verify_telemetry_semantic_contract(payload) is None
    assert validate_telemetry_payload(payload) == [
        "telemetry v2 semantic contract is missing or does not match "
        "the samples"
    ]


def test_telemetry_v2_rejects_large_sampling_hole() -> None:
    samples = _samples()
    for index in range(10, len(samples)):
        samples[index]["t"] += 2.0

    with pytest.raises(
        TelemetrySemanticContractError,
        match="maximum gap",
    ):
        compile_telemetry_semantic_contract(
            samples=samples,
            source_bytes=b"gapped-source",
            source_kind="launcher_json",
            extraction_revision="test-normalizer-1.0",
            synthetic=False,
        )


def test_telemetry_v2_requires_ulog_origin_provenance() -> None:
    with pytest.raises(
        ValueError,
        match="ULog telemetry requires complete origin provenance",
    ):
        compile_telemetry_semantic_contract(
            samples=_samples(),
            source_bytes=b"normalized-ulog",
            source_kind="px4_ulog",
            extraction_revision="test-normalizer-1.0",
            synthetic=False,
        )
