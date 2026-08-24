# DroneDream brand assets

`icons/` is the only editable release icon source. It contains exactly two
transparent PNG files for each of the five products: a bat mark and a
bat-plus-wordmark lockup. The ten files, their dimensions, hashes, visible
names, palettes, and safety boundaries are fixed by `editions.json`.

`report/report-watermark.png` is the only technical-report watermark source.
It is separate from product icons and is consumed by the PDF report service.

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
