# DroneDream canonical edition brand donor

This directory is the repository-owned source of truth for the shared
DroneDream geometry and the Universal, SIM, LAB, and FIELD visual identities.
The approved concept PNGs under the planning worktree are review inputs only;
no production build reads from `work/`.

`brand-editions.v1.json` freezes the names, centered-dot lockup contract,
palettes, surfaces, export dimensions, font source, and the presentation-only
safety boundary. `source/approved/` contains the exact user-approved SIM, LAB,
and FIELD mark and centered-dot lockup bytes. They are copied into canonical
1024 px/primary outputs without re-rendering; smaller PNG, favicon, and ICO
outputs are deterministic derivatives. `source/` also contains the Universal
mother-brand master and the OFL-licensed Space Grotesk input.
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
