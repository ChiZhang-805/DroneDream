"""Malformed uploads stay inert and cannot corrupt admission bookkeeping."""

from __future__ import annotations

import asyncio
import json
import struct

import pytest

from app.autonomy.qualification import MapAssetAdmissionRegistry


def _admit(data: bytes, filename: str):
    async def chunks():
        yield data

    return asyncio.run(MapAssetAdmissionRegistry().admit("fixture-owner", filename, chunks()))


@pytest.mark.parametrize("filename", ("asset.json", "asset.geojson", "asset.gltf", "asset.glb"))
def test_deep_json_is_rejected_without_parser_stack_escape(filename: str) -> None:
    data = b'{"nested":' + b"[" * 1500 + b"0" + b"]" * 1500 + b"}"
    if filename.endswith(".glb"):
        data += b" " * (-len(data) % 4)
        data = (
            b"glTF"
            + struct.pack("<II", 2, 20 + len(data))
            + struct.pack("<I4s", len(data), b"JSON")
            + data
        )
    receipt = _admit(data, filename)
    assert receipt.status == "rejected"
    assert receipt.planning_qualified is False


@pytest.mark.parametrize("kind", ([], {}))
def test_nonstring_geojson_type_is_rejected(kind: object) -> None:
    receipt = _admit(json.dumps({"type": kind}).encode(), "asset.geojson")
    assert receipt.status == "rejected"


@pytest.mark.parametrize("version", (20, "20.0", True, "2x"))
def test_gltf_version_is_not_admitted_by_string_prefix(version: object) -> None:
    payload = json.dumps({"asset": {"version": version}, "meshes": [{}]}).encode()
    receipt = _admit(payload, "asset.gltf")
    assert receipt.status == "rejected"


@pytest.mark.parametrize("number", ("NaN", "Infinity", "1e999"))
def test_nonfinite_json_geometry_is_rejected(number: str) -> None:
    payload = ('{"type":"Point","coordinates":[' + number + ',0]}').encode()
    receipt = _admit(payload, "asset.geojson")
    assert receipt.status == "rejected"


@pytest.mark.parametrize("limit", (True, -1, 0, 1.5))
def test_receipt_limit_is_validated_before_any_upload(limit: object) -> None:
    with pytest.raises(ValueError, match="maximum_receipts"):
        MapAssetAdmissionRegistry(maximum_receipts=limit)


def test_mutable_upload_chunk_cannot_diverge_from_hashed_bytes() -> None:
    """A retained bytearray could otherwise be changed before final parsing."""
    async def chunks():
        data = bytearray(b'{"label":"first"}')
        yield data
        data[:] = b'{"label":"other"}'

    with pytest.raises(ValueError, match="bytes"):
        asyncio.run(MapAssetAdmissionRegistry().admit("fixture-owner", "asset.json", chunks()))
