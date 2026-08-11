# DroneDream canonical brand identity

The repository-owned brand contract is `brand/brand-editions.v1.json`. It
defines one shared wing/bat geometry and four presentation identities:

| Identity | Exact lockup | Gradient | Light / dark surface |
| --- | --- | --- | --- |
| Universal | `DroneDream` | `#FF5574` / `#6A4CFF` / `#E657D1` | `#F8F5FF` / `#171225` |
| SIM | `DroneDream · SIM` | `#00D9FF` / `#2671FF` / `#744CFF` | `#F1FAFF` / `#071B31` |
| LAB | `DroneDream · LAB` | `#A7E84A` / `#20C77A` / `#087E69` | `#F3FCEF` / `#092019` |
| FIELD | `DroneDream · FIELD` | `#FFC247` / `#FF754B` / `#D746A5` | `#FFF8EF` / `#28140D` |

Universal is the canonical mother brand. Edition colors and lockups are a
visual mode only. They do not install modules, validate a Vehicle Pack, or
grant simulation or hardware authority.

## Shared geometry

Every identity uses the same rising wing/bat silhouette and the same white
internal flight path. The geometry communicates agile flight, simulator
feedback, and evidence-gated iteration. Never redraw the path per Edition or
turn an Edition palette into a capability flag.

## Lockup contract

- `DroneDream` uses the approved primary mixed-case wordmark.
- Edition lockups add one centered dot and one uppercase Edition name on the
  same line: `DroneDream · SIM`, `DroneDream · LAB`, or `DroneDream · FIELD`.
- Compact lockups use the same geometry and naming contract with the existing
  tracked uppercase responsive wordmark.
- Keep the aspect ratio and clear space. Use the mark alone below a 24 px mark
  height.
- Images are decorative inside navigation; the containing control must retain
  a real accessible text name.

## Canonical source and outputs

- `brand/source/drone-dream-mark-master.png`: the Universal mother-brand
  geometry source.
- `brand/source/approved/`: exact approved SIM/LAB/FIELD 1024 px marks and
  single-line centered-dot lockups. Canonical outputs preserve these bytes
  without re-rendering.
- `brand/source/space-grotesk-latin-wght-normal.woff2`: frozen wordmark font.
- `brand/source/Space-Grotesk-OFL-1.1.txt`: exact OFL-1.1 license text.
- `brand/generated/<edition>/`: canonical mark, lockups, favicon, PNG icon
  sizes, and multi-frame Windows ICO for each identity.
- `brand/generated/brand-assets.v1.json`: bytes, dimensions, source hashes,
  generator hash, font/license hash, and every output SHA-256.
- `brand/generated/edition-brand-preview.png`: light/dark visual review board.
- `frontend/src/assets/brand/`: generated frontend mirrors.
- `frontend/src/brand/edition-brand.generated.{ts,css}`: generated display
  tokens. They explicitly carry no hardware authority.
- `desktop/src-tauri/icons/`: Universal canonical Windows icon mirrors until an
  exact Edition build selects its own canonical ICO.

Approved concept boards are review input, not production or release assets.
No runtime or build reads from the planning `work/` directory.

## Deterministic generation

Run:

```text
python scripts/build-brand-assets.py
python scripts/build-brand-assets.py --check
```

The checked-in contract freezes the approved source hashes, output dimensions,
and ICO frame set. The generator uses only repository-owned inputs and records
its exact dependency lock plus Python, Pillow, fontTools, and zlib versions in
the manifest. A generated icon is an input to a future Edition build; it is not
proof that an installer was built or released.
