# Aircraft and import review — 2026-10-13

The default catalog now admits only X500 Depth. Candidate selection prioritizes
the current campus perception/pickup workflow, not a claim about market share.
X500 Flow was also evaluated through the actual importer and qualification
preparation: the model-only archive normalizes but fails with
`ASSET_QUALIFICATION_CONTRACT_MISSING:dronedream.vehicle.v1`; the full five-model
dependency archive fails with `ASSET_SOURCE_ENTRYPOINT_AMBIGUOUS`. It has not
passed a flight test and is removed from the default catalog along with the
other eleven variants. Actual user imports and historical evidence are preserved.
Evidence: `Q:\DroneDream-Workspace\TestRuns\Aircraft-Selection-20261013\candidate-review.json`.

Depth's bundled package was inspected and its current campus round-trip
preparation passed using a 500 m candidate search range; the generic 30 m
range contains no usable campus round trip. This is a preparation recheck,
not a new physical flight. The pinned Agent Core
`asset_pair_catalog.py` lists one exact qualified pair: normalized
`dronedream.my-drone.v1` (X500 Depth) and `dronedream.school-map.v1` (Kumpula),
qualification `asset-qualification-54d4f94f3633bccf433f3f31`.
The other twelve reviewed sources remain historical metadata and are no longer
offered by the default resource API, cards, or selectors. Even the qualified built-in pair
does not prove arbitrary natural-language pickup/delivery missions succeed.

| Aircraft | Main distinction | Current campus execution evidence |
| --- | --- | --- |
| X500 Depth | RGB and depth camera | Exact normalized built-in pair has a receipt |
| X500 Flow | Optical flow and downward ranging | Not qualified |
| X500 Down LiDAR | Downward distance sensor | Not qualified |
| X500 Front LiDAR | Forward ranging | Not qualified |
| X500 Front Cam | Forward monocular camera | Not qualified |
| X500 Down Cam | Downward monocular camera | Not qualified |
| X500 2D LiDAR | Planar laser scan | Not qualified |
| X500 Vision | Visual-odometry configuration | Not qualified |
| X500 Gimbal | Gimballed camera | Not qualified |
| X500 Standard | Base multicopter navigation sensors | Not qualified |
| Standard VTOL | Lift-and-cruise configuration | Not qualified |
| Tiltrotor VTOL | Tilting rotors | Not qualified |
| Tailsitter VTOL | Tail-sitting transition | Not qualified |

Most X500 variants share the airframe but differ in sensor placement and
observability; a downward sensor does not provide forward obstacle depth.
VTOL transition, flight envelope, and recovery differ substantially from the
multicopters. Recommended uses in the source catalog are not validated missions.

## Import contract

- Aircraft: choose one package/model file or one complete model/dependencies
  directory in the dialog. These are alternative sources, not two required
  uploads. The enabled built-in adapter registry determines file filters
  (`.ddpkg`, `.zip`, `.sdf`, `.world`, `.urdf` where admitted by the vehicle
  adapter). Native import snapshots the selected source before the received
  checkmark. A directory/package must retain its referenced models, meshes,
  textures, and declarative configuration. A lone model with missing dependencies
  remains incomplete; it is never marked flight-qualified by this dialog.
- External CAD/Blender/plugin-only formats are excluded from the ordinary local
  chooser unless a working built-in adapter admits them. Dependency/conversion
  failures preserve the received source and allow replacement/retry.
- Maps: one `.ddpkg`/`.zip` complete package; or one `.yaml` scene with its resource
  directory; or one `.sdf`/`.world` scene with a resource directory and supported
  places/entrances and navigation JSON files. Each slot accepts one source;
  resources are a directory containing multiple files. The native map preparation
  contract resolves which supplementary files are needed. Complete packages do
  not require redundant uploads. File types are shown in the native chooser.
- Upload and normalization do not grant execution qualification. Ordinary imports
  invoke no paid AI. Maps remains the current Kumpula resource plus actual user
  imports; historical Open-RMF demo maps are still retired.

## UI delivery

Maps and Aircraft share a left double-click hint and right Import button. Card
footers contain only the name and delete icon. Import aircraft now opens a file/
folder receipt dialog. Settings uses square annual cells, expanding bar charts,
seven environment rows (including actual GPU driver and free-space probe data),
and four version rows sourced from Runtime/updater reports. Missing reports stay
unknown; no synthetic successful component checks are generated.
