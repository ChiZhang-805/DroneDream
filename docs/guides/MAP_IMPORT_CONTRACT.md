# Desktop map upload contract

The UI is a compact checklist, with no help prose or required/optional badges.
Technical requirements belong here and in the parser, not in the dialog.

| Slot | Cardinality | Input | Internal purpose |
| --- | --- | --- | --- |
| Map scene | Exactly one | `.ddpkg`, `.zip`, `.sdf`, `.world`, Open-RMF `.building.yaml` | The source geometry/world; mandatory for import |
| Models & textures | Zero or one directory | Referenced model/texture tree, retaining relative paths | Needed when a loose scene references external resources |
| Places & entrances | Zero or one JSON | `dronedream.map-semantic.v1` | Supplied geometry-linked names, entrances and handoff semantics |
| Navigation network | Zero or one JSON | `dronedream.map-graph.v1` | Supplied nodes/edges; no automatic flight qualification |

A complete DDPKG/ZIP uses only the scene slot. Its existing manifest, resources
and annotations are parsed by the existing Core adapters. For loose Open-RMF
input only scene/resources are shown: its converter generates its own semantic
and navigation representations. Loose Gazebo scenes allow the four separate
slots; supplemental JSON is not required merely to receive/import the scene.
Missing referenced resources or insufficient semantics are handled by the
existing parser/readiness system, not new duplicate client-side validators.

Each selected item is copied to the application's owned cache before its receipt
is returned. A check means bytes received, not selected and not flight-ready.
Cancelling a picker preserves the previous receipt. Replacing the primary scene
starts a fresh composition so another map's annotations cannot carry over.
Files remain received if later normalization fails.

Loose files are assembled into a source ZIP: `world.sdf` (or
`map.building.yaml`), original relative resource paths, `map-semantic.json` and
`navigation-semantic-graph.json`. For Gazebo, an internal manifest explicitly
selects the world entrypoint through the existing source-bundle adapter, so
scenery `model.sdf` files cannot misclassify the map as a vehicle. Duplicate archive paths are rejected rather
than silently overwriting resources. The ordinary import service owns parsing,
normalization, immutable version storage and readiness; an unqualified but
successfully imported version is listed without granting it flight authority.

After import, explicit AI analysis uses the existing authenticated, metered map
interpretation path and stores its result in the interpretation cache. Upload
does not invoke AI. This is grounded map understanding, not generation of missing
physical geometry/real door positions or a fabricated flight-ready route graph.
