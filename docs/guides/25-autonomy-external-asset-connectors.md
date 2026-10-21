# DroneDream · AGENT external asset connectors

## Product boundary

DroneDream · AGENT is not a general-purpose CAD, DCC, GIS, or robot-modeling application.
Geometry is authored in specialist tools. DroneDream imports inert content,
normalizes it to `.ddpkg` v1, validates its declared physics, and qualifies an
exact map–vehicle pair against a pinned ROS 2 / Gazebo / PX4 environment.

The existing parameter editors remain available during migration as constrained
templates. Existing user drafts are preserved. They must not be presented as a
replacement for Blender, SolidWorks, Fusion, Onshape, FreeCAD, or GIS tools.

## Trust boundary

The public connector catalog is available at `GET /api/v1/autonomy/asset-connectors`.
It distinguishes three execution boundaries:

- `declarative_parser`: core-owned parsers for inert `.ddpkg`, SDF, and URDF data.
- `isolated_local_companion`: local software such as Blender/Phobos, Xacro,
  FreeCAD, or GDAL that must run outside the core process.
- `isolated_plugin`: separately installed connectors such as commercial CAD or
  cloud translators.

Imported code is never executed by default. An optional connector cannot claim
the core declarative-parser boundary, and it is not reported as enabled until a
healthy companion or plugin is installed.

## Normalized package and maturity

Every connector targets `.ddpkg` v1 and preserves source application, format,
adapter identity, and content hash. Asset maturity is explicit:

1. `visual_only`
2. `physics_ready`
3. `simulation_ready`
4. `flight_ready`
5. `qualified`

Import does not imply qualification. Qualification is issued only after the
normalized content is bound to the exact environment versions and the required
geometry, collision, inertia, sensor, spawn, control, flight, landing, and
evidence checks pass.

## Migration order

1. Expose connector availability in the map and aircraft libraries.
2. Route native projects through isolated companions/plugins and return `.ddpkg`.
3. Admit normalized content at its measured maturity without hiding drafts.
4. Run local map–vehicle pair qualification and bind the resulting hashes.
5. Make the qualified version selectable for mission planning and execution.
6. Retire only redundant general-modeling UI after saved drafts have a verified
   export/import path.
