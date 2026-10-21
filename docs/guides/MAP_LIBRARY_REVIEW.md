# Map library review — 2026-10-12

The current Core `map_resource_catalog.py` explicitly exposes only Kumpula Campus
as a default resource. Its current pair catalog likewise lists that map only.
The previous map-upload change displayed every historical external map version
from bootstrap, accidentally reviving retired Open-RMF demo cards.

Seven installed historical versions were checked read-only: airport-terminal,
battle-royale, campus, clinic, hotel, office, and triple-h. Their IR identifies
the `open-rmf.building-map` adapter and `rmf-building-map-package` format.
They are old converted example environments, not additional current product
maps. Some have September qualification receipts; those records are not proof
of current continuous-model natural-language task acceptance. For example the
office receipt contains no model motion records and a rejected perception
completion check. The old campus scene contains only a ground box.

`retiredMapVersions.json` identifies these exact historical asset IDs and hashes.
The library excludes them during normalization, including subsequent bootstrap
refreshes. This does not erase source bundles, experiment history, or a user's
new version with the same name. Default and imported map deletions persist in
the account/edition library; explicit re-import can restore a removed asset.

The UI now has a New Map card, 60 px captions with 18–22 px names, and a delete
button on the default map. Details use the existing interactive scene renderer
instead of preferred-flight-volume controls, with six or fewer concise facts.
Opening another map no longer replaces its details with the current campus.
The startup panel fits its content and no longer renders the yellow account
verification paragraph. Authentication gate behavior is unchanged.

Verification evidence: `artifacts/test-runs/map-library`, including a seeded
legacy-library migration, default deletion across reload, Select Map consistency,
interactive scene rotation, 1100 × 700 and 1920 × 1080 detail layouts, and four
English/Chinese startup layouts. File-picker format filters were already present
for scene, JSON, and resource-directory slots and remain intact.
