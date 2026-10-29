"""Shared footprint geometry for map visuals, collision bodies and road clearance."""

from __future__ import annotations

import math
import heapq
from collections import Counter, defaultdict

from shapely import affinity, constrained_delaunay_triangles, STRtree, set_precision
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, nearest_points, substring, unary_union, transform


def footprint_cells(polygon: Polygon, maximum_cell_m: float = 0.25):
    """Cover a footprint without filling its concavities or courtyards.

    Boundary cells conservatively add at most their diagonal to the footprint.
    The same cells supply planner boxes and the physics mesh, so neither side
    silently substitutes a building's much larger bounding rectangle.
    """
    rectangle = list(polygon.minimum_rotated_rectangle.exterior.coords)
    a, b = max(zip(rectangle, rectangle[1:]), key=lambda pair: math.dist(*pair))
    yaw = math.atan2(b[1] - a[1], b[0] - a[0])
    rotated = affinity.rotate(polygon, -yaw, origin=(0, 0), use_radians=True)
    pending, cells = [rotated.bounds], []
    while pending:
        x0, y0, x1, y1 = pending.pop()
        cell = box(x0, y0, x1, y1)
        if not rotated.intersects(cell):
            continue
        if rotated.covers(cell) or max(x1 - x0, y1 - y0) <= maximum_cell_m:
            cells.append((x0, y0, x1, y1))
        elif x1 - x0 >= y1 - y0:
            mid = (x0 + x1) / 2
            pending.extend(((x0, y0, mid, y1), (mid, y0, x1, y1)))
        else:
            mid = (y0 + y1) / 2
            pending.extend(((x0, y0, x1, mid), (x0, mid, x1, y1)))
    while True:
        before = len(cells)
        for axis in (0, 1):
            grouped = defaultdict(list)
            other = 1 - axis
            for cell in cells:
                grouped[cell[other], cell[other + 2]].append((cell[axis], cell[axis + 2]))
            merged = []
            for (lo, hi), intervals in sorted(grouped.items()):
                intervals.sort()
                start, end = intervals[0]
                for next_start, next_end in intervals[1:] + [(math.inf, math.inf)]:
                    if next_start == end:
                        end = next_end
                    else:
                        merged.append((start, lo, end, hi) if axis == 0 else (lo, start, hi, end))
                        start, end = next_start, next_end
            cells = merged
        if len(cells) == before:
            break
    cover = unary_union([box(*cell) for cell in cells])
    return cells, yaw, affinity.rotate(cover, yaw, origin=(0, 0), use_radians=True)


def partition_polygon(geometry, maximum_vertices=1000):
    """Split shells and holes on a micrometre grid, avoiding clipping slivers."""
    geometry = set_precision(geometry, 1e-6)
    pending = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
    result = []
    while pending:
        polygon = pending.pop()
        if polygon.is_empty or polygon.area <= 0:
            continue
        count = len(polygon.exterior.coords)-1 + sum(len(r.coords)-1 for r in polygon.interiors)
        if count <= maximum_vertices:
            result.append(polygon)
            continue
        x0, y0, x1, y1 = polygon.bounds
        cuts = ([box(x0, y0, (x0+x1)/2, y1), box((x0+x1)/2, y0, x1, y1)]
                if x1-x0 >= y1-y0 else
                [box(x0, y0, x1, (y0+y1)/2), box(x0, (y0+y1)/2, x1, y1)])
        for cut in cuts:
            section = set_precision(polygon.intersection(cut), 1e-6)
            parts = [section] if isinstance(section, Polygon) else getattr(section, "geoms", [])
            pending.extend(p for p in parts if isinstance(p, Polygon) and not p.is_empty)
    return result


def extruded_obj(items, *, material_library: str | None = None, material_name="buildings") -> str:
    """Triangulate polygon caps explicitly, including concavities and holes.

    OBJ n-gons leave triangulation to the importer and can fill a courtyard or
    cross an L-shaped roof. Normals and counter-clockwise solid faces are
    emitted explicitly for both Three.js exports and Gazebo/Assimp.
    """
    output = [f"mtllib {material_library}"] if material_library else []
    vertex_offset = normal_index = 0
    for name, geometry, height in items:
        for part_index, part in enumerate([geometry] if isinstance(geometry, Polygon) else geometry.geoms):
            # Triangulate on integer micrometres. Decimal clipping points that
            # are collinear can otherwise form spurious near-zero-area caps.
            lattice = transform(lambda x, y, z=None: (round(x * 1e6), round(y * 1e6)), set_precision(part, 1e-6))
            polygon = orient(lattice, sign=1)
            triangles = list(constrained_delaunay_triangles(polygon).geoms)
            if not unary_union(triangles).equals(polygon):
                raise ValueError(f"{name}: triangulation changed footprint coverage")
            rings = [[(x / 1e6, y / 1e6) for x, y in list(orient(t, sign=1).exterior.coords)[:-1]] for t in triangles]
            occurrences = [point for ring in rings for point in ring]
            parents = list(range(len(occurrences)))

            def root(i):
                while parents[i] != i:
                    parents[i] = parents[parents[i]]
                    i = parents[i]
                return i

            edges = defaultdict(list)
            for i in range(len(rings)):
                for j in range(3):
                    a, b = i*3+j, i*3+(j+1)%3
                    edges[tuple(sorted((occurrences[a], occurrences[b])))].append((a, b))
            for adjacent in edges.values():
                if len(adjacent) == 2:
                    (a, b), (c, d) = adjacent
                    parents[root(a)] = root(d)
                    parents[root(b)] = root(c)
            # Separate touching surface fans; derive walls from the same cap
            # edges so concavities and courtyard pinch points stay manifold.
            vertices, indices = [], {}
            for i, (x, y) in enumerate(occurrences):
                fan = root(i)
                if fan not in indices:
                    indices[fan] = (len(vertices), len(vertices)+1)
                    vertices.extend(((x, y, 0.), (x, y, height)))
            output.append(f"g {name}-{part_index}")
            if material_library:
                output.append(f"usemtl {material_name}")
            output.extend("v " + " ".join(format(v, ".17g") for v in p) for p in vertices)
            faces = []
            for i in range(len(rings)):
                paired = [indices[root(i*3+j)] for j in range(3)]
                faces.extend((tuple(p[1] for p in paired), tuple(p[0] for p in reversed(paired))))
            for adjacent in edges.values():
                if len(adjacent) == 1:
                    first, second = adjacent[0]
                    a, d = indices[root(first)]
                    b, c = indices[root(second)]
                    faces.extend(((a, b, c), (a, c, d)))
            directed = Counter((face[i], face[(i+1)%3]) for face in faces for i in range(3))
            if any(n != 1 or directed[b, a] != 1 for (a, b), n in directed.items()):
                raise ValueError(f"{name}: extrusion is not a closed oriented solid")
            for face in faces:
                a, b, c = [vertices[i] for i in face]
                u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
                n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
                length = math.hypot(*n)
                output.append("vn " + " ".join(format(x / length, ".17g") for x in n))
                normal_index += 1
                output.append("f " + " ".join(f"{vertex_offset+i+1}//{normal_index}" for i in face))
            vertex_offset += len(vertices)
    return "\n".join(output) + "\n"


def surface_network(surface):
    """Medial connections supported entirely by an observed ground polygon.

    The graph joins triangle interiors through shared edges. It cannot jump a
    courtyard, water gap or disconnected pavement just because endpoints are
    nearby. Degree-two chains are simplified only when the surface covers them.
    """
    paths = []
    for polygon in ([surface] if isinstance(surface, Polygon) else surface.geoms):
        if polygon.is_empty or not isinstance(polygon, Polygon):
            continue
        triangles = list(constrained_delaunay_triangles(polygon).geoms)
        edges = defaultdict(list)
        for triangle in triangles:
            center = triangle.centroid.coords[0]
            ring = list(triangle.exterior.coords)
            for a, b in zip(ring, ring[1:]):
                edges[tuple(sorted((a, b)))].append(center)
        segments = []
        for (a, b), centers in edges.items():
            if len(centers) == 2:
                midpoint = ((a[0]+b[0])/2, (a[1]+b[1])/2)
                segments.extend(LineString([c, midpoint]) for c in centers)
        if not segments:
            continue
        merged = linemerge(segments)
        for line in ([merged] if isinstance(merged, LineString) else merged.geoms):
            reduced = line.simplify(.4)
            paths.append(reduced if polygon.covers(reduced) else line)
    return paths


def surface_connections(surface, roads, destinations):
    """Connect source road components and building approaches on observed ground.

    Triangulation is a search structure, not a street map. Keep only the paths
    needed to join existing road components and destination approaches; discard
    its unneeded branches. Every shortcut is covered by the same ground polygon.
    Existing street geometry remains separate and is never replaced by this tree.
    """
    result = []
    parts = [surface] if isinstance(surface, Polygon) else surface.geoms
    for polygon in parts:
        if not isinstance(polygon, Polygon) or polygon.is_empty:
            continue
        local_roads = unary_union(roads).intersection(polygon)
        road_lines = ([local_roads] if isinstance(local_roads, LineString)
                      else [g for g in getattr(local_roads, "geoms", []) if isinstance(g, LineString)])
        road_lines = [line for line in road_lines if not line.is_empty and line.length > 1e-8]
        # One anchor per source-road component is sufficient to connect the
        # entire component, without drawing a second network over every street.
        parents = {}
        def root(p):
            parents.setdefault(p, p)
            while parents[p] != p:
                parents[p] = parents[parents[p]]
                p = parents[p]
            return p
        for line in road_lines:
            a, b = tuple(line.coords[0]), tuple(line.coords[-1])
            parents[root(a)] = root(b)
        anchors = {root(tuple(line.coords[0])): line.interpolate(.5, normalized=True)
                   for line in road_lines}
        terminals = list(anchors.values())
        for destination in destinations:
            if destination.distance(polygon) <= 35.:
                terminals.append(nearest_points(destination, polygon)[1])
        if len(terminals) < 2:
            continue
        search_lines = surface_network(polygon)
        if not search_lines:
            continue
        index = STRtree(search_lines)
        splits, connectors = defaultdict(list), []
        selected = []
        for point in terminals:
            line_index = int(index.nearest(point))
            line = search_lines[line_index]
            target = nearest_points(point, line)[1]
            connection = LineString([point, target])
            if not polygon.covers(connection):
                # A closest edge across a hole is not a legal attachment.
                candidates = index.query(point.buffer(max(5., connection.length * 2)))
                candidates = sorted(candidates, key=lambda i: search_lines[i].distance(point))
                for i in candidates:
                    target = nearest_points(point, search_lines[i])[1]
                    connection = LineString([point, target])
                    if polygon.covers(connection):
                        line_index, line = int(i), search_lines[i]
                        break
                else:
                    continue
            splits[line_index].append(line.project(target))
            connectors.append(connection)
            selected.append(tuple(round(v, 8) for v in target.coords[0]))
        adjacency, segments = defaultdict(list), []
        for i, line in enumerate(search_lines):
            cuts = sorted(set([0., line.length, *splits[i]]))
            for a, b in zip(cuts, cuts[1:]):
                if b-a < 1e-8:
                    continue
                segment = substring(line, a, b)
                left, right = [tuple(round(v, 8) for v in xy) for xy in (segment.coords[0], segment.coords[-1])]
                if left == right:
                    continue
                edge = len(segments)
                segments.append(segment)
                adjacency[left].append((right, segment.length, edge))
                adjacency[right].append((left, segment.length, edge))
        if not selected:
            continue
        pending = set(selected)
        kept = set()
        while pending:
            seed = min(pending)
            distance, previous, heap = {seed: 0.}, {}, [(0., seed)]
            while heap:
                cost, node = heapq.heappop(heap)
                if cost != distance[node]:
                    continue
                for neighbor, weight, edge in adjacency[node]:
                    candidate = cost + weight
                    if candidate < distance.get(neighbor, math.inf):
                        distance[neighbor], previous[neighbor] = candidate, (node, edge)
                        heapq.heappush(heap, (candidate, neighbor))
            for target in pending.intersection(distance):
                node = target
                while node in previous:
                    node, edge = previous[node]
                    if edge in kept:
                        break
                    kept.add(edge)
            pending.difference_update(distance)
        paths = [segments[i] for i in sorted(kept)] + [c for c in connectors if c.length > 1e-8]
        if not paths:
            continue
        merged = unary_union([set_precision(p, 1e-6) for p in paths])
        if not isinstance(merged, LineString):
            merged = linemerge(merged)
        for line in ([merged] if isinstance(merged, LineString) else merged.geoms):
            points = list(line.coords)
            reduced, start = [points[0]], 0
            while start < len(points)-1:
                end = len(points)-1
                while end > start+1 and not polygon.covers(LineString([points[start], points[end]])):
                    end -= 1
                reduced.append(points[end])
                start = end
            result.append(LineString(reduced))
    return result
