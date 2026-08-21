# AUTONOMY external asset integration

## Product boundary

DroneDream does not replace Blender, Phobos, SOLIDWORKS, Fusion, Onshape,
FreeCAD, QGIS, ROS 2, Gazebo, or PX4 authoring tools. It imports their outputs,
normalizes them into Asset IR and `.ddpkg`, validates them, and decides whether
they may enter a simulation or flight workflow.

The existing Vehicle Studio remains available only as a constrained template
editor while saved drafts are migrated. It must not grow into a general CAD or
DCC surface.

## Trust boundary

- Built-in declarative parsers may read inert `.ddpkg`, SDF, and URDF data.
- Native projects and executable conversions run only in an isolated local
  companion or an isolated plugin.
- Imported code never executes by default.
- A connector may declare at most the maturity supported by its source data.
  DroneDream qualification, not the connector, issues the final credential.

## Shared lifecycle

`created -> quarantining -> parsing -> needs_input -> normalizing -> building -> validating -> qualified | failed | cancelled`

Every transition is bound to source hashes, connector identity, schema version,
and a durable receipt. Replayed or mismatched companion results fail closed.

## Maturity levels

| Level | State | Meaning |
| --- | --- | --- |
| L1 | `visual_only` | Rendering only; no physics claim |
| L2 | `physics_ready` | Collision, mass, inertia, joints, and materials validated |
| L3 | `simulation_ready` | Spawns and behaves correctly in the selected simulator |
| L4 | `flight_ready` | PX4/ROS 2 interfaces and controlled flight sequence validated |
| L5 | `qualified` | Policy, evidence, hashes, and reproducibility checks all pass |

## Five-product ownership

- **Universal** selects and coordinates the five product workspaces.
- **SIM** runs Gazebo/PX4 simulation and deterministic evidence capture.
- **LAB** performs calibration, physics review, and qualification analysis.
- **FIELD** owns hardware authorization, preflight, operation, and recovery.
- **AUTONOMY** owns natural-language mission planning, iterative verification,
  replanning, tool/plugin orchestration, and mission evidence.

The edition-neutral connector catalog is shared. Simulation, laboratory,
hardware, and autonomous execution authorities remain separate.

## Connector extension slots

`source_adapter`, `format_parser`, `geometry_normalizer`,
`collision_generator`, `inertia_provider`, `dynamics_profile`,
`sensor_adapter`, `autopilot_adapter`, `ros_interface_adapter`,
`runtime_builder`, `validator`, `qualification_policy`, and `asset_publisher`.

Optional slots are inactive until the installed provider is healthy. Exclusive
slots allow one active provider; composable validator and publisher slots may
run multiple compatible providers under explicit ordering and failure policy.
