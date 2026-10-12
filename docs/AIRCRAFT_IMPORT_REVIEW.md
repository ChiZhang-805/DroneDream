# Aircraft and import review — 2026-10-13

This is a source/catalog review, not a new flight test. The pinned Agent Core
`asset_pair_catalog.py` lists one exact qualified pair: normalized
`dronedream.my-drone.v1` (X500 Depth) and `dronedream.school-map.v1` (Kumpula),
qualification `asset-qualification-9e8f76549880788ec9e81ef0`.
The other twelve source models are reviewed catalog resources requiring
dependency resolution and aircraft/map qualification. Their cards and model
previews do not establish mission readiness. Even the qualified built-in pair
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
