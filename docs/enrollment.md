# Enrollment status

This version imports an already prepared private enrollment bundle. Its format
is:

```json
{
  "schema": 1,
  "model": "MYQ-G0401-ES",
  "identity": "<10 hexadecimal ASCII characters>",
  "psk": "<32 hexadecimal characters encoding the 16-byte PSK>",
  "door_id": "<12 hexadecimal characters encoding the paired 6-byte ID>"
}
```

The serial/identity alone does not determine the PSK. A captured TLS handshake
contains the identity, not the key. The paired door ID must be bound to the
actual sensor; selecting the first inventory slot on another hub is insufficient.

The validated fallback acquired an unchanged mapped firmware image once and
privately recovered credentials from its device-specific records. The image
was hash-verified and the recovered material accepted by the stock hub's live
TLS session. The reader was disconnected before garage validation.

A mapped CPU view is not established as a raw, restorable flash backup. This
installation requires neither flashing nor credential-provisioning setters.
Do not write either as an enrollment shortcut.

## Proven acquisition boundary

The successful specimen read used an ST-Link with OpenOCD to read the running
Realtek device through its SWD debug port. It read the mapped AP1 window from
`0x08000000` through `0x087fffff` as 2,048 independently checked 4 KiB chunks.
Every chunk was read twice and both copies matched. The process did not halt or
reset the CPU and did not erase, program, unlock, or write target memory.

That result establishes a read-only acquisition method for this specimen, but
it is not yet a general installation recipe:

- The public documentation does not yet identify and photograph a repeatable
  connector or test-point fixture.
- The eight-megabyte mapped address window may reflect live translation, caching,
  or decryption. It must not be advertised as a raw or restorable SPI backup.
- The CPU continued running, so matching sequential reads do not make the image
  an atomic snapshot.
- The current reader and credential parser still need to be reduced to a
  bounded, reviewed tool that emits only the enrollment bundle and verification
  results.

Until those pieces exist and pass a second owner-observed acquisition, do not
publish copy-and-paste debug commands or ask users to improvise wiring. A failed
read should stop without automatically increasing voltage, changing clock
speed, retrying destructive operations, or writing anything to the hub.

## Intended guided workflow

The next supported installer should:

1. Confirm the exact MYQ-G0401-ES hardware and firmware before connecting.
2. Show the physical fixture and verify voltage, ground, and debug identity.
3. Perform read-only, bounded, checkpointed acquisition with two matching reads
   for every required region.
4. Select current records according to the firmware's append-log rules rather
   than using specimen-specific offsets alone.
5. Generate `enrollment.json` locally without printing the identity, PSK, door
   identifier, firmware bytes, or credential-derived hashes.
6. Start the Home Assistant app with controls disabled and bind the intended
   sensor from authenticated inventory and live status.
7. Remove the debug fixture before any supervised motion qualification.

The firmware image and enrollment bundle remain on the owner's computer. This
project does not need to receive or redistribute either one.

Unresolved release work:

- Reproduce the read on another MYQ-G0401-ES and document a removable fixture.
- Package bounded acquisition and image-record discovery without relying only
  on specimen-specific offsets or metadata.
- Provide a sensor-binding wizard with controls disabled while identifying it.
- Validate any hardware-free candidate before promising wireless-only setup.

Until those pass, this is an expert-assisted experimental installation, not a
general no-programmer onboarding solution. Ordinary runtime needs only the
bundle; it neither reads hardware nor uploads firmware to a service.
