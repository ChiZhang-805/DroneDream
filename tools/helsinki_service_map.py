"""Official service entrances as planar landmarks, separate from flight targets."""

import hashlib
import json
from pathlib import Path

import requests

API = "https://tpr.hel.fi/palvelukarttaws/rest/v4"


def cached_json(path: Path, url: str, refresh: bool):
    if refresh or not path.is_file():
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        payload = response.json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def entrance_entities(records, units, origin, extent):
    """Retain source IDs and XY precision; do not infer an altitude or a door."""
    entities, anchors = [], {}
    x0, y0, x1, y1 = extent
    for record in records:
        if record.get("easting_etrs_gk25") is None or record.get("northing_etrs_gk25") is None:
            continue
        x = float(record["easting_etrs_gk25"]) - origin[0]
        y = float(record["northing_etrs_gk25"]) - origin[1]
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            continue
        unit = units[record["unit_id"]]
        names = list(dict.fromkeys(unit[k] for k in ("name_en", "name_fi", "name_sv") if unit.get(k)))
        identifier = f"tpr-entrance-{record['id']}"
        main = record.get("is_main_entrance") == "Y"
        label = "Main entrance" if main else "Entrance"
        anchors[identifier] = [x, y]
        entities.append({
            "entity_id": identifier,
            "name": f"{names[0] if names else unit['id']} — {label}",
            "aliases": [f"{name} entrance" for name in names],
            "kind": "entrance", "semantic": "facility-anchor",
            "position_m": [x, y],
            "source_pointer": f"/roads/facility_anchors/{identifier}",
            "source": f"{API}/entrance/{record['id']}",
            "service_unit_id": record["unit_id"],
            "is_main_entrance": main,
            "location_claim": "official-service-entrance-planar-record; no-flight-altitude-or-handoff-qualification",
        })
    return entities, anchors


def append_service_entrances(semantic, cache_root: Path, extent, *, refresh=False):
    origin = semantic["origin"]
    origin_xy = (origin["easting_m"], origin["northing_m"])
    source = cache_root / "service-entrances.json"
    records = cached_json(source, f"{API}/entrance/", refresh)
    selected, units, unit_hashes = [], {}, {}
    x0, y0, x1, y1 = extent
    for record in records:
        if not record.get("easting_etrs_gk25") or not record.get("northing_etrs_gk25"):
            continue
        x, y = float(record["easting_etrs_gk25"])-origin_xy[0], float(record["northing_etrs_gk25"])-origin_xy[1]
        if x0 <= x <= x1 and y0 <= y <= y1:
            selected.append(record)
    for identifier in sorted({r["unit_id"] for r in selected}):
        path = cache_root / "service-units" / f"{identifier}.json"
        units[identifier] = cached_json(path, f"{API}/unit/{identifier}", refresh)
        unit_hashes[str(identifier)] = hashlib.sha256(path.read_bytes()).hexdigest()
    entities, anchors = entrance_entities(selected, units, origin_xy, extent)
    semantic["entities"] = [e for e in semantic["entities"] if not e["entity_id"].startswith("tpr-entrance-")] + entities
    existing = semantic.setdefault("roads", {}).setdefault("facility_anchors", {})
    for key in list(existing):
        if key.startswith("tpr-entrance-"):
            del existing[key]
    existing.update(anchors)
    semantic.setdefault("sources", {})["service_entrances"] = {
        "url": f"{API}/entrance/", "license": "CC-BY-4.0",
        "attribution": "City of Helsinki Service Map — https://servicemap.hel.fi",
        "license_source": "https://hri.fi/data/en/dataset/paakaupunkiseudun-palvelukartan-rest-rajapinta",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "unit_sha256": unit_hashes,
    }
    limitation = "Service entrance records have no surveyed altitude or flight qualification; several services may share a doorway."
    limits = semantic.setdefault("known_limits", [])
    if limitation not in limits:
        limits.append(limitation)
    return len(entities)
