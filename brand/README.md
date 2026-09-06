# DroneDream brand assets

`icons/` is the only editable release icon source. It contains exactly two
transparent PNG files for each of the five products: a bat mark and a
bat-plus-wordmark lockup. The ten files, their dimensions, hashes, visible
names, palettes, and safety boundaries are fixed by `editions.json`.

`brand-editions.v1.json` freezes the names, centered-dot lockup contract,
palettes, surfaces, export dimensions, font source, and the presentation-only
safety boundary. `source/approved/` contains the exact user-approved SIM, LAB,
and FIELD mark and large-edition-label lockup bytes. Edition labels use the
approved roughly 90% wordmark-height treatment and preserve natural text width.
The separator is optically and geometrically centered by requiring equal
transparent alpha-edge gaps between the end of `DroneDream`, the separator,
and the first edition-label letter. The previous off-center large-label
lockups remain as superseded review evidence.
They are copied into canonical 1024 px/primary outputs without re-rendering;
smaller PNG, favicon, and ICO outputs remain deterministic derivatives of the
unchanged marks. The retired small-label lockups have been deleted; only the
approved large-edition-label centered lockups are canonical release inputs.
`source/` also contains the Universal mother-brand master and the OFL-licensed
Space Grotesk input. The public website favicon is intentionally independent
from the Universal application mark: the exact user-approved mainland-preview
PNG lives at `source/approved/website-favicon-64.png` and is copied byte-for-byte
to the public site so brand regeneration cannot replace it.
Windows PNG/ICO files and the browser favicon are deterministic build
derivatives. They are generated into ignored temporary paths and removed after
the build; they must never be checked in as additional brand designs.

Validate all canonical assets:

```text
python scripts/build-brand-assets.py --check
```

Generate one edition's temporary Windows assets and favicon:

```text
python scripts/build-brand-assets.py --edition universal
```

The visible fifth-edition name is `DroneDream · AGENT`; `autonomy` remains an
internal compatibility identifier only. Brand assets are presentation inputs
and never grant simulation or hardware authority.
