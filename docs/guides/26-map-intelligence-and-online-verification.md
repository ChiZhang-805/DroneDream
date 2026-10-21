# Map intelligence and optional online verification

New maps need a durable, evidence-bound world model before they can enter mission
qualification.  A visually plausible overlay is insufficient: every building,
entrance, handoff point, junction and road segment must have an identity, coordinates,
provenance and confidence state.  Every route endpoint must meet its referenced node,
the navigation graph must be connected, and route geometry must avoid building,
vegetation, wall and restricted-area footprints.

Evidence also declares what it proves.  A scene mesh may prove a building footprint
without proving that a faint strip is a road.  A verified route needs durable evidence
for both its centerline and traversability; a verified entrance needs entrance-location
evidence.  Generic geometry confidence cannot substitute for either claim.

## Processing stages

1. Admit the uploaded files without executing imported code.
2. Register coordinate frames, scale and scene-to-geographic transforms.
3. Build durable candidates from the uploaded scene, user-provided place data,
   licensed OpenStreetMap data, local image/geometry analysis and sensor traces.
4. Bind buildings to all known entrances and outdoor handoff points.  Unknown
   entrances remain unknown; an automatically chosen facade point is not called a
   surveyed entrance.
5. Construct one topology edge per real bidirectional road or path.  A UI may draw
   two lane lines, but it must not create duplicate reverse edges.  Centerline points
   follow the road, parking aisle or visible forest path rather than a straight-line
   shortcut.
6. Reject missing endpoints, coordinate mismatches, disconnected components,
   overlapping reverse duplicates, self-crossing or jittering centerlines, obstacle
   crossings and off-map extensions.  Distinct alternate paths between the same two
   junctions remain valid graph edges.
7. Present unresolved items for operator review and then run route planning, physical
   simulation and qualification flights.  Passing geometry checks alone does not
   prove a real doorway or a flyable route.

The backend contract for these checks is implemented in
`services/backend/app/autonomy/map_intelligence.py`.

## Analysis modes and budget

- `local` is the normal import path.  It never spends online quota and remains fully
  usable offline.
- `balanced` and `deep` may prepare online verification requests only after the user
  explicitly starts enrichment and supplies a positive call budget.
- Paid calls target unresolved, high-value questions instead of testing every pair of
  points.  Entrance gaps are checked first, followed by disconnected components,
  candidate paths and GPS traces.
- Online checks are not planned until the map has durable coordinate-registration
  evidence and the queried points have geographic coordinates or a resolved place ID.
- Missing credentials, quota exhaustion, network errors and provider failures return
  to the complete local result.  They never fail the upload or erase local work.

## Google Maps boundary

Google Maps Platform can help review uncertain candidates:

- Places API (New) can return `entrances` and road-side `navigationPoints` for a
  resolved place.
- Routes API can compare selected endpoints and reveal whether a locally disconnected
  component probably has a real walking or driving connection.
- Roads API can compare a GPS-derived trace with nearby roads.

These results are advisory.  DroneDream stores them only as expiring hints for at
most 30 days and never promotes them directly into exported Map Packs, a non-Google
map display, training data or durable route truth.  A durable correction must be
supported independently by uploaded/licensed data, local geometry or vision,
operator review, or a qualification observation.  This boundary is enforced by the
map evidence model and durable graph hash.

The language model receives a compact reasoning packet containing the durable graph
hash, unresolved issues and expiring hints.  It may propose which entrance, junction
or route should be checked next; the packet explicitly denies it qualification
authority and requires it to preserve coordinate registration, avoid invented
entrances and return every proposed route to deterministic graph and obstacle checks.

Product integration must use official APIs rather than browser scraping.  Relevant
references:

- <https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places>
- <https://developers.google.com/maps/documentation/routes/compute_route_directions>
- <https://developers.google.com/maps/documentation/roads/snap>
- <https://cloud.google.com/maps-platform/terms/maps-service-terms>

## Acceptance requirements

A generated overlay and its execution graph use the same canonical node and edge
coordinates.  Review covers the entire map, including parking areas, faint forest
paths and map boundaries.  Off-campus roads without a mission-relevant building or
connection are excluded.  The final graph must be connected for all admitted mission
points, while genuinely separate regions remain blocked until their transition is
described and qualified.
