"""Official HSY road surfaces and height-class canopy, in the map's local frame."""

import json
from pathlib import Path

import requests
from shapely import affinity, make_valid, set_precision
from shapely.geometry import Polygon, box, shape
from shapely.ops import unary_union

HSY_WFS = "https://kartta.hsy.fi/geoserver/wfs"
GROUND_LAYERS = ("paallystetty_tie", "paallystamaton_tie", "muu_vetta_lapaisematon_pinta")
CANOPY_LAYERS = ("puusto_2_10m", "puusto_10_15m", "puusto_15_20m", "puusto_yli20m")
ATTRIBUTION = "Helsinki metropolitan area land cover dataset: © HSY and municipalities in the region 2024; background materials: © National Land Survey of Finland 2024, © Finnish Transport Agency, Digiroad 2024"


def acquire_layers(root: Path, bounds, *, refresh=False):
    session = requests.Session()
    paths = {}
    for layer in (*GROUND_LAYERS, *CANOPY_LAYERS, "rakennus"):
        path = root / f"{layer}.geojson"
        if refresh or not path.is_file():
            features, start = [], 0
            while True:
                response = session.get(HSY_WFS, params={
                    "service": "WFS", "version": "2.0.0", "request": "GetFeature",
                    "typeNames": f"asuminen_ja_maankaytto:maanpeite_{layer}_2024",
                    "srsName": "EPSG:3879", "outputFormat": "application/json",
                    "bbox": ",".join(map(str, bounds))+",EPSG:3879", "count": 2000, "startIndex": start,
                }, timeout=180)
                response.raise_for_status()
                payload = response.json()
                page = payload["features"]
                features.extend(page)
                start += len(page)
                if len(page) < 2000:
                    break
            payload["features"] = features
            payload["numberReturned"] = len(features)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        paths[layer] = path
    return paths


def polygon_parts(geometry):
    if isinstance(geometry, Polygon):
        if not geometry.is_empty:
            yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from polygon_parts(part)


def load_land_cover(paths, config, origin):
    crop = box(-config["width_m"]/2, -config["height_m"]/2,
               config["width_m"]/2, config["height_m"]/2)
    surfaces, canopies = [], []
    for layer in (*GROUND_LAYERS, *CANOPY_LAYERS):
        payload = json.loads(paths[layer].read_text(encoding="utf-8"))
        for feature in payload["features"]:
            geometry = set_precision(affinity.translate(make_valid(shape(feature["geometry"])), -origin[0], -origin[1]).intersection(crop), 1e-6)
            for index, polygon in enumerate(polygon_parts(geometry)):
                if layer in GROUND_LAYERS:
                    surfaces.append(polygon)
                else:
                    props = feature["properties"]
                    canopies.append({"id": f"{props['kohde_id']}-{index}", "polygon": polygon,
                                     "height_m": float(props["korkeus_ka_m"]),
                                     "height_source": "HSY-2024-mean-canopy-height", "source_layer": layer})
    return unary_union(surfaces), canopies
