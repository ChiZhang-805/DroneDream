# DroneDream Field adapter notices

This notice covers open-source protocol code compiled into DroneDream · FIELD.
Installing an adapter package activates source-bound data and does not install
additional executable code or grant hardware authority.

## rust-mavlink 0.17.1

DroneDream · FIELD uses `mavlink`, `mavlink-core`, and the build-time
`mavlink-bindgen` crate from the official
[mavlink/rust-mavlink](https://github.com/mavlink/rust-mavlink) project to
decode MAVLink 1 and MAVLink 2 frames for the Common and ArduPilotMega
dialects. The upstream project declares the code under the MIT License or the
Apache License 2.0, at the recipient's option.

Frozen Cargo package checksums:

- `mavlink 0.17.1`: `0df4c9e6c5f14b13459638df2dd35efdc4743b327621d5bfe7801bb850326f44`
- `mavlink-core 0.17.1`: `c9e8f00fd8c85980548571d28ead126f320733bbe27684aa02f1787060d3264d`
- `mavlink-bindgen 0.17.1`: `2052217619766a23bd0181e7ddee6c4661fac7e5179f75c8f802fec551278304`

The corresponding license texts are available in the pinned upstream source:

- [MIT License](https://github.com/mavlink/rust-mavlink/blob/0.17.1/LICENSE-MIT)
- [Apache License 2.0](https://github.com/mavlink/rust-mavlink/blob/0.17.1/LICENSE-APACHE)

MAVLink is a protocol and project name. Its inclusion does not imply validation
of any aircraft, controller, firmware, or Vehicle Pack and does not imply
upstream endorsement of DroneDream.

## serialport 4.9.0

DroneDream · FIELD uses the cross-platform `serialport` crate from the
[serialport-rs](https://github.com/serialport/serialport-rs) project for the
operator-confirmed, bounded read-only serial telemetry probe. The crate is
compiled without its default `libudev` feature and is licensed under the
Mozilla Public License 2.0.

Frozen Cargo package checksum:

- `serialport 4.9.0`: `a4d91116f97173694f1642263b2ff837f80d933aa837e2314969f6728f661df3`

The corresponding license text is available in the pinned upstream source:

- [Mozilla Public License 2.0](https://github.com/serialport/serialport-rs/blob/v4.9.0/LICENSE.txt)

Including the library does not validate a serial device or grant parameter,
arm, flight, or autonomous tuning authority.
