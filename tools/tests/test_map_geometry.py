"""Regression checks for real footprint coverage and navigable road junctions."""

import importlib.util
import json
import math
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

from pyproj import Transformer
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box, mapping
from shapely.ops import transform, unary_union
from shapely import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from map_geometry import extruded_obj, footprint_cells, partition_polygon, surface_connections
from helsinki_service_map import entrance_entities

spec = importlib.util.spec_from_file_location("helsinki_maps", Path(__file__).resolve().parents[1] / "build-helsinki-maps.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class FootprintGeometryTest(unittest.TestCase):
    def test_building_approach_tries_clear_road_instead_of_nearer_road_behind_neighbor(self):
        building, neighbor = box(0, 0, 10, 10), box(11, -5, 13, 15)
        roads = [LineString([(14, -4), (14, 14)]), LineString([(-8, -4), (-8, 14)])]
        result = builder.building_ground_approach(building, roads, STRtree(roads),
            box(-20, -20, 20, 20), unary_union([building, neighbor]))
        self.assertIsNotNone(result)
        number, point, distance, access = result
        self.assertEqual(number, 1)
        self.assertEqual(distance, 8.)
        self.assertEqual(LineString(access).intersection(neighbor).length, 0.)
        self.assertEqual(point.x, -8.)

    def test_building_approach_does_not_invent_access_over_unmapped_land_or_canopy(self):
        building = box(0, 0, 10, 10)
        roads = [LineString([(-8, -4), (-8, 14)])]
        narrow_road = box(-10, -10, -6, 20)
        self.assertIsNone(builder.building_ground_approach(
            building, roads, STRtree(roads), narrow_road, building))
        self.assertIsNone(builder.building_ground_approach(
            building, roads, STRtree(roads), box(-20, -20, 20, 20),
            unary_union([building, box(-6, -10, -2, 20)])))

    def test_package_preserves_world_uri_case_for_linux_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            meshes = root / "gazebo/meshes"
            meshes.mkdir(parents=True)
            (meshes / "buildingK.obj").write_text("v 0 0 0\n")
            (meshes / "obsolete.obj").write_text("v 1 1 1\n")
            (root / "gazebo/world.sdf").write_text(
                '<sdf><mesh><uri>meshes/buildingk.obj</uri></mesh></sdf>')
            if not (meshes / "buildingk.obj").is_file():
                with self.assertRaises(FileNotFoundError):
                    builder.map_payloads(root)
                return
            payloads = builder.map_payloads(root)
            self.assertIn("normalized/map/gazebo/meshes/buildingk.obj", payloads)
            self.assertNotIn("normalized/map/gazebo/meshes/buildingK.obj", payloads)
            self.assertNotIn("normalized/map/gazebo/meshes/obsolete.obj", payloads)

    def test_service_entrances_remain_planar_and_keep_distinct_source_ids(self):
        records = [{"id": i, "unit_id": 7, "easting_etrs_gk25": "101",
                    "northing_etrs_gk25": "202", "is_main_entrance": "Y"} for i in (1, 2)]
        records.append({"id": 3, "unit_id": 7, "easting_etrs_gk25": "999",
                        "northing_etrs_gk25": "999"})
        entities, anchors = entrance_entities(records, {7: {"id": 7, "name_en": "Library"}},
                                              (100, 200), (-10, -10, 10, 10))
        self.assertEqual(len(entities), 2)
        self.assertNotEqual(entities[0]["entity_id"], entities[1]["entity_id"])
        for entity in entities:
            self.assertEqual(entity["position_m"], [1., 2.])
            self.assertEqual(anchors[entity["entity_id"]], entity["position_m"])
            self.assertEqual(entity["semantic"], "facility-anchor")

    def test_tree_sensor_visual_matches_its_physical_collision(self):
        xml = builder.sdf_text({"key": "trees", "width_m": 100, "height_m": 100,
                                "latitude": 60., "longitude": 25.}, [],
                               [{"x": 1.234567, "y": -2.345678, "height": 12., "radius": 2.5}])
        link = ElementTree.fromstring(xml).find(".//link[@name='tree-0000']")
        visual, collision = link.find("visual"), link.find("collision")
        self.assertEqual(visual.findtext("pose"), collision.findtext("pose"))
        self.assertEqual(visual.findtext("geometry/box/size"), collision.findtext("geometry/box/size"))
        self.assertEqual(float(visual.findtext("pose").split()[0]), 1.234567)

    def test_routes_keep_continuous_clearance_around_tree_corners(self):
        origin = (25495000., 6675000.)
        to_wgs = Transformer.from_crs(3879, 4326, always_xy=True).transform
        roads = [LineString([(-80, 3.2), (80, 3.2)]),
                 LineString([(-80, -30), (80, -30)])]
        features = [{"type": "Feature", "properties": {},
                     "geometry": mapping(transform(to_wgs, affinity.translate(road, *origin)))} for road in roads]
        ground, tree = box(-90, -90, 90, 90), box(-2, -2, 2, 2)
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "roads.geojson"
            source.write_text(json.dumps({"features": features}))
            graph = builder.load_road_graph(source,
                {"key": "clearance", "name": "Clearance", "width_m": 200, "height_m": 200},
                origin, [], [{"x": 0., "y": 0., "radius": 2.}], ground)
        nodes = {n["node_id"]: (n["position_m"]["x"], n["position_m"]["y"]) for n in graph["nodes"]}
        for edge in graph["edges"]:
            segment = LineString([nodes[edge["from_node"]], nodes[edge["to_node"]]])
            # Subtract vehicle radius and the checker's continuous bound.
            self.assertGreaterEqual(segment.distance(tree) - .38 - .05, .8)
            self.assertGreaterEqual(segment.distance(ground.boundary) - .38 - .05, .8)

    def test_surface_connections_do_not_cross_a_courtyard_or_water_gap(self):
        courtyard = box(12, 8, 28, 32)
        surface = box(0, 0, 40, 40).difference(courtyard)
        roads = [LineString([(3, 5), (3, 35)]), LineString([(37, 5), (37, 35)])]
        connections = surface_connections(surface, roads, [Point(20, 3), Point(20, 37)])
        self.assertTrue(connections)
        self.assertTrue(all(surface.covers(path) for path in connections))
        merged = unary_union([*connections, *roads])
        for target in [Point(20, 3), Point(20, 37)]:
            self.assertLess(merged.distance(target), 1e-7)
        islands = unary_union([box(0, 0, 10, 10), box(20, 0, 30, 10)])
        paths = surface_connections(islands, [], [Point(2, 2), Point(8, 8), Point(22, 2), Point(28, 8)])
        self.assertTrue(all(islands.covers(path) for path in paths))

    def test_mesh_partition_preserves_full_outline_and_holes(self):
        polygon = Point(0, 0).buffer(50, quad_segs=400).difference(box(-10, -10, 10, 10))
        parts = partition_polygon(polygon, maximum_vertices=100)
        self.assertGreater(len(parts), 1)
        self.assertLess(polygon.symmetric_difference(unary_union(parts)).area, polygon.length * 1e-6)
        self.assertTrue(all(len(p.exterior.coords)-1+sum(len(r.coords)-1 for r in p.interiors) <= 100 for p in parts))

    def test_small_buildings_and_heights_above_flight_ceiling_are_retained(self):
        origin = (25495000., 6675000.)
        to_wgs = Transformer.from_crs(3879, 4326, always_xy=True).transform
        features = [{"type": "Feature", "properties": {"vtj_prt": "101589033K", "i_kerrlkm": 40},
                     "geometry": mapping(transform(to_wgs, affinity.translate(box(0, 0, 2, 2), *origin)))}]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "buildings.geojson"
            source.write_text(json.dumps({"features": features}))
            config = {"key": "height", "width_m": 200, "height_m": 200, "ceiling_m": 35}
            estimated = builder.load_buildings(source, config, origin)
            measured = builder.load_buildings(source, config, origin, {"101589033K": {"height_m": 145.2}})
        self.assertEqual(len(estimated), 1)
        self.assertEqual(estimated[0]["id"], "101589033k-0")
        self.assertEqual(estimated[0]["registry_id"], "101589033K")
        self.assertEqual(estimated[0]["height_m"], 136.)
        self.assertEqual(measured[0]["height_m"], 145.2)
        self.assertEqual(measured[0]["height_source"], "Helsinki-LoD2-measured")

    def test_rotated_concavity_and_courtyard_are_not_filled(self):
        for polygon in [
            Polygon([(0, 0), (30, 0), (30, 5), (5, 5), (5, 30), (0, 30)]),
            Polygon([(0, 0), (30, 0), (30, 30), (0, 30)], [[(5, 5), (5, 25), (25, 25), (25, 5)]]),
        ]:
            polygon = affinity.rotate(polygon, 37, origin=(0, 0))
            _, _, cover = footprint_cells(polygon)
            self.assertLess(polygon.difference(cover).area, 1e-9)
            self.assertLess(cover.difference(polygon.buffer(math.sqrt(2)*.25)).area, 1e-9)
            self.assertGreater(polygon.minimum_rotated_rectangle.difference(cover).area, 300)

    def test_extruded_mesh_is_closed_and_has_exact_volume(self):
        polygon = Polygon([(0, 0), (30, 0), (30, 30), (0, 30)], [[(5, 5), (5, 25), (25, 25), (25, 5)]])
        for shape in [polygon, footprint_cells(affinity.rotate(polygon, 23))[2]]:
            raw = extruded_obj([("courtyard", shape, 12)])
            vertices, faces = [], []
            for line in raw.splitlines():
                if line.startswith("v "):
                    vertices.append(tuple(map(float, line.split()[1:])))
                elif line.startswith("f "):
                    faces.append(tuple(int(v.split('/')[0])-1 for v in line.split()[1:]))
            edges = Counter((f[i], f[(i+1)%3]) for f in faces for i in range(3))
            self.assertTrue(all(n == 1 and edges[b, a] == 1 for (a, b), n in edges.items()))
            volume = 0.
            for f in faces:
                a, b, c = [vertices[i] for i in f]
                volume += (a[0]*(b[1]*c[2]-b[2]*c[1]) + a[1]*(b[2]*c[0]-b[0]*c[2]) + a[2]*(b[0]*c[1]-b[1]*c[0]))/6
            self.assertLess(abs(volume - shape.area*12), shape.length * 1e-6 * 12)

    def test_decimal_collinear_canopy_points_do_not_create_sliver_caps(self):
        polygon = Polygon([(61.567693, 33.359912), (62.367693, 32.559912),
                           (68.767693, 26.159912), (70., 36.), (60., 36.)])
        vertices = []
        for line in extruded_obj([("canopy", polygon, 5.4)]).splitlines():
            fields = line.split()
            if fields[0] == "v":
                vertices.append(tuple(map(float, fields[1:])))
            elif fields[0] == "f":
                a, b, c = [vertices[int(f.split('/')[0])-1] for f in fields[1:]]
                u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
                area = math.hypot(u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]) / 2
                self.assertGreater(area, 1e-12)

    def test_short_connectors_and_interior_crossings_remain_connected(self):
        origin = (25495000., 6675000.)
        to_wgs = Transformer.from_crs(3879, 4326, always_xy=True).transform
        roads = [LineString([(-80, 0), (0, 0)]), LineString([(0, 0), (.0002, 0)]),
                 LineString([(.0002, 0), (80, 0)]), LineString([(30, -80), (30, 80)])]
        features = [{"type": "Feature", "id": str(i), "properties": {"silta_alikulku": "Maanpinnan tasossa"},
                     "geometry": mapping(transform(to_wgs, affinity.translate(road, *origin)))} for i, road in enumerate(roads)]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "roads.geojson"
            source.write_text(json.dumps({"features": features}))
            graph = builder.load_road_graph(source, {"key": "junction", "name": "Junction", "width_m": 200, "height_m": 200}, origin, [], [])
        self.assertEqual(graph["component_sizes"], [len(graph["nodes"])])
        self.assertTrue(any(e["distance_m"] < .0005 for e in graph["edges"]))
        self.assertTrue(all(e["distance_m"] > 0 for e in graph["edges"]))
        self.assertTrue(any(abs(n["position_m"]["x"]-30)<1e-5 and abs(n["position_m"]["y"])<1e-5 for n in graph["nodes"]))


if __name__ == "__main__":
    unittest.main()
