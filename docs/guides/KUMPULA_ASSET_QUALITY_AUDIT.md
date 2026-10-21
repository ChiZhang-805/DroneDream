# Kumpula map and My Drone quality contract

This document defines what must be checked before the sole bundled map and
vehicle pair can be described as release-ready. It also records the limits that
must remain visible to product code and users.

## Kumpula map

The bundled map is a **real-data, outdoor/exterior simulation derivative**, not
a complete campus digital twin. Its qualified scope is:

- a 500 m × 500 m local-ENU area;
- a 2048 × 2048 City of Helsinki orthophoto;
- 42 watertight building-footprint extrusion meshes;
- 42 conservative building collision boxes and two mission-pad collisions;
- distinct bilingual semantic entities for Chemicum, Dynamicum, Exactum, and
  Physicum;
- one connected, bilingual, flight-qualified outdoor route between the south
  launch pad and the Chemicum handoff point.

The asset does **not** currently contain building interiors, doors, rooms,
furniture, facade or roof detail, vegetation, street furniture, vehicles,
terrain relief, or additional qualified routes. These are known fidelity gaps,
not files that may be silently inferred or advertised as present.

Every release audit checks:

1. required-file and SDF URI closure;
2. orthophoto format and pixel dimensions;
3. OBJ indices, degenerate faces, watertightness, and building count;
4. finite, positive, uniquely named collision primitives and their conservative
   footprint over-coverage;
5. unique semantic identifiers and distinct authoritative building centroids;
6. Chinese and English building names and aliases;
7. connected navigation nodes, valid edge references, and geometric edge
   distances;
8. explicit fidelity metadata so an exterior map cannot be presented as an
   interior-capable model;
9. binding of unchanged physical world inputs to the recorded PX4/Gazebo flight
   evidence.

## My Drone

`My Drone` is a product wrapper around the PX4 Runtime's pinned
`x500_depth` model. The dependency closure is:

`my_drone → x500_depth → x500 + OakD-Lite → x500_base + mesh files`

Every release audit checks:

1. all model includes and mesh references resolve in the installed Runtime;
2. every dynamic link has finite positive mass and principal inertia;
3. the model contains four motor plugins;
4. visual and collision geometry are both present;
5. barometer, magnetometer, IMU, GNSS, RGB camera, and depth camera sensors are
   present;
6. camera resolution, range, update rate, topic, and optical-center frame are
   explicit;
7. the 0.04 kg mission payload has mass, inertia, collision and visual geometry,
   and a detachable-joint contract;
8. loaded thrust-to-weight remains at or above the qualified threshold;
9. the source wrapper and installed PX4 Runtime stay pinned to the same model
   contract.

The audit command is:

```powershell
python scripts/audit-kumpula-assets.py `
  --map-root backend/app/autonomy/assets/kumpula-campus/gazebo `
  --navigation-graph backend/app/autonomy/assets/kumpula-campus/navigation-graph.json `
  --px4-model-root "\\wsl.localhost\DroneDreamRuntime\opt\PX4-Autopilot\Tools\simulation\gz\models" `
  --output Q:\DroneDream-Workspace\TestRuns\kumpula-asset-quality-audit\audit.json
```

A `verified` result establishes internal completeness for the disclosed outdoor
mission scope. It does not erase or waive the fidelity gaps listed above.
