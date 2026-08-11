# DroneDreamRuntime third-party notices (public beta)

This document is a practical component and source index for the
DroneDreamRuntime public beta. It is informational, is not legal advice, and
is not an exhaustive license audit. The copyright and license terms supplied
by each upstream project continue to apply. Nothing here grants trademark
rights or implies endorsement by an upstream project.

## Release inventory

The current `0.1.0` runtime is built from the reviewed repository inputs
`runtime/pins.env` and `runtime/locks/python-requirements.lock` at the source
commit recorded in `runtime-release.json`. Every built rootfs also records the
effective package closures at:

- `/opt/dronedream/runtime/apt-packages.lock`
- `/opt/dronedream/runtime/python-installed.lock`

Those two generated inventories, this notice, and the corresponding original
license files should be retained with every distributed runtime version.

## Principal components and source locations

- **DroneDream** — MIT License; see the included `DroneDream-LICENSE.txt` and
  the source commit recorded in the runtime manifest.
- **Ubuntu 24.04 (Noble), amd64** — the base image is pinned in `pins.env` by
  OCI digest. Ubuntu contains many independently licensed binary packages, not
  one license for the distribution as a whole. Corresponding Ubuntu source
  packages are available from the [Noble archive on
  Launchpad](https://launchpad.net/ubuntu/noble), using the exact binary
  versions in `apt-packages.lock`.
- **PX4 Autopilot v1.16.0** — pinned commit
  [`6ea3539157ca358c70a515878b77077af7d4611d`](https://github.com/PX4/PX4-Autopilot/tree/6ea3539157ca358c70a515878b77077af7d4611d).
  The top-level project is BSD-3-Clause; its exact
  [LICENSE](https://github.com/PX4/PX4-Autopilot/blob/6ea3539157ca358c70a515878b77077af7d4611d/LICENSE)
  is retained at `/opt/PX4-Autopilot/LICENSE`. PX4 submodules, models, assets,
  and build dependencies may carry separate notices.
- **Gazebo Harmonic** — installed as the `gz-harmonic` metapackage version
  `1.0.0-1~noble` from the OSRF Ubuntu repository. Harmonic is a collection of
  separately versioned and licensed libraries, so this notice does not assign
  one license to the entire collection. The official [Harmonic source
  instructions](https://gazebosim.org/docs/harmonic/install_ubuntu_src/) link
  the collection manifest and component repositories; use
  `apt-packages.lock` to identify the exact binary set in a release.
- **Valkey 8.1.4** — pinned commit
  [`5f4bae3ea10174a7c872cc099c953b0e91afa93a`](https://github.com/valkey-io/valkey/tree/5f4bae3ea10174a7c872cc099c953b0e91afa93a).
  Its exact [`COPYING`](https://github.com/valkey-io/valkey/blob/5f4bae3ea10174a7c872cc099c953b0e91afa93a/COPYING)
  contains two BSD-3-Clause grants and must accompany the compiled binaries.
- **Python distributions** — the full pinned set is in
  `locks/python-requirements.lock`; the installed set is in
  `python-installed.lock`. Upstream source/homepage and license metadata for
  each exact distribution version can be found through its
  [Python Package Index](https://pypi.org/) project page and installed
  `.dist-info/METADATA`. Core simulator bindings include
  [MAVSDK-Python](https://github.com/mavlink/MAVSDK-Python) and
  [pyulog](https://github.com/PX4/pyulog).

## Original notices inside the runtime

For packages installed through Ubuntu or the OSRF apt repository, retain the
package-specific copyright and license files at
`/usr/share/doc/<package>/copyright` (that is,
`/usr/share/doc/*/copyright`). These package files are authoritative and this
summary does not replace them.

Also retain the PX4 repository's license and subcomponent notices and the
license files shipped in Python `.dist-info` directories where provided. The
exact Valkey `COPYING` is distributed as `Valkey-COPYING.txt` beside every
runtime release and inside the Windows application; current runtime builds also
install it at `/usr/share/doc/valkey/COPYING`. A public runtime release is
incomplete if its binary is not accompanied by that original notice.

Before publishing each beta, review the generated apt and Python inventories,
verify that the original notices above are present in the exported rootfs, and
retain access to the corresponding source versions. This document deliberately
does not claim that those checks constitute complete license compliance.
