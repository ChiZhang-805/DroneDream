# DroneDream Field adapter notices

This notice covers open-source protocol code compiled into DroneDream · FIELD.
Installing an adapter package activates source-bound data and does not install
additional executable code or grant hardware authority.

## rust-mavlink 0.18.0

DroneDream · FIELD uses `mavlink`, `mavlink-core`, and the build-time
`mavlink-bindgen` crate from the official
[mavlink/rust-mavlink](https://github.com/mavlink/rust-mavlink) project to
decode MAVLink 1 and MAVLink 2 frames for the Common and ArduPilotMega
dialects. The upstream project declares the code under the MIT License or the
Apache License 2.0, at the recipient's option.

Frozen Cargo package checksums and source revision:

- `mavlink 0.18.0`: `ef539c358c31f69d47816dac709eebbcb733166ae1bcdeeb4463383c042e3e7c`
- `mavlink-core 0.18.0`: `b31cc9f930c7edce0c1933659d405a330a28346cdf087bd283a56a6d72eb3d85`
- `mavlink-bindgen 0.18.0`: pinned upstream Git revision
  `ac3491fd415b15f0f89cf8523d38c2bf42399c50`

The corresponding license texts are available in the pinned upstream source:

- [MIT License](https://github.com/mavlink/rust-mavlink/blob/0.18.0/LICENSE-MIT)
- [Apache License 2.0](https://github.com/mavlink/rust-mavlink/blob/0.18.0/LICENSE-APACHE)

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

## MultiWii Serial Protocol parser 0.1.1

The managed Betaflight / INAV package uses the pinned
`multiwii_serial_protocol 0.1.1` crate only to inspect complete captured MSP v1
frames. The crate is licensed under MIT OR Apache-2.0. DroneDream does not send
MSP requests or commands through this package.

- [Crate source and license metadata](https://crates.io/crates/multiwii_serial_protocol/0.1.1)
- [Betaflight MSP protocol reference](https://betaflight.com/docs/development/MSP-Protocol-Reference-Dev)

## DroneCAN parser 0.1.0

The managed DroneCAN package uses the pinned `dronecan 0.1.0` crate to decode
captured 29-bit identifiers and transfer framing. The crate is licensed under
Mozilla Public License 2.0. The DroneCAN specification and its reference
implementations are openly published by the DroneCAN project.

- [Crate source and license metadata](https://crates.io/crates/dronecan/0.1.0)
- [DroneCAN specification](https://dronecan.github.io/Specification/1._Introduction/)

## Bitcraze Crazy RealTime Protocol

The managed Crazyflie package contains only DroneDream protocol metadata. Its
offline frame inspector follows Bitcraze's published CRTP packet header and
30-byte payload limit; it does not bundle cflib, Crazyradio drivers, or a live
link implementation.

- [Bitcraze CRTP specification](https://www.bitcraze.io/documentation/repository/crazyflie-firmware/master/functional-areas/crtp/)

## Ryze Tello SDK 2.0 State

The managed Tello package contains only DroneDream protocol metadata and a
strict parser for an offline-captured SDK 2.0 state datagram. It follows the
state-field format published by Ryze Technology. DroneDream does not
redistribute a Tello SDK binary, open a live UDP session, enter SDK command
mode, or send takeoff, landing, movement, or other control commands.

- [Official Tello SDK 2.0 User Guide](https://dl-cdn.ryzerobotics.com/downloads/Tello/Tello%20SDK%202.0%20User%20Guide.pdf)

The guide and Tello product names remain the property of their respective
owners. This compatibility metadata does not imply endorsement or validation
of any Tello aircraft.

Installing or using any of these data-only packages does not validate a
Vehicle Pack and does not grant parameter, arm, flight, or autonomous tuning
authority.
