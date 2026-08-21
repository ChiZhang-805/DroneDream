# DroneDream commercial brand assets

This is the only application- and website-facing PNG directory for the
DroneDream brand. It contains the commercial images for all five products:

- five transparent edition marks;
- five transparent, natural-width edition lockups;
- one white-canvas Universal mark;
- one white-canvas Universal lockup.

The transparent assets have a uniform 5.5% safety margin around their visible
pixels. White-canvas variants preserve the approved source pixels and use one
balanced safety margin; they must not wrap the already padded transparent file
in a second margin. Do not stretch, rebuild, or substitute compact-width
wordmarks at call sites.

The Universal pair preserves the approved legacy masters formerly catalogued
as images 15 and 16: the pink-to-purple horizontal lockup and the matching
standalone mark. Do not substitute the later purple-heavy Universal variant.

Finalize or verify the checked-in commercial masters with:

```text
python scripts/build-commercial-brand-assets.py
python scripts/build-commercial-brand-assets.py --check
```

Windows ICO, favicon, and installer-frame derivatives are packaging assets,
not members of this twelve-image commercial PNG set.

The fifth product keeps the stable internal `autonomy` asset key while its
visible lockup is `DroneDream · AGENT`. The source marks, font license,
packaging derivatives, and build script remain outside this folder because
they are required by the five Windows executable builds. The natural-width
lockups in this directory are the frozen commercial masters. Runtime UI code
must import PNGs only from this directory.
