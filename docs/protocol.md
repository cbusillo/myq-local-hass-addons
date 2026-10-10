# Qualified protocol behavior

The qualified specimen is MYQ-G0401-ES stock firmware 1.10 and HBW9546.
TLS 1.2 uses PSK-AES128-CBC-SHA, a ten-byte ASCII identity, and a sixteen-byte
per-device PSK. The bridge verifies that identity and limits the accepted LAN
peer addresses. No certificate substitution obtains the PSK.

The hub uses MQTT 3.1.1 with a clean session and 360-second keepalive. It
subscribes at QoS 0 to `G/<identity>/#`. The client publish prefix is
`S/<identity-first-two-characters>/<identity>/`, not a fixed prefix copied from
another model.

One `012/0040` zero-filled 32-byte startup reply satisfies this firmware's
readiness requirement. `014/0008` lists six-byte device identifiers. The
enrolled door must occur exactly once in that inventory, regardless of order.

The `011/0000` body is twelve bytes: target ID (6), little-endian RC2 message
(2), little-endian 20-bit value in three bytes, and a zero reserved byte.

| Purpose | RC2 message | Value | Evidence |
| --- | --- | --- | --- |
| Status query | `0x0080` | `0` | Firmware trace and successful live local polling |
| Open | `0x0280` | `0x10100` | Authenticated native capture and owner-observed local opening |
| Close | `0x0280` | `0x00100` | Authenticated native capture and owner-observed local closure |
| Position report | `0x0081` | Bits 16–19 | State 2 closed; state 9 not closed, associated with owner observations |

Bit 14 stayed set during a successful open/close cycle. It is not qualified as
an obstruction flag. Other RC2 reports, including `0x00E5`, are uninterpreted;
no battery percentage, fault status, or stop action is inferred.

The first field test validated two explicit local motion requests, matching
state transitions `2 → 9 → 2`, and owner observation. It used a bounded
temporary router transaction, with independent rollback verification. A later
installed Home Assistant app test validated one explicit open and one explicit
close with matching physical and reported states. Neither test establishes
prolonged service stability, additional units, or programmer-free enrollment.

The package tests validate exact bytes, binding despite inventory reorder,
freshness, duplicate/pending requests, stream fragmentation, and queued-command
removal across reconnection. Its container smoke test validates the real PSK
listener and MQTT broker with invented credentials, retained-command rejection,
and repeated explicit cycles. They do not replace a packaged field test.
