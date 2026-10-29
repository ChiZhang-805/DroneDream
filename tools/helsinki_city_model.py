"""Read registry-linked measured heights from Helsinki's official LoD2 tiles.

The public city viewer supplies these 3D Tiles / glTF metadata records. Matching
uses VTJ_PRT, never an approximate address or the nearest building.
"""

import hashlib
import json
import math
import struct
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

CITY_MODEL_URL = "https://kartta.hel.fi/3d/datasource-data/16fc3fd5-df6d-4f48-bfd5-9aeee430a02f/tileset.json"


def metadata_records(raw: bytes) -> list[dict]:
    magic, version, length = struct.unpack_from("<4sII", raw)
    if magic != b"glTF" or version != 2 or length != len(raw):
        raise ValueError("Expected a complete GLB 2 city-model tile")
    chunks, offset = {}, 12
    while offset < len(raw):
        size, kind = struct.unpack_from("<I4s", raw, offset)
        chunks[kind] = raw[offset+8:offset+8+size]
        offset += 8+size
    document = json.loads(chunks[b"JSON"])
    binary = chunks[b"BIN\x00"]
    metadata = document["extensions"]["EXT_structural_metadata"]

    def view(index):
        entry = document["bufferViews"][index]
        start = entry.get("byteOffset", 0)
        return binary[start:start+entry["byteLength"]]

    records = []
    formats = {"INT32": "i", "UINT32": "I", "FLOAT32": "f", "FLOAT64": "d", "UINT64": "Q"}
    for table in metadata["propertyTables"]:
        schema = metadata["schema"]["classes"][table["class"]]["properties"]
        rows = [{} for _ in range(table["count"])]
        for name, source in table["properties"].items():
            if name not in {"id", "VTJ_PRT", "RATU", "height", "height.status", "height_uom",
                            "height.lowReference", "height.highReference", "__PARENT_FEATURE"}:
                continue
            field = schema[name]
            values = view(source["values"])
            if field["type"] == "STRING":
                fmt = formats[source.get("stringOffsetType", "UINT32")]
                offsets = struct.unpack("<"+str(table["count"]+1)+fmt, view(source["stringOffsets"]))
                decoded = [values[offsets[i]:offsets[i+1]].decode("utf-8") for i in range(table["count"])]
            else:
                decoded = struct.unpack("<"+str(table["count"])+formats[field["componentType"]], values)
            for row, value in zip(rows, decoded, strict=True):
                if value != field.get("noData"):
                    row[name] = value
        records.extend(rows)
    return records


def acquire_measured_heights(bounds_wgs84, cache_root: Path, *, refresh=False) -> dict:
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=4, backoff_factor=1., status_forcelist=(429, 502, 503, 504), allowed_methods={"GET"})))
    visited, tiles, records = set(), [], []
    crop = tuple(map(math.radians, bounds_wgs84))

    def fetch(url):
        relative = urlparse(url).path.split("16fc3fd5-df6d-4f48-bfd5-9aeee430a02f/", 1)[1]
        path = cache_root / "city-model" / relative
        if refresh or not path.is_file():
            response = session.get(url, timeout=180)
            response.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
        return path.read_bytes()

    def visit(node, base):
        region = node.get("boundingVolume", {}).get("region")
        if region and (region[2] < crop[0] or region[0] > crop[2] or region[3] < crop[1] or region[1] > crop[3]):
            return
        uri = node.get("content", {}).get("uri")
        # Coarse replacement tiles can omit small buildings. Read the finest
        # intersecting tiles rather than assuming that a parent's feature table
        # is a complete registry for every child.
        replacement_children = node.get("children") and node.get("refine", "REPLACE") == "REPLACE"
        if uri and not (replacement_children and not uri.endswith(".json")):
            url = urljoin(base, uri)
            if url not in visited:
                visited.add(url)
                raw = fetch(url)
                if url.endswith(".json"):
                    visit(json.loads(raw)["root"], url)
                else:
                    rows = metadata_records(raw)
                    records.extend(rows)
                    tiles.append({"url": url, "sha256": hashlib.sha256(raw).hexdigest()})
        for child in node.get("children", []):
            visit(child, base)

    visit(json.loads(fetch(CITY_MODEL_URL))["root"], CITY_MODEL_URL)
    measured = {}
    for row in records:
        identifier, height = row.get("VTJ_PRT"), row.get("height")
        if (identifier and isinstance(height, (int, float)) and 0 < height < 1000
                and row.get("height.status") == "measured" and row.get("height_uom") in {"m", "urn:adv:uom:m"}
                and row.get("height.lowReference") == "lowestGroundPoint"
                and row.get("height.highReference") == "topOfConstruction"):
            existing = measured.get(identifier)
            if existing is None or existing["height_m"] < height:
                measured[identifier] = {"height_m": height, "city_model_id": row.get("id"),
                                        "reference": "lowestGroundPoint-to-topOfConstruction"}
    return {"source_url": CITY_MODEL_URL, "license": "CC-BY-4.0", "tiles": tiles, "buildings": measured}
