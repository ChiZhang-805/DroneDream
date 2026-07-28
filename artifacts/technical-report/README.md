# Technical-report software evidence

This directory contains software-generated, content-addressed inputs for the
separate report line. It is not the report source tree and contains no
PX4/Gazebo or flight-performance claim.

`evidence.json`, `evidence.manifest.json`, and `evidence.sha256` are the
historical v6 freeze. They remain immutable.

The current non-overwriting successor is:

- `evidence-v7.json`: file SHA-256
  `93232a2f0027503c24cfe4a8a1768d518f436cd35a3db72e788fc42f5eb45c55`;
- `evidence-v7.manifest.json`: file SHA-256
  `0702abb2e5d1aedb999c4158feaab78b25f6dc2ab7dcc07b5bcefad2b30324d2`;
- `evidence-v7.sha256`: independent file-hash list;
- `csv-v7/`: chart-ready projections generated from the same verified bundle.

The v7 bundle has canonical content SHA-256
`a0432d092d5e751a6f414ba4d0cb6b91cb7e9117b6fead109ef2a1c805ad8522`,
binds software subject commit
`742b12467efc9b37b7e4a2fa3ac73b7578f21385`, and consumes only
`artifacts/test-runs/aurora-software-742b124-receipt.json` for backend test
claims. Report code may consume these bytes and hashes but must not edit the
software evidence.
