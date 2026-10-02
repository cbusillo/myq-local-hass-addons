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

Unresolved release work:

- Reproduce the read on another MYQ-G0401-ES and document a removable fixture.
- Package image-record discovery without specimen-specific offsets or metadata.
- Provide a sensor-binding wizard with controls disabled while identifying it.
- Validate any hardware-free candidate before promising wireless-only setup.

Until those pass, this is an expert-assisted experimental installation, not a
general no-programmer onboarding solution. Ordinary runtime needs only the
bundle; it neither reads hardware nor uploads firmware to a service.
