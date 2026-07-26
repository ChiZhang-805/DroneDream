# DroneDream brand identity

## Brand idea

The DroneDream mark is a rising bat drawn inside a compact, near-square visual
footprint. The animal is not decorative:

- **Agile flight** represents the product's purpose: improving UAV control in
  simulation.
- **Echolocation** represents the Harness reading simulator feedback instead of
  guessing from an unconstrained model response.
- **The white echo path** represents the evidence gate. A proposal advances only
  after the relevant experiment, verifier, and provenance checks succeed.
- **The rising three-quarter pose** represents iterative improvement rather than
  a static final answer.
- **Night flight** connects the symbol directly to the `Dream` in DroneDream.

## Core colors

| Role | Color | Hex |
| --- | --- | --- |
| Flight / intelligence | Electric violet | `#684BFF` |
| Simulation / imagination | Light violet | `#9B72FF` |
| Energy / iteration | Magenta | `#F166D8` |
| Forward motion / lift | Coral | `#FF4E70` |
| Precision / verification | Flight blue | `#3A74FF` |
| Evidence path | White | `#FFFFFF` |
| Dark-background fallback | Ink | `#171225` |

The wordmark gradient runs from electric violet through light violet to
magenta. The animal mark extends that system with coral at the rising wing and
flight blue at the lower trailing edge, while violet remains the dominant
bridge color. The mark also needs a single-color violet and a white version for
contexts where gradients are unavailable or do not meet contrast requirements.

## Wordmarks

- **Primary:** `DroneDream` in a geometric semibold face. Use it on the public
  website, report title page, account surfaces, and prominent marketing
  placements.
- **Compact:** `DRONEDREAM` in a heavier, tracked uppercase face. Use it in the
  desktop title area, launch chrome, narrow horizontal placements, and small
  technical labels.

Both wordmarks use the same color progression and the same notched capital
`D`. They are two responsive forms of one identity, not separate logos.

## Usage rules

- Keep the mark's aspect ratio. Never stretch it horizontally or vertically.
- Keep clear space around the mark equal to at least one quarter of the mark's
  visible width.
- Do not add an enclosing tile, glow, drop shadow, technology lines, or animal
  illustration details.
- Use the full lockup at 24 px mark height or larger. Below that size, use the
  mark alone.
- Product navigation may use the fixed raster lockup to preserve the approved
  optical alignment, but the containing link or landmark must expose the real
  accessible name `DroneDream`; the image is never the sole accessible label.
- On busy or low-contrast backgrounds, use the white single-color fallback
  rather than adding effects.

## Source and generated assets

- `docs/assets/drone-dream-logo-source.png`: selected transparent source artwork.
- `docs/assets/drone-dream-icon.png`: normalized 1024 px production mark.
- `docs/assets/brand/`: primary wordmark, compact wordmark, lockups, and preview.
- `frontend/src/assets/drone-dream-mark.png`: standalone product and website mark.
- `frontend/src/assets/drone-dream-lockup-primary.png`: public-site lockup.
- `frontend/src/assets/drone-dream-lockup-compact.png`: desktop compact lockup.
- `frontend/public/drone-favicon.png`: tight 64 px browser icon.
- `desktop/src-tauri/app-icon.png`: source for generated Tauri/Windows icons.

Run `python scripts/build-brand-assets.py` after changing the selected source
artwork. The script requires Pillow and fontTools in the selected Python
environment plus the installed frontend dependencies, which supply the
OFL-licensed Space Grotesk variable font. Regenerate the Windows icon set from
`desktop/src-tauri/app-icon.png` with the Tauri icon command after changing the
mark.
