# AUTONOMY core promotion provenance

This public component was promoted from the private DroneDream AUTONOMY incubation
repository at commit `cf7927a` (`Prepare generated plugin resources for Rust checks`).

The promotion deliberately includes the reusable engineering core:

- Python Harness, application service, first-party plugin catalog, and plugin SDK;
- versioned structured-input/output JSON Schemas;
- ROS 2 messages, safety guard, Gazebo observer, and `pluginlib` host;
- PX4/Gazebo runtime adapters and bounded acceptance runners;
- unit, contract, lifecycle, interruption, replan, and plugin isolation tests;
- compact simulation evidence manifests and architecture documentation.
- the three small compiled default-asset qualification fixtures (`index.json`,
  `school-map.zip`, and `my-drone.zip`) required to reproduce asset acceptance tests.

The private repository's standalone frontend, standalone Tauri shell, generated
installer animation frames, build caches, virtual environment, and local artifacts
are not copied. The compiled fixtures above are evidence-bound test inputs, not the
authoritative editable geometry or physics source. The public five-product shell and
its signed Map Pack, Vehicle Pack, Runtime, updater, OAuth, and installer contracts
remain authoritative for those responsibilities.

Future promotion from private incubation must use an ordinary reviewed change. It
must record the source commit, preserve the public MIT license, pass the protected
repository checks, and must not weaken product-specific hardware authority gates.
