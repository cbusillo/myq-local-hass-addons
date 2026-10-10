# Hardware support

myQ products with similar names can use different processors, flash layouts,
firmware, message formats, and enrollment procedures. Match the board model and
firmware before following any hardware instructions.

## MYQ-G0401-ES hub

- Qualified firmware: **1.10**
- Typical paired sensor in this project: **HBW9546**
- Status: maintained here
- Runtime: the root [`myq_local`](../myq_local/) Home Assistant app
- Enrollment: one-time hardware read of the device identity, TLS PSK, and
  paired door identifier; ordinary use does not require a programmer or
  modified firmware

The packaged app passed an owner-observed Home Assistant open/close cycle on one
specimen, and its source and isolated package tests pass. A repeatable
credential-acquisition guide remains before this is a consumer-ready path.

## 050DCTWF logic board

- Qualified firmware in the source project: **3.13**
- Processor family: Marvell MW300
- Status: community reference
- Runtime and research: [`community/050dctwf`](../community/050dctwf/README.md)
- Enrollment: physical SPI-flash read using the source project's board-specific
  instructions

StanleyCA tested this path in the source project. The current maintainer does
not own a 050DCTWF board, so imported code and instructions can be preserved and
improved through community contributions but cannot yet receive hardware-backed
acceptance here.

## What the labels mean

**Maintained** means changes can be exercised against hardware owned by the
current maintainer. It does not expand validation beyond the exact models,
firmware, sensors, and acceptance evidence stated in the documentation.

**Community reference** means the original project supplied hardware-backed
evidence, but this repository cannot independently reproduce new changes on
that hardware. Reports and contributions are welcome. A change should not be
described as hardware-tested unless someone with the named board and firmware
actually performed the test and records what they observed.

No path supports every product sold under the myQ or Security 2.0 names. Do not
apply flash offsets, wiring, or firmware assumptions from one row to another.
