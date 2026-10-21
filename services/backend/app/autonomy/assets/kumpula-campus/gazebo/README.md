# Kumpula Campus runtime map

This package is a local-ENU simulation derivative of current City of Helsinki
building-register footprints and the 2025 Helsinki orthophoto (CC BY 4.0).
Building names are cross-checked against the University of Helsinki campus list
and OpenStreetMap contributors (ODbL 1.0). This is an exterior-only map: it does
not claim rooms, doors, furniture, trees, terrain relief, or photorealistic
facades. Collision boxes are conservative proxies around the footprint-extruded
visual meshes. Historical flight evidence remains attached to the qualification
route, while current missions resolve bilingual semantic endpoints and generate
their own three-dimensional paths from collision geometry at runtime. Delivery
endpoints intentionally contain no authored route edges.
