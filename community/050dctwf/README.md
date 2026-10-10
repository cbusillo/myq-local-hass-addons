# 050DCTWF community package

This directory preserves StanleyCA's local Home Assistant bridge and research
for the **050DCTWF logic board running firmware 3.13**. It includes the original
bridge, flash-read instructions, analysis tools, tests, and reverse-engineering
writeup.

Start with the preserved [upstream README](UPSTREAM_README.md), then follow its
[flash guide](FLASH_GUIDE.md). Those instructions apply to the 050DCTWF board
and its Marvell flash layout. They do not apply to the MYQ-G0401-ES hub supported
by the root app.

## Support status

StanleyCA developed and tested this package on the named hardware. The current
maintainer does not own a 050DCTWF board, so this is currently a community
reference path:

- The imported source and documentation are retained in one discoverable home.
- Community reports and contributions are welcome.
- Changes are not described as hardware-tested without a recorded test on a
  050DCTWF running the applicable firmware.
- The root `myq_local` app is not a drop-in replacement for this package. The
  devices use different protocol details and enrollment procedures.

## Import validation

At import time, all eight original bridge unit tests passed under the root
project's Python environment. A clean `linux/amd64` container rebuild did not:
the pinned Alpine package list requires Python 3.14.7 and libexpat 2.8.4, while
the package repository used by the pinned base image now resolves newer patch
versions. The snapshot remains unchanged so this repository does not silently
claim a hardware-unverified dependency update. Treat the original image build
instructions as historical until a contributor updates the lock, runs its
container tests, and validates the result on a 050DCTWF.

[`SOURCE.md`](SOURCE.md) records the exact source snapshot. The imported files
remain available under their original AGPL-3.0 license in [`LICENSE`](LICENSE).
No firmware image, flash dump, capture, or device credential is included.

## Directory map

- [`myq_local`](myq_local/): original Home Assistant app
- [`FLASH_GUIDE.md`](FLASH_GUIDE.md): board-specific SPI read and enrollment
- [`WRITEUP.md`](WRITEUP.md): firmware, TLS-PSK, MQTT, and HomeKit research
- [`analysis`](analysis/): flash, PSM, disassembly, and capture-analysis tools
- [`tests`](tests/): original source and container tests
- [`BUILDING.md`](BUILDING.md): pinned image build and validation procedure

Return to the repository-wide [hardware support matrix](../../docs/hardware-support.md)
before using information from this package with any other myQ product.
