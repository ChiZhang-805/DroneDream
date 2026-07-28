# Technical-report software evidence

This directory contains software-generated, content-addressed inputs for the
separate report line. It is not the report source tree and contains no
PX4/Gazebo or flight-performance claim.

`evidence.json`, `evidence.manifest.json`, and `evidence.sha256` are the
historical v6 freeze. They remain immutable.

`evidence-v7.json`, `evidence-v7.manifest.json`, `evidence-v7.sha256`, and
`csv-v7/` are the historical Prompt 1.6 / 1,147-test freeze. They also remain
immutable.

The current non-overwriting successor is:

- `evidence-v8.json`: file SHA-256
  `d1b8c1931b64ca5df971e24e34c03f4f202585b852612b11458abeb57a70dd07`;
- `evidence-v8.manifest.json`: file SHA-256
  `6bd08f15b034dccf3922b4ccd95a5e1368dde79a49719dede1e628a002a3dafc`;
- `evidence-v8.sha256`: independent file-hash list;
- `csv-v8/`: chart-ready projections generated from the same verified bundle.

The v8 bundle has canonical content SHA-256
`2dad5492c8e8bd1d91a06db8b6a87c978e45cc139e83e53cf73634324ee9b3d4`,
binds software subject commit
`65a33bbd70f999962afd1bea1e374dcd5e9de460`, and consumes only
`artifacts/test-runs/aurora-software-65a33bb-receipt.json` for passing backend
test claims. That receipt has canonical SHA-256
`8053861b31b5d78f67eef78b04f0c51cec7fff4a609ac95a480ad5c4c8b319cf`
and binds the exact clean-commit run of 1,164 passing tests plus a 27-test
focused supplement.

The initial clean `533500f...` full-suite failure is retained separately as
`artifacts/test-runs/aurora-software-533500f-pytest-failed.log`, file SHA-256
`59b1f8994177259103af6fb5fc3371374c5e3c2a19e1667d60f22746bf477f5d`.
It records 1,161 passes and two load-sensitive failures before the Windows
process cleanup and heartbeat timing repair; it is diagnostic evidence and is
not a passing receipt. Report code may consume the v8 bytes and hashes but must
not edit the software evidence.
