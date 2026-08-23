# DroneDream canonical edition brand donor

This directory is the repository-owned source of truth for the shared
DroneDream geometry and the Universal, SIM, LAB, and FIELD visual identities.
The approved concept PNGs under the planning worktree are review inputs only;
no production build reads from `work/`.

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
`source/` also contains the approved pink-purple-blue Universal mother-brand
master. Its colors are preserved exactly rather than recolored during export.
The same directory contains the OFL-licensed Space Grotesk input.
`generated/brand-assets.v1.json` binds every canonical output to exact source,
generator, locked requirements, font, bytes, dimensions, and SHA-256.

Generate or verify all checked-in assets with:

```text
python scripts/build-brand-assets.py
python scripts/build-brand-assets.py --check
```

The generated Windows ICO is the common executable, installer, Start Menu, and
desktop-shortcut icon input for its edition. Wiring an icon into an installer
still requires that edition's own build and release validation. The presence
of a LAB or FIELD color token never grants hardware authority.
